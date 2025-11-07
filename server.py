"""
x402 Insurance Service - Minimal Flask Server

Endpoints:
  GET  / - Dashboard UI
  GET  /api - API documentation
  GET  /api/dashboard - Dashboard data (live stats)
  POST /insure - Create insurance policy (requires x402 payment)
  POST /claim - Submit fraud claim
  POST /verify - Verify proof (public)
  GET  /proofs/<claim_id> - Get proof data (public)
"""
from flask import Flask, request, jsonify, g, send_from_directory
import json
import os
import uuid
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

from x402.flask.middleware import PaymentMiddleware
from x402.types import TokenAmount, TokenAsset, EIP712Domain

from zkengine_client import ZKEngineClient
from blockchain import BlockchainClient

# Load environment
load_dotenv()

# Initialize Flask
app = Flask(__name__, static_folder='static')

# Get backend wallet address for x402 payments
BACKEND_ADDRESS = os.getenv("BACKEND_WALLET_ADDRESS")
if not BACKEND_ADDRESS:
    print("⚠️  WARNING: BACKEND_WALLET_ADDRESS not set - x402 middleware will fail")
    print("   Set BACKEND_WALLET_ADDRESS in .env to receive x402 payments")

# Initialize services
zkengine = ZKEngineClient(os.getenv("ZKENGINE_BINARY_PATH", "./zkengine/zkengine-binary"))
blockchain = BlockchainClient(
    rpc_url=os.getenv("BASE_RPC_URL", "https://sepolia.base.org"),
    usdc_address=os.getenv("USDC_CONTRACT_ADDRESS", "0x036CbD53842c5426634e7929541eC2318f3dCF7e"),
    private_key=os.getenv("BACKEND_WALLET_PRIVATE_KEY")
)

# Configuration
PREMIUM_PERCENTAGE = float(os.getenv("PREMIUM_PERCENTAGE", "0.01"))  # 1% of coverage
MAX_COVERAGE = float(os.getenv("MAX_COVERAGE_USDC", "0.1"))
POLICY_DURATION = int(os.getenv("POLICY_DURATION_HOURS", "24"))
USDC_ADDRESS = os.getenv("USDC_CONTRACT_ADDRESS", "0x036CbD53842c5426634e7929541eC2318f3dCF7e")

# Initialize x402 payment middleware
if BACKEND_ADDRESS:
    payment_middleware = PaymentMiddleware(app)
    print(f"✅ x402 middleware initialized")
    print(f"   Premium: {PREMIUM_PERCENTAGE * 100}% of coverage amount")
    print(f"   Max coverage: {MAX_COVERAGE} USDC")
    print(f"   Payment recipient: {BACKEND_ADDRESS}")
else:
    print("⚠️  x402 middleware DISABLED - no payment verification")

# Simple JSON file storage
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

POLICIES_FILE = DATA_DIR / "policies.json"
CLAIMS_FILE = DATA_DIR / "claims.json"


def load_data(file_path):
    """Load data from JSON file"""
    if not file_path.exists():
        return {}
    with open(file_path, 'r') as f:
        return json.load(f)


def save_data(file_path, data):
    """Save data to JSON file"""
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=2, default=str)


@app.route('/')
def index():
    """Serve dashboard UI"""
    return send_from_directory('static', 'dashboard.html')


@app.route('/api')
def api_info():
    """API information with x402 discovery metadata"""
    base_url = request.host_url.rstrip('/')

    return jsonify({
        "service": "x402 Insurance API",
        "version": "1.0.0",
        "x402Version": 1,
        "description": "ZKP-verified insurance against x402 merchant fraud. Protect your micropayment API calls with zero-knowledge proof verified insurance.",
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
                    "maxAmountRequired": str(int(DEFAULT_PREMIUM * 1_000_000)),
                    "asset": USDC_ADDRESS,
                    "payTo": BACKEND_ADDRESS,
                    "description": "Insurance premium for micropayment protection",
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
            print(f"Error getting blockchain stats: {e}")

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
            "calculation": "Premium = Coverage Amount × 1%",
            "currency": "USDC",
            "network": "base",
            "examples": {
                "0.01_usdc_coverage": {
                    "coverage": 0.01,
                    "premium": 0.0001,
                    "premium_display": "$0.0001",
                    "units": 100
                },
                "0.05_usdc_coverage": {
                    "coverage": 0.05,
                    "premium": 0.0005,
                    "premium_display": "$0.0005",
                    "units": 500
                },
                "0.1_usdc_coverage": {
                    "coverage": 0.1,
                    "premium": 0.001,
                    "premium_display": "$0.001",
                    "units": 1000
                }
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
            "description": "Zero-knowledge proof verified insurance against x402 merchant fraud. Protect your micropayment API calls with instant refunds.",
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
                "description": "Public endpoint to verify zkp proofs. Anyone can verify fraud claims.",
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
                        "fraud_detected": {"type": "boolean"},
                        "payout_amount": {"type": "number"}
                    }
                }
            }
        ],
        "metadata": {
            "category": "insurance",
            "tags": ["insurance", "x402", "zkp", "micropayments", "fraud-protection"],
            "pricing": {
                "model": "pay-per-policy",
                "premium": DEFAULT_PREMIUM,
                "currency": "USDC"
            },
            "performance": {
                "zkp_generation_time_ms": "10000-20000",
                "refund_time_ms": "2000-5000",
                "total_claim_time_ms": "15000-30000"
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
    """Health check"""
    return jsonify({
        "status": "healthy",
        "zkengine": "operational",
        "blockchain": "connected"
    })


@app.route('/insure', methods=['POST'])
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
    data = request.json
    merchant_url = data.get('merchant_url')
    coverage_amount = data.get('coverage_amount')

    if not merchant_url or not coverage_amount:
        return jsonify({"error": "Missing merchant_url or coverage_amount"}), 400

    # Validate coverage amount
    if coverage_amount <= 0:
        return jsonify({"error": "Coverage amount must be positive"}), 400

    if coverage_amount > MAX_COVERAGE:
        return jsonify({"error": f"Coverage exceeds maximum of {MAX_COVERAGE} USDC"}), 400

    # Calculate premium dynamically (1% of coverage)
    premium = coverage_amount * PREMIUM_PERCENTAGE
    premium_units = int(premium * 1_000_000)  # Convert to smallest units

    # Add dynamic x402 payment requirement for this specific request
    if BACKEND_ADDRESS:
        payment_middleware.add(
            path="/insure",
            price=TokenAmount(
                amount=str(premium_units),
                asset=TokenAsset(
                    address=USDC_ADDRESS,
                    decimals=6,
                    eip712=EIP712Domain(name="USDC", version="2"),
                ),
            ),
            pay_to_address=BACKEND_ADDRESS,
            network="base",
        )

    # x402 middleware handles payment verification
    # Get payer address from x402 verification response
    verify_response = getattr(g, 'verify_response', None)

    if not verify_response or not verify_response.payer:
        return jsonify({
            "error": "Payment verification failed - no payer address found",
            "debug": "x402 middleware may not be configured correctly"
        }), 500

    agent_address = verify_response.payer

    # Create policy
    policy_id = str(uuid.uuid4())
    merchant_url_hash = hashlib.sha256(merchant_url.encode()).hexdigest()

    policy = {
        "id": policy_id,
        "agent_address": agent_address,
        "merchant_url": merchant_url,
        "merchant_url_hash": merchant_url_hash,
        "coverage_amount": coverage_amount,
        "premium": premium,
        "status": "active",
        "created_at": datetime.utcnow().isoformat(),
        "expires_at": (datetime.utcnow() + timedelta(hours=POLICY_DURATION)).isoformat()
    }

    # Save policy
    policies = load_data(POLICIES_FILE)
    policies[policy_id] = policy
    save_data(POLICIES_FILE, policies)

    return jsonify({
        "policy_id": policy_id,
        "agent_address": policy["agent_address"],
        "coverage_amount": coverage_amount,
        "premium": premium,
        "status": "active",
        "expires_at": policy["expires_at"]
    }), 201


@app.route('/claim', methods=['POST'])
def claim():
    """
    Submit fraud claim

    Body:
      {
        "policy_id": "uuid",
        "http_response": {
          "status": 503,
          "body": "",
          "headers": {}
        }
      }

    Returns:
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
    """
    data = request.json
    policy_id = data.get('policy_id')
    http_response = data.get('http_response')

    if not policy_id or not http_response:
        return jsonify({"error": "Missing policy_id or http_response"}), 400

    # Load policy
    policies = load_data(POLICIES_FILE)
    policy = policies.get(policy_id)

    if not policy:
        return jsonify({"error": "Policy not found"}), 404

    if policy["status"] != "active":
        return jsonify({"error": f"Policy is not active: {policy['status']}"}), 400

    # Check expiration
    if datetime.fromisoformat(policy["expires_at"]) < datetime.utcnow():
        return jsonify({"error": "Policy expired"}), 400

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
    is_fraud = public_inputs[0]
    detected_status = public_inputs[1]
    body_length = public_inputs[2]
    zkengine_payout = public_inputs[3]  # zkEngine's suggested payout (may be hardcoded)

    if is_fraud != 1:
        return jsonify({"error": "No fraud detected in HTTP response"}), 400

    # Use policy coverage amount as payout (parametric insurance)
    # zkEngine proves fraud occurred, we pay the full coverage amount
    payout_amount = policy["coverage_amount"]

    # Issue USDC refund
    # Convert USDC to smallest units (6 decimals): 0.01 USDC = 10,000 units
    payout_amount_units = int(payout_amount * 1_000_000)

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
        "id": claim_id,
        "policy_id": policy_id,
        "proof": proof_hex,
        "public_inputs": public_inputs,
        "proof_generation_time_ms": gen_time_ms,
        "verification_result": True,
        "http_status": http_response["status"],
        "http_body_hash": http_body_hash,
        "http_headers": http_response.get("headers", {}),
        "payout_amount": payout_amount,
        "refund_tx_hash": refund_tx_hash,
        "recipient_address": policy["agent_address"],
        "status": "paid",
        "created_at": datetime.utcnow().isoformat(),
        "paid_at": datetime.utcnow().isoformat()
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
        "fraud_detected": true,
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

        fraud_detected = public_inputs[0] == 1 if len(public_inputs) > 0 else False
        payout_amount = public_inputs[3] if len(public_inputs) > 3 else 0

        return jsonify({
            "valid": is_valid,
            "public_inputs": public_inputs,
            "fraud_detected": fraud_detected,
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


if __name__ == '__main__':
    port = int(os.getenv('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=True)
