"""
x402 Insurance Service - Production-Ready Flask Server

Endpoints:
  GET  / - Dashboard UI (home page)
  GET  /docs - API documentation (for site viewers)
  GET  /api - API info JSON (for agents)
  GET  /api/dashboard - Dashboard data (live stats)
  POST /insure - Create insurance policy (requires x402 payment)
  POST /claim - Submit failure claim
  POST /verify - Verify proof (public)
  GET  /proofs/<claim_id> - Get proof data (public)
  GET  /health - Health check with dependency status
  GET  /api/reserves - Reserve health status

Enhanced with:
- Proper x402 payment verification
- Rate limiting
- Database abstraction (JSON or PostgreSQL)
- Reserve monitoring
- Better error handling
"""
from flask import Flask, request, jsonify, g, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
import json
import os
import uuid
import hashlib
import logging
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv
from typing import Tuple, List, Optional

from zkengine_client import ZKEngineClient
from blockchain import BlockchainClient
from database import DatabaseClient
from auth.payment_verifier import PaymentVerifier, SimplePaymentVerifier
from tasks.reserve_monitor import ReserveMonitor
from config import get_config

# Load environment
load_dotenv()

# Load configuration
config = get_config()

#############################################
# App setup
#############################################

# Initialize Flask
app = Flask(__name__, static_folder='static')
app.config.from_object(config)

# Logging
logging.basicConfig(
    level=config.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("x402insurance")

# CORS
if config.CORS_ORIGINS:
    origins = [o.strip() for o in config.CORS_ORIGINS.split(',') if o.strip()]
    CORS(app, resources={r"/api/*": {"origins": origins}})
    logger.info("CORS enabled for origins: %s", origins)

# Rate Limiting
if config.RATE_LIMIT_ENABLED:
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=["200 per day", "50 per hour"],
        storage_uri=config.RATE_LIMIT_STORAGE_URL or "memory://"
    )
    logger.info("Rate limiting enabled")
else:
    # Create dummy limiter that does nothing
    class DummyLimiter:
        def limit(self, *args, **kwargs):
            def decorator(f):
                return f
            return decorator
    limiter = DummyLimiter()
    logger.warning("Rate limiting DISABLED")

# Get backend wallet address for x402 payments
BACKEND_ADDRESS = config.BACKEND_WALLET_ADDRESS
if not BACKEND_ADDRESS:
    logger.warning("BACKEND_WALLET_ADDRESS not set - payment verification will fail")

# Initialize services
logger.info("Initializing services...")

# zkEngine
zkengine = ZKEngineClient(config.ZKENGINE_BINARY_PATH)

# Blockchain
blockchain = BlockchainClient(
    rpc_url=config.BASE_RPC_URL,
    usdc_address=config.USDC_CONTRACT_ADDRESS,
    private_key=config.BACKEND_WALLET_PRIVATE_KEY,
    max_gas_price_gwei=config.MAX_GAS_PRICE_GWEI,
    max_retries=config.MAX_RETRIES
)

# Database
database = DatabaseClient(
    database_url=config.DATABASE_URL,
    data_dir=config.DATA_DIR
)

# Payment Verifier
if config.PAYMENT_VERIFICATION_MODE == "full" and BACKEND_ADDRESS:
    payment_verifier = PaymentVerifier(
        backend_address=BACKEND_ADDRESS,
        usdc_address=config.USDC_CONTRACT_ADDRESS
    )
    logger.info("Using FULL payment verification (EIP-712 signatures)")
else:
    payment_verifier = SimplePaymentVerifier(
        backend_address=BACKEND_ADDRESS or "0x0000000000000000000000000000000000000000",
        usdc_address=config.USDC_CONTRACT_ADDRESS
    )
    logger.info("Using SIMPLE payment verification (testing mode)")

# Reserve Monitor
reserve_monitor = ReserveMonitor(
    blockchain_client=blockchain,
    database_client=database,
    min_reserve_ratio=config.MIN_RESERVE_RATIO
)

# Custom rate limit error handler for better agent experience
@app.errorhandler(429)
def ratelimit_handler(e):
    """
    Custom handler for rate limit errors (429 Too Many Requests).
    Provides clear guidance for agents on retry strategy.
    """
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

# Configuration summary
PREMIUM_PERCENTAGE = config.PREMIUM_PERCENTAGE
MAX_COVERAGE = config.MAX_COVERAGE_USDC
POLICY_DURATION = config.POLICY_DURATION_HOURS
USDC_ADDRESS = config.USDC_CONTRACT_ADDRESS

logger.info("x402 Insurance Service initialized")
logger.info("Premium: %.4f%% of coverage amount", PREMIUM_PERCENTAGE * 100)
logger.info("Max coverage: %s USDC", MAX_COVERAGE)
logger.info("Payment recipient: %s", BACKEND_ADDRESS or "NOT SET")
logger.info("Database: %s", "PostgreSQL" if config.DATABASE_URL else "JSON files")

# Backward compatibility: keep old load_data/save_data for dashboard
DATA_DIR = config.DATA_DIR
DATA_DIR.mkdir(exist_ok=True)
POLICIES_FILE = DATA_DIR / "policies.json"
CLAIMS_FILE = DATA_DIR / "claims.json"


def load_data(file_path: Path):
    """Backward compatibility - load JSON file"""
    if not file_path.exists():
        return {}
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def save_data(file_path: Path, data: dict):
    """Backward compatibility - save JSON file atomically"""
    try:
        # Use the database client's atomic write method
        database.backend._save_json(file_path, data)
    except Exception as e:
        logger.exception("Failed to save data to %s: %s", file_path, e)
        raise


# Monetary helpers (USDC 6 decimals)
MICRO = Decimal(10) ** 6


def to_micro(amount_usdc: Decimal | float) -> int:
    d = Decimal(str(amount_usdc))
    return int((d * MICRO).to_integral_exact(rounding=ROUND_DOWN))


def from_micro(amount_units: int) -> float:
    return float(Decimal(amount_units) / MICRO)


def iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_utc(dt_str: str) -> datetime:
    # Accept both Z and +00:00 or naive (assume UTC)
    s = dt_str.replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        dt = datetime.utcnow().replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def process_claim_async(claim_id: str):
    """
    Background worker function to process claim asynchronously.
    Generates zkEngine proof and issues blockchain refund.
    Updates claim record with final status (paid/failed).
    """
    try:
        logger.info("Starting async claim processing: %s", claim_id)

        # Load claim record
        claims = load_data(CLAIMS_FILE)
        claim = claims.get(claim_id)

        if not claim:
            logger.error("Claim not found for async processing: %s", claim_id)
            return

        # Load policy
        policies = load_data(POLICIES_FILE)
        policy = policies.get(claim['policy_id'])

        if not policy:
            logger.error("Policy not found for claim: %s", claim_id)
            claim['status'] = 'failed'
            claim['error'] = 'Policy not found'
            claims[claim_id] = claim
            save_data(CLAIMS_FILE, claims)
            return

        # Get HTTP response from claim
        http_response = claim.get('http_response', {})

        # Generate zkEngine proof (this is the slow part: 10-20 seconds)
        logger.info("Generating proof for claim: %s", claim_id)
        proof_hex, public_inputs, gen_time_ms = zkengine.generate_proof(
            http_status=http_response["status"],
            http_body=http_response["body"],
            http_headers=http_response.get("headers", {})
        )

        # Verify proof (sanity check)
        is_valid = zkengine.verify_proof(proof_hex, public_inputs)
        if not is_valid:
            logger.error("Proof verification failed for claim: %s", claim_id)
            claim['status'] = 'failed'
            claim['error'] = 'Generated proof is invalid'
            claims[claim_id] = claim
            save_data(CLAIMS_FILE, claims)
            return

        # Parse public inputs
        is_failure = public_inputs[0]
        if is_failure != 1:
            logger.warning("No failure detected for claim: %s", claim_id)
            claim['status'] = 'failed'
            claim['error'] = 'No failure detected in HTTP response'
            claims[claim_id] = claim
            save_data(CLAIMS_FILE, claims)
            return

        # Issue USDC refund (2-5 seconds)
        logger.info("Issuing refund for claim: %s", claim_id)
        refund_tx_hash = blockchain.issue_refund(
            to_address=claim['agent_address'],
            amount=claim['coverage_amount_units']
        )

        # Update claim record with final status
        claim['proof'] = proof_hex
        claim['public_inputs'] = public_inputs
        claim['proof_generation_time_ms'] = gen_time_ms
        claim['verification_result'] = True
        claim['payout_amount'] = claim['coverage_amount']
        claim['payout_amount_units'] = claim['coverage_amount_units']
        claim['refund_tx_hash'] = refund_tx_hash
        claim['recipient_address'] = claim['agent_address']
        claim['status'] = 'paid'
        claim['paid_at'] = iso_utc_now()

        # Remove http_response from final claim (too large, already have hash)
        claim.pop('http_response', None)

        # Save claim
        claims[claim_id] = claim
        save_data(CLAIMS_FILE, claims)

        # Update policy status
        policy['status'] = 'claimed'
        policies[claim['policy_id']] = policy
        save_data(POLICIES_FILE, policies)

        logger.info("Claim processed successfully: %s, refund TX: %s", claim_id, refund_tx_hash)

    except Exception as e:
        logger.error("Error processing claim async: %s, error: %s", claim_id, str(e), exc_info=True)
        # Mark claim as failed
        try:
            claims = load_data(CLAIMS_FILE)
            if claim_id in claims:
                claims[claim_id]['status'] = 'failed'
                claims[claim_id]['error'] = str(e)
                claims[claim_id]['failed_at'] = iso_utc_now()
                save_data(CLAIMS_FILE, claims)
        except Exception as save_error:
            logger.error("Failed to save error status: %s", str(save_error))


@app.before_request
def handle_x402_payment():
    """Capture X-Payment header for verification in /insure endpoint."""
    if request.path == '/insure' and request.method == 'POST':
        g.payment_header = request.headers.get('X-Payment') or request.headers.get('X-PAYMENT')
        g.payer_header = request.headers.get('X-Payer') or request.headers.get('X-FROM-ADDRESS')


@app.route('/')
def index():
    """Serve dashboard UI"""
    return send_from_directory('static', 'dashboard.html')


@app.route('/docs')
def docs():
    """Serve API documentation page"""
    return send_from_directory('static', 'api-docs.html')


@app.route('/api')
def api_info():
    """API information with x402 discovery metadata"""
    base_url = request.host_url.rstrip('/')

    return jsonify({
        "service": "x402 Insurance API",
        "version": "1.0.0",
        "x402Version": 1,
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
            "paymentRequired": {
                "/insure": {
                    "scheme": "exact",
                    "network": "base",
                    "maxAmountRequired": str(int(MAX_COVERAGE * PREMIUM_PERCENTAGE * 1_000_000)),
                    "asset": USDC_ADDRESS,
                    "payTo": BACKEND_ADDRESS,
                    "description": "Insurance premium (1% of requested coverage)",
                    "mimeType": "application/json",
                    "maxTimeoutSeconds": 60
                }
            }
        },
        "status": "operational",
        "links": {
            "documentation": f"{base_url}/api/schema",
            "pricing": f"{base_url}/api/pricing",
            "agentCard": f"{base_url}/.well-known/agent-card.json"
        }
    })


@app.route('/api/dashboard')
def dashboard_data():
    """Dashboard live data"""
    # Load policies and claims
    policies_file = DATA_DIR / "policies.json"
    claims_file = DATA_DIR / "claims.json"

    policies = []
    claims = []

    if policies_file.exists():
        with open(policies_file, 'r') as f:
            policies_data = json.load(f)
            # Convert dict to list if needed
            if isinstance(policies_data, dict):
                policies = list(policies_data.values())
            else:
                policies = policies_data

    if claims_file.exists():
        with open(claims_file, 'r') as f:
            claims_data = json.load(f)
            # Convert dict to list if needed
            if isinstance(claims_data, dict):
                claims = list(claims_data.values())
            else:
                claims = claims_data

    # Add sample data if no real data exists
    sample_policies = [
        {
            "policy_id": "sample-001",
            "agent_address": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
            "merchant_url": "https://api.weather.com/forecast",
            "coverage_amount": 5000,
            "premium": 50,
            "status": "active",
            "created_at": "2025-11-07T10:15:30Z",
            "expires_at": "2025-11-08T10:15:30Z",
            "is_sample": True
        },
        {
            "policy_id": "sample-002",
            "agent_address": "0x1234567890123456789012345678901234567890",
            "merchant_url": "https://api.coinbase.com/v2/prices",
            "coverage_amount": 10000,
            "premium": 100,
            "status": "active",
            "created_at": "2025-11-07T14:22:15Z",
            "expires_at": "2025-11-08T14:22:15Z",
            "is_sample": True
        },
        {
            "policy_id": "sample-003",
            "agent_address": "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
            "merchant_url": "https://api.openai.com/v1/completions",
            "coverage_amount": 2500,
            "premium": 25,
            "status": "claimed",
            "created_at": "2025-11-07T08:45:00Z",
            "expires_at": "2025-11-08T08:45:00Z",
            "is_sample": True
        }
    ]

    sample_claims = [
        {
            "claim_id": "sample-claim-001",
            "policy_id": "sample-003",
            "agent_address": "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
            "merchant_url": "https://api.openai.com/v1/completions",
            "http_status": 503,
            "payout_amount": 2500,
            "status": "paid",
            "refund_tx_hash": "0xabc123def456789abc123def456789abc123def456789abc123def456789abc12",
            "proof": "0x1a2b3c4d...",
            "public_inputs": [1, 503, 0, 2500],  # [is_failure, http_status, body_length, payout]
            "paid_at": "2025-11-07T09:30:58Z",
            "created_at": "2025-11-07T09:30:45Z",
            "is_sample": True
        },
        {
            "claim_id": "sample-claim-002",
            "policy_id": "sample-004",
            "agent_address": "0x9876543210987654321098765432109876543210",
            "merchant_url": "https://api.stripe.com/v1/charges",
            "http_status": 500,
            "payout_amount": 7500,
            "status": "paid",
            "refund_tx_hash": "0xdef789abc123def789abc123def789abc123def789abc123def789abc123def78",
            "proof": "0x5e6f7g8h...",
            "public_inputs": [1, 500, 0, 7500],  # [is_failure, http_status, body_length, payout]
            "paid_at": "2025-11-06T18:12:35Z",
            "created_at": "2025-11-06T18:12:20Z",
            "is_sample": True
        },
        {
            "claim_id": "sample-claim-003",
            "policy_id": "sample-005",
            "agent_address": "0x5555666677778888999900001111222233334444",
            "merchant_url": "https://api.github.com/repos",
            "http_status": 502,
            "payout_amount": 1000,
            "status": "paid",
            "refund_tx_hash": "0x9i0j1k2l3m4n5o6p7q8r9s0t1u2v3w4x5y6z7a8b9c0d1e2f3g4h5i6j7k8l9m",
            "proof": "0x9i0j1k2l...",
            "public_inputs": [1, 502, 0, 1000],  # [is_failure, http_status, body_length, payout]
            "paid_at": "2025-11-06T12:05:22Z",
            "created_at": "2025-11-06T12:05:10Z",
            "is_sample": True
        }
    ]

    # Prepend sample data (so real data appears first if it exists)
    policies = sample_policies + policies
    claims = sample_claims + claims

    # Calculate stats
    total_coverage = sum(p.get('coverage_amount', 0) for p in policies if isinstance(p, dict) and p.get('status') == 'active')
    total_policies = len(policies)
    claims_paid = sum(c.get('payout_amount', 0) for c in claims if isinstance(c, dict) and c.get('status') == 'paid')

    # Get blockchain stats
    blockchain_stats = None
    if blockchain and blockchain.has_wallet:
        try:
            from web3 import Web3
            w3 = blockchain.w3

            eth_balance = w3.eth.get_balance(blockchain.account.address)
            eth_balance_formatted = f"{w3.from_wei(eth_balance, 'ether'):.4f}"

            # Get USDC balance
            usdc_balance = 0
            try:
                usdc = blockchain.usdc
                usdc_balance = usdc.functions.balanceOf(blockchain.account.address).call()
                usdc_balance_formatted = f"{usdc_balance / 1_000_000:.2f}"
            except:
                usdc_balance_formatted = "0.00"

            blockchain_stats = {
                "wallet_address": blockchain.account.address,
                "block_number": w3.eth.block_number,
                "eth_balance": eth_balance_formatted,
                "usdc_balance": usdc_balance_formatted,
                "chain_id": w3.eth.chain_id
            }
        except Exception as e:
            logger.exception("Error getting blockchain stats: %s", e)

    # Get recent items
    recent_policies = sorted(policies, key=lambda x: x.get('created_at', ''), reverse=True)[:5]
    recent_claims = sorted(claims, key=lambda x: x.get('created_at', ''), reverse=True)[:5]

    return jsonify({
        "stats": {
            "total_coverage": total_coverage,
            "total_policies": total_policies,
            "claims_paid": claims_paid
        },
        "recent_policies": recent_policies,
        "recent_claims": recent_claims,
        "blockchain": blockchain_stats
    })


@app.route('/api/pricing')
def pricing_info():
    """Pricing information for agent discovery"""
    return jsonify({
        "premium": {
            "model": "percentage-based",
            "percentage": PREMIUM_PERCENTAGE,
            "percentage_display": f"{PREMIUM_PERCENTAGE * 100}%",
            "calculation": "premium = coverage × percentage",
            "currency": "USDC",
            "network": "base",
            "examples": {
                "0.01_usdc_coverage": {"coverage": 0.01, "premium": 0.0001, "units": 100},
                "0.05_usdc_coverage": {"coverage": 0.05, "premium": 0.0005, "units": 500},
                "0.1_usdc_coverage": {"coverage": 0.1, "premium": 0.001, "units": 1000}
            }
        },
        "coverage": {
            "min": 0.001,
            "max": MAX_COVERAGE,
            "currency": "USDC",
            "recommended": 0.01,
            "display": f"$0.001 - ${MAX_COVERAGE}",
            "note": "Maximum coverage per claim is 0.1 USDC for micropayment protection"
        },
        "policy_duration": {
            "hours": POLICY_DURATION,
            "seconds": POLICY_DURATION * 3600,
            "display": f"{POLICY_DURATION} hours"
        },
        "payment": {
            "protocol": "x402",
            "network": "base",
            "token": {
                "symbol": "USDC",
                "name": "USD Coin",
                "address": USDC_ADDRESS,
                "decimals": 6
            },
            "payTo": BACKEND_ADDRESS
        },
        "economics": {
            "protection_ratio": "Up to 100x",
            "explanation": "Pay 1% premium to protect 100% of coverage",
            "example_scenario": {
                "api_call_cost": "$0.01",
                "insurance_coverage": "$0.01",
                "premium_paid": "$0.0001 (1% of coverage)",
                "if_merchant_fails": {
                    "refund_received": "$0.01",
                    "total_cost": "$0.0001 (just the premium)",
                    "savings": "$0.01 - $0.0001 = $0.0099"
                },
                "if_merchant_succeeds": {
                    "total_cost": "$0.01 (API) + $0.0001 (premium) = $0.0101",
                    "cost_vs_uninsured": "+$0.0001 (1% overhead)"
                }
            }
        }
    })


@app.route('/api/schema')
def api_schema():
    """Serve OpenAPI schema for agent discovery"""
    import yaml
    schema_path = Path(__file__).parent / 'openapi.yaml'

    if not schema_path.exists():
        return jsonify({"error": "Schema not found"}), 404

    # Check Accept header for format preference
    accept = request.headers.get('Accept', 'application/json')

    with open(schema_path, 'r') as f:
        schema_content = f.read()

    if 'application/yaml' in accept or 'text/yaml' in accept:
        return schema_content, 200, {'Content-Type': 'application/yaml'}
    else:
        # Return as JSON
        schema = yaml.safe_load(schema_content)
        return jsonify(schema)


@app.route('/.well-known/agent-card.json')
def agent_card():
    """A2A Agent Card for autonomous agent discovery"""
    base_url = request.host_url.rstrip('/')

    return jsonify({
        "x402Version": 1,
        "agentCardVersion": "1.0",
        "identity": {
            "name": "x402 Insurance",
            "description": "Zero-knowledge proof verified insurance against x402 service failures. Protect your micropayment API calls with instant refunds.",
            "provider": "x402 Insurance",
            "version": "1.0.0",
            "url": base_url,
            "contact": {
                "support": f"{base_url}/api",
                "documentation": f"{base_url}/api/schema"
            }
        },
        "capabilities": {
            "x402": True,
            "zkProofs": True,
            "instantRefunds": True,
            "micropayments": True,
            "networks": ["base"],
            "protocols": ["x402", "a2a"]
        },
        "services": [
            {
                "id": "insurance-policy",
                "name": "Create Insurance Policy",
                "description": "Purchase micropayment insurance to protect against merchant failures. Coverage for x402 API calls.",
                "endpoint": f"{base_url}/insure",
                "method": "POST",
                "x402Required": True,
                "payment": {
                    "scheme": "exact",
                    "network": "base",
                    "maxAmountRequired": str(int(MAX_COVERAGE * PREMIUM_PERCENTAGE * 1_000_000)),
                    "asset": USDC_ADDRESS,
                    "payTo": BACKEND_ADDRESS,
                    "description": f"Insurance premium (1% of coverage, max {MAX_COVERAGE * PREMIUM_PERCENTAGE} USDC for max coverage)",
                    "maxTimeoutSeconds": 60,
                    "note": "Actual amount varies based on requested coverage_amount (premium = coverage × 1%)"
                },
                "inputSchema": {
                    "type": "object",
                    "required": ["merchant_url", "coverage_amount"],
                    "properties": {
                        "merchant_url": {
                            "type": "string",
                            "format": "uri",
                            "description": "Merchant API endpoint to protect"
                        },
                        "coverage_amount": {
                            "type": "number",
                            "minimum": 0.001,
                            "maximum": MAX_COVERAGE,
                            "description": f"Coverage amount in USDC (max {MAX_COVERAGE}). Premium will be calculated as 1% of this amount."
                        }
                    }
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "policy_id": {"type": "string", "format": "uuid"},
                        "agent_address": {"type": "string"},
                        "coverage_amount": {"type": "number"},
                        "premium": {"type": "number"},
                        "status": {"type": "string"},
                        "expires_at": {"type": "string", "format": "date-time"}
                    }
                },
                "pricing": {
                    "model": "percentage-based",
                    "percentage": PREMIUM_PERCENTAGE,
                    "percentage_display": f"{PREMIUM_PERCENTAGE * 100}%",
                    "calculation": "Premium = Coverage Amount × 1%",
                    "currency": "USDC",
                    "examples": {
                        "min": {"coverage": 0.001, "premium": 0.00001},
                        "typical": {"coverage": 0.01, "premium": 0.0001},
                        "max": {"coverage": MAX_COVERAGE, "premium": MAX_COVERAGE * PREMIUM_PERCENTAGE}
                    }
                }
            },
            {
                "id": "submit-claim",
                "name": "Submit Fraud Claim",
                "description": "Submit a claim when a merchant fails to deliver. Includes zkp proof generation and instant USDC refund.",
                "endpoint": f"{base_url}/claim",
                "method": "POST",
                "x402Required": False,
                "inputSchema": {
                    "type": "object",
                    "required": ["policy_id", "http_response"],
                    "properties": {
                        "policy_id": {
                            "type": "string",
                            "format": "uuid",
                            "description": "Policy ID from insurance purchase"
                        },
                        "http_response": {
                            "type": "object",
                            "required": ["status", "body"],
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
                        "claim_id": {"type": "string", "format": "uuid"},
                        "proof": {"type": "string"},
                        "payout_amount": {"type": "number"},
                        "refund_tx_hash": {"type": "string"},
                        "status": {"type": "string"}
                    }
                },
                "features": ["zkp-verification", "instant-refund", "public-proof"]
            },
            {
                "id": "verify-proof",
                "name": "Verify Zero-Knowledge Proof",
                "description": "Public endpoint to verify zkp proofs. Anyone can verify failure claims.",
                "endpoint": f"{base_url}/verify",
                "method": "POST",
                "x402Required": False,
                "public": True,
                "inputSchema": {
                    "type": "object",
                    "required": ["proof", "public_inputs"],
                    "properties": {
                        "proof": {"type": "string", "description": "zkp proof hex"},
                        "public_inputs": {"type": "array", "items": {"type": "integer"}}
                    }
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "valid": {"type": "boolean"},
                        "failure_detected": {"type": "boolean"},
                        "payout_amount": {"type": "number"}
                    }
                }
            }
        ],
        "metadata": {
            "category": "insurance",
            "tags": ["insurance", "x402", "zkp", "micropayments", "failure-protection"],
            "pricing": {
                "model": "percentage-based",
                "percentage": PREMIUM_PERCENTAGE,
                "currency": "USDC"
            },
            "performance": {
                "zkp_generation_time_ms": "10000-20000",
                "refund_time_ms": "2000-5000",
                "total_claim_time_ms": "15000-30000"
            },
            "rate_limits": {
                "/insure": {
                    "limit": "10 per hour",
                    "limit_per_minute": None,
                    "recommendation": "Implement exponential backoff if you receive 429 responses"
                },
                "/claim": {
                    "limit": "5 per hour",
                    "limit_per_minute": None,
                    "recommendation": "Implement exponential backoff if you receive 429 responses"
                },
                "/renew": {
                    "limit": "20 per hour",
                    "limit_per_minute": None,
                    "recommendation": "Renew policies before expiration to avoid coverage gaps"
                },
                "general": {
                    "limit": "200 per day, 50 per hour",
                    "recommendation": "Cache discovery endpoints (agent-card, pricing, schema) to reduce request volume"
                }
            },
            "agent_guidance": {
                "timeout_recommendations": {
                    "/insure": "5-10 seconds (simple x402 payment verification)",
                    "/claim": "30-45 seconds (includes zkp generation which takes 10-20s)",
                    "/verify": "5-10 seconds (proof verification)",
                    "/renew": "5-10 seconds (simple x402 payment verification)"
                },
                "memory_solution": {
                    "endpoint": "/policies?wallet=0xYourAddress",
                    "description": "Retrieve active policies by wallet address. Solves agent context window memory loss.",
                    "use_case": "If you forget your policy_id after context reset, query by wallet address"
                },
                "policy_expiration": {
                    "duration": "24 hours (initial)",
                    "max_extension": "168 hours (7 days)",
                    "grace_period": None,
                    "renewal_available": True,
                    "renewal_endpoint": "/renew",
                    "recommendation": "Use /renew endpoint to extend policies before expiration. Pro-rated fees: 24h extension = full premium."
                },
                "error_handling": {
                    "429_rate_limit": "Implement exponential backoff (1s, 2s, 4s, 8s...)",
                    "402_payment_required": "First request returns 402 with payment details. Sign payment and retry.",
                    "503_service_unavailable": "Retry with exponential backoff, check /health endpoint"
                }
            }
        },
        "links": {
            "self": f"{base_url}/.well-known/agent-card.json",
            "api": f"{base_url}/api",
            "schema": f"{base_url}/api/schema",
            "pricing": f"{base_url}/api/pricing",
            "dashboard": f"{base_url}/",
            "health": f"{base_url}/health"
        }
    })


@app.route('/health')
def health():
    """Health check with real dependency status."""
    zk_status = "operational" if not getattr(zkengine, 'use_mock', True) else "mock"
    bc_connected = False
    try:
        bc_connected = blockchain.w3.is_connected() if blockchain else False
    except Exception:
        bc_connected = False
    status = "healthy" if bc_connected else "degraded"
    return jsonify({
        "status": status,
        "zkengine": zk_status,
        "blockchain": "connected" if bc_connected else "disconnected",
        "wallet": getattr(blockchain, 'has_wallet', False)
    })


@app.route('/insure', methods=['POST'])
@limiter.limit("10 per hour")
def insure():
    """
    Create insurance policy

    x402 payment required: Automatically verified by PaymentMiddleware

    Body:
      {
        "merchant_url": "https://api.example.com",
        "coverage_amount": 50  # USDC (testing: max 100 USDC)
      }

    Returns:
      {
        "policy_id": "uuid",
        "agent_address": "0x...",
        "coverage_amount": 50,
        "premium": 1,  # 1 USDC for testing
        "status": "active",
        "expires_at": "2025-11-07T10:00:00"
      }
    """
    # Get request data first to calculate premium
    data = request.json or {}
    merchant_url = data.get('merchant_url')
    coverage_amount = data.get('coverage_amount')

    if not merchant_url or not coverage_amount:
        return jsonify({"error": "Missing merchant_url or coverage_amount"}), 400

    # Validate coverage amount
    if coverage_amount is None:
        return jsonify({"error": "coverage_amount required"}), 400

    if coverage_amount <= 0:
        return jsonify({"error": "Coverage amount must be positive"}), 400

    if coverage_amount > MAX_COVERAGE:
        return jsonify({"error": f"Coverage exceeds maximum of {MAX_COVERAGE} USDC"}), 400

    # Calculate premium dynamically (1% of coverage)
    premium = float(Decimal(str(coverage_amount)) * Decimal(str(PREMIUM_PERCENTAGE)))
    premium_units = to_micro(premium)

    # Dynamic x402 payment requirement handled by custom implementation below
    # (payment_middleware SDK not used)

    # Payment verification using new payment verifier
    payment_header = getattr(g, 'payment_header', None)
    payer_header = getattr(g, 'payer_header', None)

    if not payment_header:
        # Return proper 402 with required payment details
        required = {
            "x402Version": 1,
            "payment": {
                "scheme": "exact",
                "network": "base",
                "amount": str(premium_units),
                "asset": {"address": USDC_ADDRESS, "decimals": 6, "symbol": "USDC"},
                "pay_to": BACKEND_ADDRESS,
                "mimeType": "application/json",
                "maxTimeoutSeconds": 60,
                "description": "Insurance premium (1% of requested coverage)"
            }
        }
        headers = {"X-Payment-Required": json.dumps(required["payment"])}
        return jsonify(required), 402, headers

    # Verify payment
    payment_details = payment_verifier.verify_payment(
        payment_header=payment_header,
        payer_address=payer_header,
        required_amount=premium_units,
        max_age_seconds=config.PAYMENT_MAX_AGE_SECONDS
    )

    if not payment_details.is_valid:
        logger.warning("Payment verification failed for premium=%s units", premium_units)
        required = {
            "error": "Payment verification failed",
            "expected_amount": str(premium_units),
            "asset": {"address": USDC_ADDRESS, "decimals": 6, "symbol": "USDC"},
            "pay_to": BACKEND_ADDRESS,
            "network": "base"
        }
        headers = {"X-Payment-Required": json.dumps(required)}
        return jsonify(required), 402, headers

    agent_address = payment_details.payer

    # Create policy
    policy_id = str(uuid.uuid4())
    merchant_url_hash = hashlib.sha256(merchant_url.encode()).hexdigest()

    policy = {
        "policy_id": policy_id,
        "agent_address": agent_address,
        "merchant_url": merchant_url,
        "merchant_url_hash": merchant_url_hash,
        "coverage_amount": coverage_amount,
        "coverage_amount_units": to_micro(coverage_amount),
        "premium": premium,
        "premium_units": premium_units,
        "status": "active",
        "created_at": iso_utc_now(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=POLICY_DURATION)).isoformat()
    }

    # Save policy using database client
    success = database.create_policy(policy_id, policy)
    if not success:
        logger.error("Failed to save policy: %s", policy_id)
        return jsonify({"error": "Failed to create policy"}), 500

    return jsonify({
        "policy_id": policy_id,
        "agent_address": policy["agent_address"],
        "coverage_amount": coverage_amount,
        "premium": premium,
        "status": "active",
        "expires_at": policy["expires_at"]
    }), 201


@app.route('/policies', methods=['GET'])
def get_policies():
    """
    Get active policies for a wallet address

    Query params:
        wallet: Agent's wallet address (0x...)

    Returns list of active policies for that wallet
    """
    wallet_address = request.args.get('wallet')

    if not wallet_address:
        return jsonify({"error": "wallet parameter required"}), 400

    # Normalize address to lowercase for comparison
    wallet_address = wallet_address.lower()

    # Filter policies for this wallet that are still active
    agent_policies = []
    current_time = datetime.now(timezone.utc)

    policies = load_data(POLICIES_FILE)
    for policy_id, policy in policies.items():
        if policy.get("agent_address", "").lower() == wallet_address:
            expires_at = parse_utc(policy["expires_at"]) if policy.get("expires_at") else datetime.now(timezone.utc)

            # Only include active policies (not expired, not claimed)
            if policy["status"] == "active" and expires_at > current_time:
                agent_policies.append({
                    "policy_id": policy.get("policy_id", policy_id),
                    "merchant_url": policy.get("merchant_url"),
                    "merchant_url_hash": policy.get("merchant_url_hash"),
                    "coverage_amount": policy.get("coverage_amount"),
                    "premium": policy.get("premium"),
                    "status": policy.get("status"),
                    "created_at": policy.get("created_at"),
                    "expires_at": policy.get("expires_at")
                })

    return jsonify({
        "wallet_address": wallet_address,
        "active_policies": agent_policies,
        "total_coverage": sum(p["coverage_amount"] for p in agent_policies),
        "claim_endpoint": "/claim",
        "renew_endpoint": "/renew",
        "note": "Use policy_id from any active policy to file a claim if merchant fails"
    }), 200


@app.route('/renew', methods=['POST'])
@limiter.limit("20 per hour")
def renew_policy():
    """
    Renew/extend an existing policy before expiration.

    Requires x402 payment for renewal fee (pro-rated based on extension duration).

    Body:
      {
        "policy_id": "uuid",
        "extend_hours": 24  // Number of hours to extend (default 24, max 168 = 7 days)
      }

    Returns:
      {
        "policy_id": "uuid",
        "old_expires_at": "2025-11-08T10:00:00Z",
        "new_expires_at": "2025-11-09T10:00:00Z",
        "extension_hours": 24,
        "renewal_fee": 0.0001,
        "renewal_count": 1,
        "status": "active"
      }
    """
    data = request.json
    policy_id = data.get('policy_id')
    extend_hours = data.get('extend_hours', 24)

    if not policy_id:
        return jsonify({"error": "Missing policy_id"}), 400

    if extend_hours < 1 or extend_hours > 168:  # Max 7 days
        return jsonify({"error": "extend_hours must be between 1 and 168 (7 days)"}), 400

    # Load policy
    policies = load_data(POLICIES_FILE)
    policy = policies.get(policy_id)

    if not policy:
        return jsonify({"error": "Policy not found"}), 404

    if policy['status'] != 'active':
        return jsonify({"error": f"Can only renew active policies (current status: {policy['status']})"}), 400

    # Check if already expired
    expires_at = parse_utc(policy["expires_at"])
    if expires_at < datetime.now(timezone.utc):
        return jsonify({"error": "Cannot renew expired policy. Please purchase a new policy."}), 400

    # Calculate renewal fee (pro-rated: percentage of coverage for extended duration)
    # Example: 24h extension = full premium, 12h = half premium
    hours_per_day = 24
    days_extended = extend_hours / hours_per_day
    renewal_fee = policy['coverage_amount'] * PREMIUM_PERCENTAGE * days_extended
    renewal_fee_units = to_micro(renewal_fee)

    # Check x402 payment
    payment_header = request.headers.get('X-Payment')
    payer_header = request.headers.get('X-Payer')

    if not payment_header or not payer_header:
        # Return 402 with renewal fee details
        required = {
            "x402Version": 1,
            "payment": {
                "scheme": "exact",
                "network": "base",
                "amount": str(renewal_fee_units),
                "asset": USDC_ADDRESS,
                "pay_to": BACKEND_ADDRESS,
                "description": f"Policy renewal fee for {extend_hours} hours extension",
                "maxTimeoutSeconds": 60
            },
            "policy_id": policy_id,
            "extend_hours": extend_hours,
            "renewal_fee": renewal_fee,
            "renewal_fee_display": f"{renewal_fee} USDC",
            "current_expires_at": policy['expires_at'],
            "new_expires_at": (expires_at + timedelta(hours=extend_hours)).isoformat()
        }
        headers = {"X-Payment-Required": json.dumps(required["payment"])}
        return jsonify(required), 402, headers

    # Verify payment
    payment_details = payment_verifier.verify_payment(
        payment_header=payment_header,
        payer_address=payer_header,
        required_amount=renewal_fee_units,
        max_age_seconds=config.PAYMENT_MAX_AGE_SECONDS
    )

    if not payment_details.is_valid:
        logger.warning("Payment verification failed for renewal: policy=%s, fee=%s units", policy_id, renewal_fee_units)
        return jsonify({
            "error": "Payment verification failed",
            "expected_amount": str(renewal_fee_units),
            "asset": {"address": USDC_ADDRESS, "decimals": 6, "symbol": "USDC"},
            "pay_to": BACKEND_ADDRESS
        }), 402

    # Verify payer is the policy owner
    if payment_details.payer.lower() != policy['agent_address'].lower():
        return jsonify({"error": "Only policy owner can renew policy"}), 403

    # Extend policy expiration
    old_expires_at = expires_at
    new_expires_at = old_expires_at + timedelta(hours=extend_hours)

    policy['expires_at'] = new_expires_at.isoformat()
    policy['renewed_at'] = iso_utc_now()
    policy['renewal_count'] = policy.get('renewal_count', 0) + 1
    policy['total_renewal_fees'] = policy.get('total_renewal_fees', 0.0) + renewal_fee

    # Save updated policy
    policies[policy_id] = policy
    save_data(POLICIES_FILE, policies)

    logger.info("Policy renewed: %s, extended by %d hours", policy_id, extend_hours)

    return jsonify({
        "policy_id": policy_id,
        "old_expires_at": old_expires_at.isoformat(),
        "new_expires_at": policy['expires_at'],
        "extension_hours": extend_hours,
        "renewal_fee": renewal_fee,
        "renewal_fee_display": f"{renewal_fee} USDC",
        "renewal_count": policy['renewal_count'],
        "total_paid": policy['premium'] + policy['total_renewal_fees'],
        "status": "active",
        "message": f"Policy successfully extended by {extend_hours} hours"
    }), 200


@app.route('/claim', methods=['POST'])
@limiter.limit("5 per hour")
def claim():
    """
    Submit failure claim (supports async processing)

    Query params (optional):
      async: bool (default: false) - If true, returns immediately with status "processing"

    Headers (optional):
      Idempotency-Key: string (prevents duplicate claims if retried)

    Body:
      {
        "policy_id": "uuid",
        "http_response": {
          "status": 503,
          "body": "",
          "headers": {}
        }
      }

    Returns (sync mode):
      {
        "claim_id": "uuid",
        "policy_id": "uuid",
        "proof": "0xabc...",
        "public_inputs": [1, 503, 0, 10000],
        "payout_amount": 10000,
        "refund_tx_hash": "0x...",
        "status": "paid",
        "proof_url": "/proofs/uuid"
      }

    Returns (async mode):
      {
        "claim_id": "uuid",
        "policy_id": "uuid",
        "status": "processing",
        "estimated_completion_seconds": 20,
        "poll_url": "/claims/uuid",
        "message": "Claim is being processed. Poll /claims/{claim_id} for status."
      }
    """
    data = request.json
    policy_id = data.get('policy_id')
    http_response = data.get('http_response')

    if not policy_id or not http_response:
        return jsonify({"error": "Missing policy_id or http_response"}), 400

    # Idempotency check: Allow agents to safely retry claim requests
    idempotency_key = request.headers.get('Idempotency-Key')
    if idempotency_key:
        # Check if claim with this idempotency key already exists
        claims = load_data(CLAIMS_FILE)
        for claim_id, existing_claim in claims.items():
            if existing_claim.get('idempotency_key') == idempotency_key:
                # Return existing claim (idempotent response)
                return jsonify({
                    "claim_id": existing_claim["claim_id"],
                    "policy_id": existing_claim["policy_id"],
                    "proof": existing_claim["proof"],
                    "public_inputs": existing_claim["public_inputs"],
                    "payout_amount": existing_claim["payout_amount"],
                    "refund_tx_hash": existing_claim["refund_tx_hash"],
                    "status": existing_claim["status"],
                    "proof_url": f"/proofs/{existing_claim['claim_id']}",
                    "idempotent": True,
                    "note": "This claim was already processed (idempotent response)"
                }), 200

    # Load policy
    policies = load_data(POLICIES_FILE)
    policy = policies.get(policy_id)

    if not policy:
        return jsonify({"error": "Policy not found"}), 404

    if policy["status"] != "active":
        return jsonify({"error": f"Policy is not active: {policy['status']}"}), 400

    # Check expiration
    if parse_utc(policy["expires_at"]) < datetime.now(timezone.utc):
        return jsonify({"error": "Policy expired"}), 400

    # Check if async mode requested
    async_mode = request.args.get('async', 'false').lower() in ('true', '1', 'yes')

    if async_mode:
        # Async mode: Create claim record with "processing" status and process in background
        claim_id = str(uuid.uuid4())
        http_body_hash = hashlib.sha256(http_response["body"].encode()).hexdigest()

        claim_record = {
            "claim_id": claim_id,
            "policy_id": policy_id,
            "status": "processing",
            "http_response": http_response,  # Store for background processing
            "http_status": http_response["status"],
            "http_body_hash": http_body_hash,
            "http_headers": http_response.get("headers", {}),
            "agent_address": policy["agent_address"],
            "coverage_amount": policy.get("coverage_amount"),
            "coverage_amount_units": policy.get("coverage_amount_units") or to_micro(policy.get("coverage_amount")),
            "created_at": iso_utc_now(),
            "idempotency_key": idempotency_key
        }

        # Save claim with "processing" status
        claims = load_data(CLAIMS_FILE)
        claims[claim_id] = claim_record
        save_data(CLAIMS_FILE, claims)

        # Start background thread to process claim
        import threading
        thread = threading.Thread(
            target=process_claim_async,
            args=(claim_id,),
            daemon=True
        )
        thread.start()

        logger.info("Claim submitted for async processing: %s", claim_id)

        # Return immediately with 202 Accepted
        return jsonify({
            "claim_id": claim_id,
            "policy_id": policy_id,
            "status": "processing",
            "estimated_completion_seconds": 20,
            "poll_url": f"/claims/{claim_id}",
            "message": "Claim is being processed in the background. Poll /claims/{claim_id} for status.",
            "async_mode": True
        }), 202  # 202 Accepted

    # Synchronous mode (default): Process claim inline
    # Generate zkEngine proof
    try:
        proof_hex, public_inputs, gen_time_ms = zkengine.generate_proof(
            http_status=http_response["status"],
            http_body=http_response["body"],
            http_headers=http_response.get("headers", {})
        )
    except Exception as e:
        return jsonify({"error": f"Proof generation failed: {str(e)}"}), 500

    # Verify proof (sanity check)
    try:
        is_valid = zkengine.verify_proof(proof_hex, public_inputs)
    except Exception as e:
        return jsonify({"error": f"Proof verification failed: {str(e)}"}), 500

    if not is_valid:
        return jsonify({"error": "Generated proof is invalid (internal error)"}), 500

    # Parse public inputs
    is_failure = public_inputs[0]
    detected_status = public_inputs[1]
    body_length = public_inputs[2]
    zkengine_payout = public_inputs[3]  # zkEngine's suggested payout (may be hardcoded)

    if is_failure != 1:
        return jsonify({"error": "No failure detected in HTTP response"}), 400

    # Use policy coverage amount as payout (parametric insurance)
    # zkEngine proves failure occurred, we pay the full coverage amount
    payout_amount = policy.get("coverage_amount")

    # Issue USDC refund
    # Convert USDC to smallest units (6 decimals): 0.01 USDC = 10,000 units
    payout_amount_units = policy.get("coverage_amount_units") or to_micro(payout_amount)

    try:
        refund_tx_hash = blockchain.issue_refund(
            to_address=policy["agent_address"],
            amount=payout_amount_units
        )
    except Exception as e:
        return jsonify({"error": f"Refund failed: {str(e)}"}), 500

    # Create claim record
    claim_id = str(uuid.uuid4())
    http_body_hash = hashlib.sha256(http_response["body"].encode()).hexdigest()

    claim_record = {
        "claim_id": claim_id,
        "policy_id": policy_id,
        "proof": proof_hex,
        "public_inputs": public_inputs,
        "proof_generation_time_ms": gen_time_ms,
        "verification_result": True,
        "http_status": http_response["status"],
        "http_body_hash": http_body_hash,
        "http_headers": http_response.get("headers", {}),
        "payout_amount": payout_amount,
        "payout_amount_units": payout_amount_units,
        "refund_tx_hash": refund_tx_hash,
        "recipient_address": policy["agent_address"],
        "status": "paid",
        "created_at": iso_utc_now(),
        "paid_at": iso_utc_now(),
        "idempotency_key": idempotency_key  # Store for future idempotent requests
    }

    # Save claim
    claims = load_data(CLAIMS_FILE)
    claims[claim_id] = claim_record
    save_data(CLAIMS_FILE, claims)

    # Update policy status
    policy["status"] = "claimed"
    save_data(POLICIES_FILE, policies)

    return jsonify({
        "claim_id": claim_id,
        "policy_id": policy_id,
        "proof": proof_hex,
        "public_inputs": public_inputs,
        "payout_amount": payout_amount,
        "refund_tx_hash": refund_tx_hash,
        "status": "paid",
        "proof_url": f"/proofs/{claim_id}"
    }), 201


@app.route('/claims/<claim_id>', methods=['GET'])
def get_claim_status(claim_id):
    """
    Get claim processing status (for polling)

    Allows agents to check claim status without downloading full proof data.
    Useful for polling during async proof generation (future enhancement).

    Returns:
      {
        "claim_id": "uuid",
        "policy_id": "uuid",
        "status": "paid|processing|failed",
        "payout_amount": 0.01,
        "refund_tx_hash": "0x...",
        "proof_url": "/proofs/uuid",
        "created_at": "2025-11-08T10:00:00Z",
        "paid_at": "2025-11-08T10:00:15Z"
      }
    """
    claims = load_data(CLAIMS_FILE)
    claim = claims.get(claim_id)

    if not claim:
        return jsonify({"error": "Claim not found"}), 404

    # Return lightweight status info (no full proof data)
    return jsonify({
        "claim_id": claim["claim_id"],
        "policy_id": claim["policy_id"],
        "status": claim.get("status", "unknown"),
        "payout_amount": claim.get("payout_amount"),
        "refund_tx_hash": claim.get("refund_tx_hash"),
        "proof_url": f"/proofs/{claim_id}",
        "created_at": claim.get("created_at"),
        "paid_at": claim.get("paid_at"),
        "proof_generation_time_ms": claim.get("proof_generation_time_ms")
    }), 200


@app.route('/verify', methods=['POST'])
def verify():
    """
    PUBLIC ENDPOINT: Verify zkEngine proof

    Body:
      {
        "proof": "0xabc...",
        "public_inputs": [1, 503, 0, 10000]
      }

    Returns:
      {
        "valid": true,
        "failure_detected": true,
        "payout_amount": 10000
      }
    """
    data = request.json
    proof = data.get('proof')
    public_inputs = data.get('public_inputs')

    if not proof or not public_inputs:
        return jsonify({"error": "Missing proof or public_inputs"}), 400

    try:
        is_valid = zkengine.verify_proof(proof, public_inputs)

        failure_detected = public_inputs[0] == 1 if len(public_inputs) > 0 else False
        payout_amount = public_inputs[3] if len(public_inputs) > 3 else 0

        return jsonify({
            "valid": is_valid,
            "public_inputs": public_inputs,
            "failure_detected": failure_detected,
            "payout_amount": payout_amount
        })

    except Exception as e:
        return jsonify({
            "valid": False,
            "error": str(e)
        }), 500


@app.route('/proofs/<claim_id>', methods=['GET'])
def get_proof(claim_id):
    """
    PUBLIC ENDPOINT: Download proof data

    Returns:
      {
        "claim_id": "uuid",
        "proof": "0xabc...",
        "public_inputs": [1, 503, 0, 10000],
        "http_status": 503,
        "http_body_hash": "sha256...",
        "http_headers": {},
        "verification_result": true,
        "payout_amount": 10000,
        "refund_tx_hash": "0x...",
        "recipient_address": "0x...",
        "status": "paid",
        "created_at": "2025-11-06T10:00:00",
        "paid_at": "2025-11-06T10:00:05"
      }
    """
    claims = load_data(CLAIMS_FILE)
    claim = claims.get(claim_id)

    if not claim:
        return jsonify({"error": "Claim not found"}), 404

    return jsonify(claim)


#############################################
# Basic in-process metrics (prototype)
#############################################

METRICS = {
    "policies_created_total": 0,
    "claims_paid_total": 0,
}


@app.after_request
def after_request(resp):
    try:
        if request.endpoint == 'insure' and resp.status_code == 201:
            METRICS["policies_created_total"] += 1
        if request.endpoint == 'claim' and resp.status_code == 201:
            METRICS["claims_paid_total"] += 1
    except Exception:
        pass
    return resp


@app.route('/api/reserves')
def reserves():
    """Reserve health monitoring endpoint"""
    try:
        health = reserve_monitor.check_reserve_health()
        return jsonify(health), 200
    except Exception as e:
        logger.exception("Error checking reserves: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route('/metrics')
def metrics():
    lines = [
        f"x402_policies_created_total {METRICS['policies_created_total']}",
        f"x402_claims_paid_total {METRICS['claims_paid_total']}"
    ]
    return '\n'.join(lines) + '\n', 200, {"Content-Type": "text/plain; version=0.0.4"}


if __name__ == '__main__':
    port = config.PORT
    debug = config.DEBUG
    logger.info("Starting x402 Insurance Service on %s:%d (debug=%s)", config.HOST, port, debug)
    app.run(host=config.HOST, port=port, debug=debug)
