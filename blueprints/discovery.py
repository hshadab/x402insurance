"""
Discovery blueprint — /, /docs, /api, /api/dashboard, /api/pricing, /api/schema, /.well-known/agent-card.json
"""
import json
from pathlib import Path
from flask import Blueprint, request, jsonify, send_from_directory, redirect
import extensions as ext

discovery_bp = Blueprint('discovery', __name__)


@discovery_bp.route('/')
def index():
    return send_from_directory('static', 'dashboard.html')


@discovery_bp.route('/docs')
def docs():
    return redirect('/#docs')


@discovery_bp.route('/view/<page>')
def json_viewer(page):
    if page in ('pricing', 'schema', 'agent-card'):
        return redirect('/#' + page)
    return "Not found", 404


@discovery_bp.route('/api')
def api_info():
    base_url = request.host_url.rstrip('/')
    cfg = ext.config

    return jsonify({
        "service": "x402 Insurance API",
        "version": "1.0.0",
        "x402Version": 2,
        "description": "ZKP-verified insurance for x402 API failures. Protect your micropayment API calls from service downtime and errors with zero-knowledge proof verified insurance.",
        "category": "insurance",
        "provider": "x402 Insurance",
        "endpoints": {
            "discovery": "GET /.well-known/agent-card.json",
            "schema": "GET /api/schema",
            "pricing": "GET /api/pricing",
            "dashboard": "GET /api/dashboard",
            "create_policy": "POST /insure (x402 payment required)",
            "submit_claim": "POST /claim",
            "verify_proof": "POST /verify (public)",
            "get_proof": "GET /proofs/<claim_id> (public)"
        },
        "x402": {
            "accepts": [
                {
                    "scheme": "exact",
                    "network": cfg.CAIP2_NETWORK,
                    "maxAmountRequired": str(int(ext.MAX_COVERAGE * ext.PREMIUM_PERCENTAGE * 1_000_000)),
                    "asset": ext.USDC_ADDRESS,
                    "payTo": ext.BACKEND_ADDRESS,
                    "description": "Insurance premium (1% of requested coverage)",
                    "maxTimeoutSeconds": 60,
                    "extra": {}
                }
            ],
            "resource": {"url": "/insure", "method": "POST"}
        },
        "status": "operational",
        "links": {
            "documentation": f"{base_url}/api/schema",
            "pricing": f"{base_url}/api/pricing",
            "agentCard": f"{base_url}/.well-known/agent-card.json"
        }
    })


@discovery_bp.route('/api/dashboard')
def dashboard_data():
    import logging

    logger = logging.getLogger("x402insurance")

    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)

    policies = []
    claims = []
    total_coverage = 0
    total_policies = 0
    claims_paid = 0

    if ext.database:
        try:
            policies_dict = ext.database.get_all_policies(limit=limit, offset=offset)
            claims_dict = ext.database.get_all_claims(limit=limit, offset=offset)
            policies = list(policies_dict.values())
            claims = list(claims_dict.values())
            total_coverage = sum(p.get('coverage_amount', 0) for p in policies if isinstance(p, dict) and p.get('status') == 'active')
            total_policies = len(policies)
            claims_paid = sum(c.get('payout_amount', 0) for c in claims if isinstance(c, dict) and c.get('status') == 'paid')
        except Exception as e:
            logger.warning("Database unavailable for dashboard: %s", e)

    blockchain_stats = None
    blockchain = ext.blockchain
    if blockchain:
        try:
            from web3 import Web3
            w3 = blockchain.w3
            eth_balance = w3.eth.get_balance(blockchain.account.address)
            eth_balance_formatted = f"{w3.from_wei(eth_balance, 'ether'):.4f}"
            usdc_balance = 0
            try:
                usdc = blockchain.usdc
                usdc_balance = usdc.functions.balanceOf(blockchain.account.address).call()
                usdc_balance_formatted = f"{usdc_balance / 1_000_000:.2f}"
            except Exception:
                usdc_balance_formatted = "0.00"
            blockchain_stats = {
                "wallet_address": blockchain.account.address,
                "block_number": w3.eth.block_number,
                "eth_balance": eth_balance_formatted,
                "usdc_balance": usdc_balance_formatted,
                "chain_id": w3.eth.chain_id
            }
        except Exception as e:
            logger.warning("Blockchain unavailable for dashboard: %s", e)

    recent_policies = sorted(policies, key=lambda x: x.get('created_at', ''), reverse=True)[:5]
    recent_claims = sorted(claims, key=lambda x: x.get('created_at', ''), reverse=True)[:5]

    return jsonify({
        "stats": {"total_coverage": total_coverage, "total_policies": total_policies, "claims_paid": claims_paid},
        "recent_policies": recent_policies,
        "recent_claims": recent_claims,
        "blockchain": blockchain_stats
    })


@discovery_bp.route('/api/pricing')
def pricing_info():
    cfg = ext.config
    return jsonify({
        "premium": {
            "model": "percentage-based",
            "percentage": ext.PREMIUM_PERCENTAGE,
            "percentage_display": f"{ext.PREMIUM_PERCENTAGE * 100}%",
            "calculation": "premium = coverage × percentage",
            "currency": "USDC",
            "network": cfg.CAIP2_NETWORK,
            "examples": {
                "0.01_usdc_coverage": {"coverage": 0.01, "premium": 0.0001, "units": 100},
                "0.05_usdc_coverage": {"coverage": 0.05, "premium": 0.0005, "units": 500},
                "0.1_usdc_coverage": {"coverage": 0.1, "premium": 0.001, "units": 1000}
            }
        },
        "coverage": {
            "min": 0.001, "max": ext.MAX_COVERAGE, "currency": "USDC",
            "recommended": 0.01,
            "display": f"$0.001 - ${ext.MAX_COVERAGE}",
            "note": "Maximum coverage per claim is 0.1 USDC for micropayment protection"
        },
        "policy_duration": {
            "hours": ext.POLICY_DURATION,
            "seconds": ext.POLICY_DURATION * 3600,
            "display": f"{ext.POLICY_DURATION} hours"
        },
        "payment": {
            "protocol": "x402",
            "network": cfg.CAIP2_NETWORK,
            "token": {"symbol": "USDC", "name": "USD Coin", "address": ext.USDC_ADDRESS, "decimals": 6},
            "payTo": ext.BACKEND_ADDRESS
        },
        "economics": {
            "protection_ratio": "Up to 100x",
            "explanation": "Pay 1% premium to protect 100% of coverage",
            "example_scenario": {
                "api_call_cost": "$0.01",
                "insurance_coverage": "$0.01",
                "premium_paid": "$0.0001 (1% of coverage)",
                "if_merchant_fails": {"refund_received": "$0.01", "total_cost": "$0.0001 (just the premium)", "savings": "$0.01 - $0.0001 = $0.0099"},
                "if_merchant_succeeds": {"total_cost": "$0.01 (API) + $0.0001 (premium) = $0.0101", "cost_vs_uninsured": "+$0.0001 (1% overhead)"}
            }
        }
    })


@discovery_bp.route('/api/schema')
def api_schema():
    import yaml
    schema_path = Path(__file__).parent.parent / 'openapi.yaml'
    if not schema_path.exists():
        return jsonify({"error": "Schema not found"}), 404
    accept = request.headers.get('Accept', 'application/json')
    with open(schema_path, 'r') as f:
        schema_content = f.read()
    if 'application/yaml' in accept or 'text/yaml' in accept:
        return schema_content, 200, {'Content-Type': 'application/yaml'}
    else:
        schema = yaml.safe_load(schema_content)
        return jsonify(schema)


@discovery_bp.route('/.well-known/agent-card.json')
def agent_card():
    base_url = request.host_url.rstrip('/')
    cfg = ext.config

    return jsonify({
        "x402Version": 2,
        "agentCardVersion": "1.0",
        "identity": {
            "name": "x402 Insurance",
            "description": "Zero-knowledge proof verified insurance against x402 service failures. Protect your micropayment API calls with instant refunds.",
            "provider": "x402 Insurance", "version": "1.0.0", "url": base_url,
            "contact": {"support": f"{base_url}/api", "documentation": f"{base_url}/api/schema"}
        },
        "capabilities": {
            "x402": True, "zkProofs": True, "instantRefunds": True, "micropayments": True,
            "networks": [cfg.CAIP2_NETWORK], "protocols": ["x402", "a2a"]
        },
        "services": [
            {
                "id": "insurance-policy", "name": "Create Insurance Policy",
                "description": "Purchase micropayment insurance to protect against merchant failures. Coverage for x402 API calls.",
                "endpoint": f"{base_url}/insure", "method": "POST", "x402Required": True,
                "accepts": [{
                    "scheme": "exact", "network": cfg.CAIP2_NETWORK,
                    "maxAmountRequired": str(int(ext.MAX_COVERAGE * ext.PREMIUM_PERCENTAGE * 1_000_000)),
                    "asset": ext.USDC_ADDRESS, "payTo": ext.BACKEND_ADDRESS,
                    "description": f"Insurance premium (1% of coverage, max {ext.MAX_COVERAGE * ext.PREMIUM_PERCENTAGE} USDC for max coverage)",
                    "maxTimeoutSeconds": 60, "extra": {},
                    "note": "Actual amount varies based on requested coverage_amount (premium = coverage × 1%)"
                }],
                "inputSchema": {
                    "type": "object", "required": ["merchant_url", "coverage_amount"],
                    "properties": {
                        "merchant_url": {"type": "string", "format": "uri", "description": "Merchant API endpoint to protect"},
                        "coverage_amount": {"type": "number", "minimum": 0.001, "maximum": ext.MAX_COVERAGE, "description": f"Coverage amount in USDC (max {ext.MAX_COVERAGE}). Premium will be calculated as 1% of this amount."}
                    }
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "policy_id": {"type": "string", "format": "uuid"}, "agent_address": {"type": "string"},
                        "coverage_amount": {"type": "number"}, "premium": {"type": "number"},
                        "status": {"type": "string"}, "expires_at": {"type": "string", "format": "date-time"}
                    }
                },
                "pricing": {
                    "model": "percentage-based", "percentage": ext.PREMIUM_PERCENTAGE,
                    "percentage_display": f"{ext.PREMIUM_PERCENTAGE * 100}%",
                    "calculation": "Premium = Coverage Amount × 1%", "currency": "USDC",
                    "examples": {
                        "min": {"coverage": 0.001, "premium": 0.00001},
                        "typical": {"coverage": 0.01, "premium": 0.0001},
                        "max": {"coverage": ext.MAX_COVERAGE, "premium": ext.MAX_COVERAGE * ext.PREMIUM_PERCENTAGE}
                    }
                }
            },
            {
                "id": "submit-claim", "name": "Submit Fraud Claim",
                "description": "Submit a claim when a merchant fails to deliver. Includes zkp proof generation and instant USDC refund.",
                "endpoint": f"{base_url}/claim", "method": "POST", "x402Required": False,
                "inputSchema": {
                    "type": "object", "required": ["policy_id", "http_response"],
                    "properties": {
                        "policy_id": {"type": "string", "format": "uuid", "description": "Policy ID from insurance purchase"},
                        "http_response": {
                            "type": "object", "required": ["status", "body"],
                            "properties": {
                                "status": {"type": "integer", "description": "HTTP status code"},
                                "body": {"type": "string", "description": "Response body"},
                                "headers": {"type": "object", "description": "Response headers"}
                            }
                        }
                    }
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "claim_id": {"type": "string", "format": "uuid"}, "proof": {"type": "string"},
                        "payout_amount": {"type": "number"}, "refund_tx_hash": {"type": "string"},
                        "status": {"type": "string"}
                    }
                },
                "features": ["zkp-verification", "instant-refund", "public-proof"]
            },
            {
                "id": "verify-proof", "name": "Verify Zero-Knowledge Proof",
                "description": "Public endpoint to verify zkp proofs. Anyone can verify failure claims.",
                "endpoint": f"{base_url}/verify", "method": "POST", "x402Required": False, "public": True,
                "inputSchema": {
                    "type": "object", "required": ["proof", "public_inputs"],
                    "properties": {
                        "proof": {"type": "string", "description": "zkp proof hex"},
                        "public_inputs": {"type": "array", "items": {"type": "integer"}}
                    }
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {"valid": {"type": "boolean"}, "failure_detected": {"type": "boolean"}, "payout_amount": {"type": "number"}}
                }
            }
        ],
        "metadata": {
            "category": "insurance",
            "tags": ["insurance", "x402", "zkp", "micropayments", "failure-protection"],
            "pricing": {"model": "percentage-based", "percentage": ext.PREMIUM_PERCENTAGE, "currency": "USDC"},
            "performance": {"zkp_generation_time_ms": "10000-20000", "refund_time_ms": "2000-5000", "total_claim_time_ms": "15000-30000"},
            "rate_limits": {
                "/insure": {"limit": "10 per hour", "limit_per_minute": None, "recommendation": "Implement exponential backoff if you receive 429 responses"},
                "/claim": {"limit": "5 per hour", "limit_per_minute": None, "recommendation": "Implement exponential backoff if you receive 429 responses"},
                "/renew": {"limit": "20 per hour", "limit_per_minute": None, "recommendation": "Renew policies before expiration to avoid coverage gaps"},
                "general": {"limit": "200 per day, 50 per hour", "recommendation": "Cache discovery endpoints (agent-card, pricing, schema) to reduce request volume"}
            },
            "agent_guidance": {
                "timeout_recommendations": {"/insure": "5-10 seconds", "/claim": "30-45 seconds", "/verify": "5-10 seconds", "/renew": "5-10 seconds"},
                "memory_solution": {"endpoint": "/policies?wallet=0xYourAddress", "description": "Retrieve active policies by wallet address.", "use_case": "If you forget your policy_id after context reset, query by wallet address"},
                "policy_expiration": {"duration": "24 hours (initial)", "max_extension": "168 hours (7 days)", "grace_period": None, "renewal_available": True, "renewal_endpoint": "/renew", "recommendation": "Use /renew endpoint to extend policies before expiration."},
                "error_handling": {"429_rate_limit": "Implement exponential backoff (1s, 2s, 4s, 8s...)", "402_payment_required": "First request returns 402 with payment details. Sign payment and retry.", "503_service_unavailable": "Retry with exponential backoff, check /health endpoint"}
            }
        },
        "links": {
            "self": f"{base_url}/.well-known/agent-card.json", "api": f"{base_url}/api",
            "schema": f"{base_url}/api/schema", "pricing": f"{base_url}/api/pricing",
            "dashboard": f"{base_url}/", "health": f"{base_url}/health"
        }
    })
