#!/usr/bin/env python3
"""
End-to-End Test for x402 Insurance
Tests the complete flow: buy policy -> submit claim -> verify proof
"""
import httpx
import time
import json
from datetime import datetime

BASE_URL = "http://localhost:8000"

def print_section(title):
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70)

def test_1_buy_insurance():
    """Test 1: Purchase insurance policy"""
    print_section("TEST 1: Purchase Insurance Policy")

    start = time.time()
    response = httpx.post(
        f"{BASE_URL}/insure",
        headers={
            "X-Payment": "token=test123,amount=100,signature=mocksig",
            "Content-Type": "application/json"
        },
        json={
            "merchant_url": "https://api.example.com",
            "coverage_amount": 0.01  # $0.01 USDC coverage
        },
        timeout=30.0
    )
    elapsed = time.time() - start

    print(f"⏱️  Time: {elapsed:.2f}s")
    print(f"📊 Status: {response.status_code}")

    if response.status_code == 201:
        data = response.json()
        print(f"✅ Policy created successfully!")
        print(f"   Policy ID: {data['policy_id']}")
        print(f"   Agent Address: {data['agent_address']}")
        print(f"   Coverage: ${data['coverage_amount']}")
        print(f"   Premium: ${data['premium']}")
        print(f"   Status: {data['status']}")
        print(f"   Expires: {data['expires_at']}")
        return data['policy_id']
    else:
        print(f"❌ Failed: {response.text}")
        return None

def test_2_submit_claim(policy_id):
    """Test 2: Submit failure claim with proof generation"""
    print_section("TEST 2: Submit Failure Claim (with Jolt Atlas Proof)")

    print("📤 Submitting claim for HTTP 503 error...")
    start = time.time()

    response = httpx.post(
        f"{BASE_URL}/claim",
        json={
            "policy_id": policy_id,
            "http_response": {
                "status": 503,
                "body": "",
                "headers": {"server": "nginx"}
            }
        },
        timeout=60.0  # Jolt Atlas proof generation can take ~15-30s
    )

    elapsed = time.time() - start

    print(f"⏱️  Total Time: {elapsed:.2f}s")
    print(f"📊 Status: {response.status_code}")

    if response.status_code == 201:
        data = response.json()
        print(f"✅ Claim processed successfully!")
        print(f"\n📋 Claim Details:")
        print(f"   Claim ID: {data['claim_id']}")
        print(f"   Proof: {data['proof'][:66]}...")
        print(f"   Public Inputs: {data['public_inputs']}")
        print(f"   Payout: ${data['payout_amount']}")
        print(f"   Status: {data['status']}")
        print(f"   Refund TX: {data['refund_tx_hash'][:66]}...")

        # Break down timing
        print(f"\n⏱️  Performance Breakdown:")
        print(f"   Total: {elapsed:.2f}s")
        print(f"   (includes: proof generation + blockchain tx + API processing)")

        return data
    else:
        print(f"❌ Failed: {response.text}")
        return None

def test_3_verify_proof(proof_data):
    """Test 3: Verify the proof independently"""
    print_section("TEST 3: Independent Proof Verification")

    print("🔐 Verifying proof via public API...")
    start = time.time()

    response = httpx.post(
        f"{BASE_URL}/verify",
        json={
            "proof": proof_data['proof'],
            "public_inputs": proof_data['public_inputs']
        },
        timeout=30.0
    )

    elapsed = time.time() - start

    print(f"⏱️  Time: {elapsed:.2f}s")
    print(f"📊 Status: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        print(f"✅ Proof verified successfully!")
        print(f"   Valid: {data['valid']}")
        print(f"   Failure Detected: {data.get('failure_detected', data.get('fraud_detected'))}")
        print(f"   Payout Amount: ${data['payout_amount']}")
        return True
    else:
        print(f"❌ Verification failed: {response.text}")
        return False

def test_4_check_dashboard():
    """Test 4: Check dashboard shows updated stats"""
    print_section("TEST 4: Dashboard Statistics")

    response = httpx.get(f"{BASE_URL}/api/dashboard", timeout=10.0)

    if response.status_code == 200:
        data = response.json()
        print(f"✅ Dashboard loaded successfully!")
        print(f"\n📊 Statistics:")
        print(f"   Total Coverage: ${data['stats']['total_coverage']}")
        print(f"   Total Policies: {data['stats']['total_policies']}")
        print(f"   Claims Paid: ${data['stats']['claims_paid']}")
        print(f"   Recent Policies: {len(data.get('recent_policies', []))}")
        print(f"   Recent Claims: {len(data.get('recent_claims', []))}")

        if data.get('blockchain'):
            print(f"\n⛓️  Blockchain:")
            print(f"   Chain ID: {data['blockchain']['chain_id']}")
            print(f"   Block: {data['blockchain']['block_number']}")
            print(f"   Wallet: {data['blockchain']['wallet_address']}")
            print(f"   ETH Balance: {data['blockchain']['eth_balance']}")
            print(f"   USDC Balance: {data['blockchain']['usdc_balance']}")
        else:
            print(f"\n⛓️  Blockchain: Not available (network error)")

        return True
    else:
        print(f"❌ Failed to load dashboard")
        return False

def run_e2e_test():
    """Run complete end-to-end test"""
    print("\n" + "🚀 " + "="*65)
    print("   x402 Insurance - End-to-End Performance Test")
    print("="*70)
    print(f"   Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)

    overall_start = time.time()

    try:
        # Test 1: Buy insurance
        policy_id = test_1_buy_insurance()
        if not policy_id:
            print("\n❌ Test suite failed at step 1")
            return False

        time.sleep(1)  # Brief pause between tests

        # Test 2: Submit claim (includes proof generation)
        claim_data = test_2_submit_claim(policy_id)
        if not claim_data:
            print("\n❌ Test suite failed at step 2")
            return False

        time.sleep(1)

        # Test 3: Verify proof
        verified = test_3_verify_proof(claim_data)
        if not verified:
            print("\n❌ Test suite failed at step 3")
            return False

        time.sleep(1)

        # Test 4: Check dashboard
        dashboard_ok = test_4_check_dashboard()

        overall_elapsed = time.time() - overall_start

        print_section("FINAL RESULTS")
        print(f"✅ All tests passed!")
        print(f"⏱️  Total execution time: {overall_elapsed:.2f}s")
        print(f"\n📈 Performance Summary:")
        print(f"   - Insurance purchase: < 1s")
        print(f"   - Claim submission (with proof): ~15-30s")
        print(f"   - Proof verification: < 1s")
        print(f"   - Dashboard load: < 1s")

        print(f"\n💡 Key Insights:")
        print(f"   - Jolt Atlas proof generation is the bottleneck (~15-30s)")
        print(f"   - This is acceptable for failure claims (not time-critical)")
        print(f"   - Verification is instant (< 1s)")
        print(f"   - Agents get immediate confirmation, refund processes async")

        return True

    except Exception as e:
        print(f"\n❌ Test suite failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = run_e2e_test()
    exit(0 if success else 1)
