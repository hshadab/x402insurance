"""
Health blueprint — /health, /ping, /invocations, /api/reserves, /metrics
"""
import os
import time
import logging
from flask import Blueprint, request, jsonify, current_app, Response
from core.utils import iso_utc_now
import extensions as ext

health_bp = Blueprint('health', __name__)
logger = logging.getLogger("x402insurance")


@health_bp.route('/ping')
def ping() -> tuple[Response, int]:
    import time as _time
    return jsonify({"status": "Healthy", "time_of_last_update": int(_time.time())}), 200


@health_bp.route('/invocations', methods=['POST'])
def invocations() -> tuple[Response, int]:
    payload = request.get_json(silent=True) or {}
    endpoint = payload.get("endpoint", "/api")
    method = payload.get("method", "GET").upper()
    body = payload.get("body", {})
    headers = payload.get("headers", {})

    with current_app.test_client() as client:
        if method == "POST":
            resp = client.post(endpoint, json=body, headers=headers)
        elif method == "GET":
            resp = client.get(endpoint, headers=headers, query_string=payload.get("query", {}))
        else:
            resp = client.get(endpoint)
        result = {
            "statusCode": resp.status_code,
            "body": resp.get_json(silent=True) or resp.get_data(as_text=True),
            "headers": dict(resp.headers),
        }
    return jsonify(result), 200


@health_bp.route('/health')
def health() -> tuple[Response, int]:
    cfg = ext.config
    include_blockchain = request.args.get('full', 'false').lower() == 'true'

    health_data = {
        "status": "healthy",
        "timestamp": iso_utc_now(),
        "version": os.getenv("SENTRY_RELEASE", "dev"),
        "environment": cfg.ENV if hasattr(cfg, 'ENV') else os.getenv('ENV', 'unknown'),
        "checks": {}
    }

    is_healthy = True
    is_degraded = False

    # 1. Jolt Atlas Prover Check
    try:
        jolt_binary_exists = os.path.exists(cfg.JOLT_BINARY_PATH) if hasattr(cfg, 'JOLT_BINARY_PATH') else False
        health_data["checks"]["jolt_atlas"] = {
            "status": "operational",
            "binary_exists": jolt_binary_exists,
            "mode": "jolt-atlas-snark",
            "model_hash": ext.proof_client.model_hash if ext.proof_client else None,
        }
    except Exception as e:
        health_data["checks"]["jolt_atlas"] = {"status": "error", "error": str(e)}
        is_degraded = True

    # 2. Blockchain RPC Check
    if include_blockchain:
        try:
            bc_connected = ext.blockchain.w3.is_connected() if ext.blockchain else False
            if bc_connected:
                try:
                    chain_id = ext.blockchain.w3.eth.chain_id
                    block_number = ext.blockchain.w3.eth.block_number
                    gas_price = ext.blockchain.w3.eth.gas_price
                    health_data["checks"]["blockchain"] = {
                        "status": "connected", "chain_id": chain_id,
                        "latest_block": block_number,
                        "gas_price_gwei": float(ext.blockchain.w3.from_wei(gas_price, 'gwei'))
                    }
                except Exception:
                    health_data["checks"]["blockchain"] = {"status": "connected"}
            else:
                health_data["checks"]["blockchain"] = {"status": "disconnected"}
                is_healthy = False
        except Exception as e:
            health_data["checks"]["blockchain"] = {"status": "error", "error": str(e)}
            is_healthy = False
    else:
        health_data["checks"]["blockchain"] = {"status": "skipped", "info": "Use ?full=true for blockchain checks"}

    # 3. Wallet Check
    if include_blockchain:
        try:
            wallet_address = cfg.BACKEND_WALLET_ADDRESS
            eth_balance = ext.blockchain.w3.eth.get_balance(wallet_address)
            usdc_balance = ext.blockchain.get_balance()
            health_data["checks"]["wallet"] = {
                "status": "configured", "address": wallet_address,
                "eth_balance": float(ext.blockchain.w3.from_wei(eth_balance, 'ether')),
                "usdc_balance": usdc_balance
            }
            if eth_balance < ext.blockchain.w3.to_wei(0.001, 'ether'):
                health_data["checks"]["wallet"]["warning"] = "Low ETH balance for gas"
                is_degraded = True
            if usdc_balance < 0.1:
                health_data["checks"]["wallet"]["warning"] = "Low USDC balance for refunds"
                is_degraded = True
        except Exception as e:
            health_data["checks"]["wallet"] = {"status": "error", "error": str(e)}
            is_degraded = True
    else:
        health_data["checks"]["wallet"] = {"status": "skipped"}

    # 4. Database Check
    try:
        policies = ext.database.get_all_policies()
        active_policies = [p for p in policies.values() if p.get('status') == 'active']
        health_data["checks"]["database"] = {
            "status": "operational",
            "backend": "postgresql" if cfg.DATABASE_URL else "json",
            "total_policies": len(policies),
            "active_policies": len(active_policies)
        }
    except Exception as e:
        health_data["checks"]["database"] = {"status": "error", "error": str(e)}
        is_healthy = False

    # 5. Reserve Health Check
    if include_blockchain:
        try:
            policies = ext.database.get_all_policies()
            active_policies = [p for p in policies.values() if p.get('status') == 'active']
            total_coverage = sum(p.get('coverage_amount', 0) for p in active_policies)
            if total_coverage > 0:
                usdc_balance = ext.blockchain.get_balance()
                reserve_ratio = usdc_balance / total_coverage
                min_reserve_ratio = cfg.MIN_RESERVE_RATIO
                health_data["checks"]["reserves"] = {
                    "status": "healthy" if reserve_ratio >= min_reserve_ratio else "low",
                    "usdc_balance": usdc_balance, "total_coverage": total_coverage,
                    "reserve_ratio": round(reserve_ratio, 2), "min_ratio": min_reserve_ratio
                }
                if reserve_ratio < 1.0:
                    health_data["checks"]["reserves"]["status"] = "critical"
                    is_healthy = False
                elif reserve_ratio < min_reserve_ratio:
                    health_data["checks"]["reserves"]["status"] = "low"
                    is_degraded = True
            else:
                health_data["checks"]["reserves"] = {"status": "healthy", "message": "No active policies"}
        except Exception as e:
            health_data["checks"]["reserves"] = {"status": "error", "error": str(e)}
            is_degraded = True
    else:
        health_data["checks"]["reserves"] = {"status": "skipped"}

    # 6. Payment Verifier / Facilitator Check
    try:
        if cfg.FACILITATOR_URL and cfg.FACILITATOR_URL != "none":
            import httpx
            fac_start = time.monotonic()
            try:
                fac_resp = httpx.get(cfg.FACILITATOR_URL, timeout=5.0)
                fac_latency_ms = round((time.monotonic() - fac_start) * 1000, 1)
                health_data["checks"]["payment_verifier"] = {
                    "status": "operational" if fac_resp.status_code < 500 else "degraded",
                    "mode": "facilitator",
                    "facilitator_url": cfg.FACILITATOR_URL,
                    "facilitator_status": fac_resp.status_code,
                    "latency_ms": fac_latency_ms,
                }
            except Exception as fac_err:
                fac_latency_ms = round((time.monotonic() - fac_start) * 1000, 1)
                health_data["checks"]["payment_verifier"] = {
                    "status": "degraded",
                    "mode": "facilitator",
                    "error": str(fac_err),
                    "latency_ms": fac_latency_ms,
                }
                is_degraded = True
        else:
            health_data["checks"]["payment_verifier"] = {"status": "operational", "mode": "local"}
    except Exception as e:
        health_data["checks"]["payment_verifier"] = {"status": "error", "error": str(e)}
        is_degraded = True

    # 7. Redis Check (for Huey task queue — not needed in dashboard-only mode)
    if current_app.config.get('DASHBOARD_ONLY'):
        health_data["checks"]["redis"] = {"status": "skipped", "info": "Not required in dashboard mode"}
    else:
        try:
            import redis
            redis_url = cfg.REDIS_URL if hasattr(cfg, 'REDIS_URL') else "redis://localhost:6379/0"
            redis_start = time.monotonic()
            r = redis.from_url(redis_url, socket_connect_timeout=3)
            r.ping()
            redis_latency_ms = round((time.monotonic() - redis_start) * 1000, 1)
            health_data["checks"]["redis"] = {
                "status": "connected",
                "latency_ms": redis_latency_ms,
            }
        except ImportError:
            health_data["checks"]["redis"] = {"status": "skipped", "info": "redis package not installed"}
        except Exception as e:
            health_data["checks"]["redis"] = {"status": "error", "error": str(e)}
            is_degraded = True

    # 8. RPC Latency Measurement
    if include_blockchain and ext.blockchain:
        try:
            rpc_start = time.monotonic()
            ext.blockchain.w3.eth.block_number
            rpc_latency_ms = round((time.monotonic() - rpc_start) * 1000, 1)
            health_data["checks"]["rpc_latency"] = {
                "status": "operational",
                "latency_ms": rpc_latency_ms,
            }
        except Exception as e:
            health_data["checks"]["rpc_latency"] = {"status": "error", "error": str(e)}

    # 9. Monitoring Check
    try:
        sentry_enabled = bool(cfg.SENTRY_DSN)
        health_data["checks"]["monitoring"] = {"status": "enabled" if sentry_enabled else "disabled", "sentry": sentry_enabled}
        if not sentry_enabled and os.getenv('ENV') == 'production':
            health_data["checks"]["monitoring"]["warning"] = "Sentry recommended for production"
    except Exception as e:
        health_data["checks"]["monitoring"] = {"status": "error", "error": str(e)}

    if not is_healthy:
        health_data["status"] = "unhealthy"
        http_status = 503
    elif is_degraded:
        health_data["status"] = "degraded"
        http_status = 200
    else:
        health_data["status"] = "healthy"
        http_status = 200

    return jsonify(health_data), http_status


@health_bp.route('/api/reserves')
def reserves() -> tuple[Response, int]:
    try:
        health = ext.reserve_monitor.check_reserve_health()
        return jsonify(health), 200
    except Exception as e:
        logger.exception("Error checking reserves: %s", e)
        return jsonify({"error": str(e)}), 500


@health_bp.route('/metrics')
def metrics() -> tuple[bytes, int, dict[str, str]]:
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}
