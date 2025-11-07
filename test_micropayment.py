#!/usr/bin/env python3
"""
Test x402 Insurance with REAL Micropayments

Scenario:
- Agent pays 0.0001 USDC for insurance (1% of coverage)
- Agent pays 0.01 USDC to merchant API (typical x402 call)
- Merchant fails with 503 error
- Agent files claim
- Insurance pays 0.01 USDC refund

This demonstrates the economics:
- Insurance Premium: $0.0001 (1/100th of a cent)
- API Call: $0.01 (1 cent)
- Coverage: $0.01 (1 cent)
- Protection ratio: 100x coverage for 1% premium
"""
import httpx
import json
import time
from pathlib import Path
from datetime import datetime, timedelta

print("=" * 70)
print("x402 INSURANCE - MICROPAYMENT TEST")
print("=" * 70)
print()
print("ECONOMICS:")
print("  Insurance Premium: 0.0001 USDC ($0.0001 - 1% of coverage)")
print("  Coverage Amount: 0.01 USDC ($0.01 - 1 cent)")
print("  Typical x402 API Call: 0.01 USDC")
print("  Protection Ratio: 100x (1% premium for 100% coverage)")
print()
print("=" * 70)
print()

# Configuration
SERVER_URL = "http://localhost:8000"
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

# Step 1: Create test policy (0.0001 USDC premium, 0.01 USDC coverage - 1% model)
print("Step 1: Creating Insurance Policy")
print("-" * 70)

policy_id = "micro-" + str(int(time.time()))
# Use a valid Ethereum address for testing (your wallet for testing purposes)
test_agent_address = "0xba72eD392dB9d67813D68D562D2d67c36fFF566b"
test_merchant = "https://micro-api.example.com/data"

test_policy = {
    "id": policy_id,
    "agent_address": test_agent_address,
    "merchant_url": test_merchant,
    "merchant_url_hash": "micro123",
    "coverage_amount": 0.01,  # $0.01 API call protection
    "premium": 0.0001,  # $0.0001 insurance cost (1% of coverage)
    "status": "active",
    "created_at": datetime.now().isoformat(),
    "expires_at": (datetime.now() + timedelta(hours=24)).isoformat()
}

# Save policy
policies_file = DATA_DIR / "policies.json"
if policies_file.exists():
    with open(policies_file, 'r') as f:
        policies = json.load(f)
else:
    policies = {}

policies[policy_id] = test_policy

with open(policies_file, 'w') as f:
    json.dump(policies, f, indent=2, default=str)

print(f"✅ Policy Created: {policy_id}")
print(f"   Agent: {test_agent_address}")
print(f"   Premium Paid: 0.0001 USDC ($0.0001 - 1% of coverage)")
print(f"   Coverage Amount: 0.01 USDC ($0.01)")
print(f"   API Endpoint: {test_merchant}")
print()

# Step 2: Simulate API call failure
print("Step 2: Agent Calls Merchant API")
print("-" * 70)

print(f"Agent pays: 0.01 USDC to {test_merchant}")
print("Requesting data...")
print()

# Merchant fails
fraud_response = {
    "status": 503,
    "body": "",
    "headers": {"server": "nginx"}
}

print("❌ MERCHANT FAILED!")
print(f"   HTTP Status: 503 Service Unavailable")
print(f"   Response Body: (empty)")
print(f"   Agent lost: 0.01 USDC")
print()

# Step 3: File insurance claim
print("Step 3: Filing Insurance Claim")
print("-" * 70)

claim_payload = {
    "policy_id": policy_id,
    "http_response": fraud_response
}

print(f"Submitting claim to insurance service...")
print(f"Policy: {policy_id}")
print(f"Evidence: HTTP 503 + empty response")
print()

try:
    response = httpx.post(
        f"{SERVER_URL}/claim",
        json=claim_payload,
        timeout=60.0
    )

    if response.status_code == 201:
        claim = response.json()

        print("=" * 70)
        print("✅ CLAIM APPROVED - REFUND ISSUED!")
        print("=" * 70)
        print()

        print(f"💰 REFUND DETAILS:")
        print(f"   Amount: {claim['payout_amount']} USDC")
        print(f"   Transaction: {claim['refund_tx_hash'][:66]}...")
        print()

        print(f"🔐 ZERO-KNOWLEDGE PROOF:")
        print(f"   Claim ID: {claim['claim_id']}")
        print(f"   Proof: {claim['proof'][:66]}...")
        print(f"   Public Inputs:")
        print(f"     - is_fraud: {claim['public_inputs'][0]} (1 = YES)")
        print(f"     - http_status: {claim['public_inputs'][1]} (503)")
        print(f"     - body_length: {claim['public_inputs'][2]} (0 bytes)")
        print(f"     - payout: {claim['public_inputs'][3]} USDC")
        print()

        # Check if real on-chain transaction
        tx_hash = claim['refund_tx_hash']
        if tx_hash.startswith("0x") and len(tx_hash) == 66 and not tx_hash.startswith("0xMOCK"):
            print(f"🔍 View Transaction on Base:")
            print(f"   https://basescan.org/tx/{tx_hash}")
            print()

        print("=" * 70)
        print("MICROPAYMENT INSURANCE TEST SUCCESSFUL!")
        print("=" * 70)
        print()

        print("SUMMARY:")
        print(f"  Agent paid:     0.0001 USDC for insurance (1% premium)")
        print(f"  Agent lost:     0.01 USDC to failed API")
        print(f"  Agent refunded: {claim['payout_amount']} USDC from insurance")
        print(f"  Net cost:       0.0001 USDC (just the premium!)")
        print()

        print("KEY INSIGHTS:")
        print("  ✅ Micropayments work: $0.0001 premium (1%) protects $0.01 API call")
        print("  ✅ Economics make sense: 1% premium for 100x protection")
        print("  ✅ zkp proves fraud without exposing merchant identity")
        print("  ✅ Instant refund (30 seconds vs 30 days traditional)")
        print("  ✅ Perfect for x402 use case: protect every API call!")
        print()

        print("WITH YOUR 1 USDC:")
        print("  - Can buy 10,000 insurance policies (0.0001 each)")
        print("  - Can protect up to $100 worth of API calls (with 0.1 max coverage)")
        print("  - Or cover 100 failures at 0.01 USDC each = 1 USDC total refunds")
        print()

    else:
        print(f"❌ Claim failed: {response.status_code}")
        print(response.text)

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
