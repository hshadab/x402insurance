"""
Flask application factory for x402 Insurance Service.
"""
import json
import os
import logging
from flask import Flask, request, g, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from dotenv import load_dotenv

import extensions as ext
from config import get_config

load_dotenv()


class DummyLimiter:
    """No-op rate limiter for when rate limiting is disabled."""
    def limit(self, *args, **kwargs):
        def decorator(f):
            return f
        return decorator


def create_app(env=None):
    """Create and configure the Flask application."""
    cfg = get_config(env)

    app = Flask(__name__, static_folder='static')
    app.config.from_object(cfg)
    app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2 MB

    # Store config reference
    ext.config = cfg

    # Logging
    logging.basicConfig(
        level=cfg.LOG_LEVEL,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger("x402insurance")

    # Sentry
    if cfg.SENTRY_DSN:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.flask import FlaskIntegration
            from sentry_sdk.integrations.logging import LoggingIntegration

            sentry_sdk.init(
                dsn=cfg.SENTRY_DSN,
                environment=cfg.SENTRY_ENVIRONMENT,
                traces_sample_rate=cfg.SENTRY_TRACES_SAMPLE_RATE,
                integrations=[
                    FlaskIntegration(),
                    LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
                ],
                release=os.getenv("SENTRY_RELEASE", "x402-insurance@dev"),
                profiles_sample_rate=0.1,
                before_send_transaction=lambda event, hint: None if event.get("request", {}).get("url", "").endswith("/health") else event,
            )
            logger.info("Sentry error tracking enabled (environment: %s)", cfg.SENTRY_ENVIRONMENT)
        except ImportError:
            logger.warning("Sentry SDK not installed.")
        except Exception as e:
            logger.error("Failed to initialize Sentry: %s", e)
    else:
        logger.info("Sentry error tracking disabled (no SENTRY_DSN configured)")

    # CORS
    if cfg.CORS_ORIGINS:
        origins = [o.strip() for o in cfg.CORS_ORIGINS.split(',') if o.strip()]
        CORS(app, resources={r"/api/*": {"origins": origins}})

    # Rate Limiting
    if cfg.RATE_LIMIT_ENABLED:
        ext.limiter = Limiter(
            app=app,
            key_func=get_remote_address,
            default_limits=[cfg.RATE_LIMIT_DEFAULT],
            storage_uri=cfg.RATE_LIMIT_STORAGE_URL or "memory://"
        )
        logger.info("Rate limiting enabled with default: %s", cfg.RATE_LIMIT_DEFAULT)
    else:
        ext.limiter = DummyLimiter()
        logger.warning("Rate limiting DISABLED")

    # Startup validation: chain ID vs RPC URL sanity check
    if cfg.CHAIN_ID == 8453 and "sepolia" in cfg.BASE_RPC_URL:
        raise ValueError(
            "CHAIN_ID is 8453 (Base Mainnet) but BASE_RPC_URL contains 'sepolia'. "
            "Set BASE_RPC_URL to a mainnet RPC or change CHAIN_ID to 84532."
        )

    # Startup validation: required config
    if not cfg.BACKEND_WALLET_PRIVATE_KEY:
        raise RuntimeError("BACKEND_WALLET_PRIVATE_KEY is required")
    if not cfg.BACKEND_WALLET_ADDRESS:
        raise RuntimeError("BACKEND_WALLET_ADDRESS is required")

    # Config constants
    ext.BACKEND_ADDRESS = cfg.BACKEND_WALLET_ADDRESS

    ext.PREMIUM_PERCENTAGE = cfg.PREMIUM_PERCENTAGE
    ext.MAX_COVERAGE = cfg.MAX_COVERAGE_USDC
    ext.POLICY_DURATION = cfg.POLICY_DURATION_HOURS
    ext.USDC_ADDRESS = cfg.USDC_CONTRACT_ADDRESS

    ext.DATA_DIR = cfg.DATA_DIR
    ext.DATA_DIR.mkdir(exist_ok=True)
    ext.POLICIES_FILE = ext.DATA_DIR / "policies.json"
    ext.CLAIMS_FILE = ext.DATA_DIR / "claims.json"

    # Initialize services
    from proof_client import JoltProofClient
    from blockchain import BlockchainClient
    from database import DatabaseClient
    from auth.payment_verifier import PaymentVerifier, FacilitatorPaymentVerifier
    from tasks.reserve_monitor import ReserveMonitor

    ext.proof_client = JoltProofClient(
        binary_path=cfg.JOLT_BINARY_PATH,
        timeout=cfg.JOLT_TIMEOUT,
        model_path=cfg.ONNX_MODEL_PATH,
    )

    ext.blockchain = BlockchainClient(
        rpc_url=cfg.BASE_RPC_URL,
        usdc_address=cfg.USDC_CONTRACT_ADDRESS,
        private_key=cfg.BACKEND_WALLET_PRIVATE_KEY,
        max_gas_price_gwei=cfg.MAX_GAS_PRICE_GWEI,
        max_retries=cfg.MAX_RETRIES,
        confirmation_timeout=cfg.BLOCKCHAIN_CONFIRMATION_TIMEOUT
    )

    ext.database = DatabaseClient(
        database_url=cfg.DATABASE_URL,
        data_dir=cfg.DATA_DIR
    )

    ext.eip712_verifier = PaymentVerifier(
        backend_address=ext.BACKEND_ADDRESS,
        usdc_address=cfg.USDC_CONTRACT_ADDRESS,
        chain_id=cfg.CHAIN_ID
    )

    if cfg.FACILITATOR_URL and cfg.FACILITATOR_URL != "none":
        ext.payment_verifier = FacilitatorPaymentVerifier(
            backend_address=ext.BACKEND_ADDRESS,
            usdc_address=cfg.USDC_CONTRACT_ADDRESS,
            facilitator_url=cfg.FACILITATOR_URL,
            chain_id=cfg.CHAIN_ID,
        )
        logger.info("Using FACILITATOR payment verification (V2, chain_id=%d)", cfg.CHAIN_ID)
    else:
        ext.payment_verifier = ext.eip712_verifier
        logger.info("Using LOCAL EIP-712 payment verification (chain_id=%d)", cfg.CHAIN_ID)

    ext.reserve_monitor = ReserveMonitor(
        blockchain_client=ext.blockchain,
        database_client=ext.database,
        min_reserve_ratio=cfg.MIN_RESERVE_RATIO
    )

    # Register blueprints
    from blueprints.discovery import discovery_bp
    from blueprints.health import health_bp
    from blueprints.policies import policies_bp
    from blueprints.claims import claims_bp
    from blueprints.verify import verify_bp

    app.register_blueprint(discovery_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(policies_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(verify_bp)

    # Before request: capture payment headers
    @app.before_request
    def handle_x402_payment():
        if request.method == 'POST' and request.path in ['/insure', '/claim', '/renew']:
            g.payment_header = (
                request.headers.get('PAYMENT-SIGNATURE')
                or request.headers.get('X-Payment')
                or request.headers.get('X-PAYMENT')
            )
            g.payer_header = request.headers.get('X-Payer') or request.headers.get('X-FROM-ADDRESS')

    # After request: metrics
    @app.after_request
    def after_request(resp):
        try:
            if request.endpoint == 'policies.insure' and resp.status_code == 201:
                ext.policies_created_total.inc()
            if request.endpoint == 'claims.claim' and resp.status_code == 201:
                ext.claims_paid_total.labels(status="paid").inc()
        except Exception:
            pass
        return resp

    # Error handlers
    @app.errorhandler(429)
    def ratelimit_handler(e):
        return jsonify({
            "error": "Rate limit exceeded",
            "message": str(e.description),
            "retry_strategy": {
                "recommendation": "Implement exponential backoff",
                "example_delays": [1, 2, 4, 8, 16],
                "example_delays_unit": "seconds"
            },
            "rate_limits": {
                "/insure": "10 per hour",
                "/claim": "5 per hour",
                "general": "200 per day, 50 per hour"
            },
            "documentation": "See /.well-known/agent-card.json for complete rate limit information"
        }), 429

    logger.info("x402 Insurance Service initialized")
    logger.info("Premium: %.4f%% of coverage amount", ext.PREMIUM_PERCENTAGE * 100)
    logger.info("Max coverage: %s USDC", ext.MAX_COVERAGE)
    logger.info("Payment recipient: %s", ext.BACKEND_ADDRESS or "NOT SET")
    logger.info("Database: %s", "PostgreSQL" if cfg.DATABASE_URL else "JSON files")

    # Startup wallet balance check
    if ext.blockchain:
        try:
            w3 = ext.blockchain.w3
            eth_balance = w3.eth.get_balance(ext.blockchain.account.address)
            eth_formatted = float(w3.from_wei(eth_balance, 'ether'))
            logger.info("Wallet ETH balance: %.6f", eth_formatted)
            if eth_formatted < 0.001:
                logger.warning("LOW ETH BALANCE (%.6f) — transactions may fail due to insufficient gas", eth_formatted)

            try:
                usdc_balance = ext.blockchain.usdc.functions.balanceOf(ext.blockchain.account.address).call()
                usdc_formatted = usdc_balance / 1_000_000
                logger.info("Wallet USDC balance: %.2f", usdc_formatted)
                if usdc_formatted < 1.0:
                    logger.warning("LOW USDC BALANCE (%.2f) — refund payouts may fail", usdc_formatted)
            except Exception as e:
                logger.warning("Could not check USDC balance: %s", e)
        except Exception as e:
            logger.warning("Could not check wallet balances at startup: %s", e)

    return app


def create_dashboard_app(env=None):
    """
    Create a lightweight read-only dashboard app.

    Only registers discovery and health blueprints — no blockchain,
    wallet, prover, or payment verification dependencies required.
    Used by App Runner as a public informational dashboard.
    """
    cfg = get_config(env)

    app = Flask(__name__, static_folder='static')
    app.config.from_object(cfg)
    app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024

    logging.basicConfig(
        level=cfg.LOG_LEVEL,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger("x402insurance.dashboard")

    # CORS
    if cfg.CORS_ORIGINS:
        origins = [o.strip() for o in cfg.CORS_ORIGINS.split(',') if o.strip()]
        CORS(app, resources={r"/*": {"origins": origins}})

    # Populate ext with config and constants so discovery_bp works
    import extensions as ext
    ext.config = cfg
    ext.BACKEND_ADDRESS = cfg.BACKEND_WALLET_ADDRESS
    ext.PREMIUM_PERCENTAGE = cfg.PREMIUM_PERCENTAGE
    ext.MAX_COVERAGE = cfg.MAX_COVERAGE_USDC
    ext.POLICY_DURATION = cfg.POLICY_DURATION_HOURS
    ext.USDC_ADDRESS = cfg.USDC_CONTRACT_ADDRESS

    # Only register lightweight blueprints
    from blueprints.discovery import discovery_bp
    from blueprints.dashboard_health import dashboard_health_bp

    app.register_blueprint(discovery_bp)
    app.register_blueprint(dashboard_health_bp)

    logger.info("x402 Insurance Dashboard initialized (read-only mode)")
    logger.info("AgentCore service URL: %s", cfg.AGENTCORE_SERVICE_URL)

    return app
