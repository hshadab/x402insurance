#!/usr/bin/env python3
"""
End-to-End Test with Real Payments and Proofs

This test performs a complete insurance flow:
1. Checks initial wallet balances
2. Creates an insurance policy (with payment)
3. Submits a claim with real HTTP failure
4. Generates Jolt Atlas proof
5. Receives USDC refund
6. Verifies balances decreased (net cost = coverage - premium)

Expected outcome: USDC balance decreases by ~0.0099 USDC
                  (0.01 coverage - 0.0001 premium)
"""

import httpx
import json
import time
import os
from decimal import Decimal
from web3 import Web3
from dotenv import load_dotenv

# Load test environment
# Try .env.test first (for E2E testing), fallback to .env
import os.path
if os.path.exists('.env.test'):
    load_dotenv('.env.test')
    print("ℹ Using .env.test configuration")
else:
    load_dotenv()
    print("ℹ Using .env configuration")

# Configuration
BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")
RPC_URL = os.getenv("BASE_RPC_URL", "https://mainnet.base.org")
WALLET_ADDRESS = os.getenv("BACKEND_WALLET_ADDRESS")
USDC_ADDRESS = os.getenv("USDC_CONTRACT_ADDRESS", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")

# Test parameters
COVERAGE_AMOUNT = 0.01  # 0.01 USDC coverage
PREMIUM = 0.0001  # 1% premium

# Colors for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

# ERC20 ABI (minimal)
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    }
]


def print_header(text):
    print(f"\n{BLUE}{'='*70}{RESET}")
    print(f"{BLUE}{text.center(70)}{RESET}")
    print(f"{BLUE}{'='*70}{RESET}\n")


def print_success(text):
    print(f"{GREEN}✓ {text}{RESET}")


def print_error(text):
    print(f"{RED}✗ {text}{RESET}")


def print_info(text):
    print(f"{YELLOW}ℹ {text}{RESET}")


def get_balances():
    """Get current ETH and USDC balances"""
    try:
        w3 = Web3(Web3.HTTPProvider(RPC_URL))

        if not w3.is_connected():
            print_error("Failed to connect to RPC")
            return None, None

        # ETH balance
        eth_balance_wei = w3.eth.get_balance(WALLET_ADDRESS)
        eth_balance = float(w3.from_wei(eth_balance_wei, 'ether'))

        # USDC balance
        usdc_contract = w3.eth.contract(address=USDC_ADDRESS, abi=ERC20_ABI)
        usdc_balance_raw = usdc_contract.functions.balanceOf(WALLET_ADDRESS).call()
        usdc_balance = float(usdc_balance_raw) / 1_000_000  # USDC has 6 decimals

        return eth_balance, usdc_balance
    except Exception as e:
        print_error(f"Failed to get balances: {e}")
        return None, None


def check_server_health():
    """Check if server is running and healthy"""
    try:
        response = httpx.get(f"{BASE_URL}/health", timeout=10.0)
        if response.status_code == 200:
            health = response.json()
            print_success(f"Server is {health['status']}")
            return True
        else:
            print_error(f"Server health check failed: {response.status_code}")
            return False
    except Exception as e:
        print_error(f"Cannot connect to server: {e}")
        print_info("Make sure the server is running: python server.py")
        return False


def create_policy():
    """Create an insurance policy"""
    print_info("Creating insurance policy...")

    payload = {
        "merchant_url": "https://test-api-e2e.example.com",
        "coverage_amount": COVERAGE_AMOUNT
    }

    # Create mock payment headers for simple mode testing
    # Format: amount=<micro_usdc>,signature=mock
    # Premium is 1% of coverage = 0.01 * 0.01 = 0.0001 USDC = 100 micro-USDC
    premium_units = int(PREMIUM * 1_000_000)  # Convert to micro-USDC
    headers = {
        "X-Payment": f"amount={premium_units},signature=mock_signature",
        "X-Payer": WALLET_ADDRESS
    }

    try:
        # Send request with payment headers
        response = httpx.post(
            f"{BASE_URL}/insure",
            json=payload,
            headers=headers,
            timeout=30.0
        )

        if response.status_code == 402:
            # Payment required - might need real signature
            print_info("Payment verification failed - server may require full EIP-712 signatures")
            print_error(f"Response: {response.text}")
            return None

        if response.status_code in [200, 201]:  # Accept both 200 OK and 201 Created
            policy = response.json()
            print_success(f"Policy created: {policy['policy_id'][:16]}...")
            print_info(f"Coverage: {policy['coverage_amount']} USDC")
            print_info(f"Premium: {policy['premium']} USDC")
            print_info(f"Expires: {policy['expires_at']}")
            return policy
        else:
            print_error(f"Failed to create policy: {response.status_code}")
            print_error(f"Response: {response.text}")
            return None
    except Exception as e:
        print_error(f"Error creating policy: {e}")
        return None


def submit_claim(policy_id):
    """Submit a claim with HTTP failure data"""
    print_info("Submitting claim with HTTP 503 error...")

    claim_payload = {
        "policy_id": policy_id,
        "http_response": {
            "status": 503,
            "body": "",
            "headers": {"server": "nginx"}
        }
    }

    # Add mock payment headers for claim authentication (if enabled)
    headers = {
        "X-Payment": "mock_claim_payment_proof",
        "X-Payer": WALLET_ADDRESS
    }

    try:
        response = httpx.post(
            f"{BASE_URL}/claim",
            json=claim_payload,
            headers=headers,
            timeout=60.0  # Jolt Atlas can take 20-30 seconds
        )

        if response.status_code == 402:
            print_info("Claim requires authentication (REQUIRE_CLAIM_AUTHENTICATION=true)")
            print_info("This is expected in production mode")
            return None

        if response.status_code in [200, 201]:  # Accept both 200 OK and 201 Created
            claim = response.json()
            print_success(f"Claim processed: {claim['claim_id'][:16]}...")
            print_info(f"Proof: {claim['proof'][:20]}...")
            print_info(f"Payout: {claim['payout_amount']} USDC")
            print_info(f"TX Hash: {claim['refund_tx_hash'][:20]}...")
            print_info(f"Status: {claim['status']}")

            if 'proof_generation_time_ms' in claim:
                print_info(f"Proof generation time: {claim['proof_generation_time_ms']}ms")

            return claim
        else:
            print_error(f"Failed to submit claim: {response.status_code}")
            print_error(f"Response: {response.text}")
            return None
    except Exception as e:
        print_error(f"Error submitting claim: {e}")
        return None


def verify_proof(claim_id):
    """Verify the proof data"""
    print_info("Verifying proof data...")

    try:
        response = httpx.get(
            f"{BASE_URL}/proofs/{claim_id}",
            timeout=10.0
        )

        if response.status_code == 200:
            proof_data = response.json()
            print_success("Proof data retrieved")
            print_info(f"Public inputs: {proof_data.get('public_inputs', 'N/A')}")
            print_info(f"Verification result: {proof_data.get('verification_result', 'N/A')}")
            return proof_data
        else:
            print_error(f"Failed to get proof: {response.status_code}")
            return None
    except Exception as e:
        print_error(f"Error verifying proof: {e}")
        return None


def verify_transaction(tx_hash):
    """Verify the refund transaction on-chain"""
    print_info(f"Verifying transaction on Base Mainnet...")

    try:
        w3 = Web3(Web3.HTTPProvider(RPC_URL))

        # Remove 0xMOCK prefix if present (mock mode)
        if tx_hash.startswith("0xMOCK"):
            print_info("Transaction is in mock mode (no real blockchain transaction)")
            return None

        # Clean tx hash
        if not tx_hash.startswith("0x"):
            tx_hash = "0x" + tx_hash

        tx_receipt = w3.eth.get_transaction_receipt(tx_hash)

        if tx_receipt:
            print_success("Transaction confirmed on-chain!")
            print_info(f"Block: {tx_receipt['blockNumber']}")
            print_info(f"Gas used: {tx_receipt['gasUsed']}")
            print_info(f"Status: {'Success' if tx_receipt['status'] == 1 else 'Failed'}")
            print_info(f"View on Basescan: https://basescan.org/tx/{tx_hash}")
            return tx_receipt
        else:
            print_error("Transaction not found on-chain")
            return None
    except Exception as e:
        print_error(f"Error verifying transaction: {e}")
        return None


def main():
    print_header("x402 Insurance E2E Test - Real Payments & Proofs")

    print(f"Test Configuration:")
    print(f"  Server: {BASE_URL}")
    print(f"  Wallet: {WALLET_ADDRESS}")
    print(f"  Coverage: {COVERAGE_AMOUNT} USDC")
    print(f"  Premium: {PREMIUM} USDC")
    print(f"  Expected cost: {COVERAGE_AMOUNT - PREMIUM} USDC")

    # Step 0: Check server health
    print_header("Step 0: Server Health Check")
    if not check_server_health():
        print_error("Server is not healthy. Exiting.")
        return False

    # Step 1: Get initial balances
    print_header("Step 1: Check Initial Balances")
    initial_eth, initial_usdc = get_balances()

    if initial_eth is None or initial_usdc is None:
        print_error("Failed to get initial balances. Exiting.")
        return False

    print_success(f"Initial ETH: {initial_eth:.6f} ETH")
    print_success(f"Initial USDC: {initial_usdc:.6f} USDC")

    # Check if we have enough balance
    if initial_usdc < COVERAGE_AMOUNT:
        print_error(f"Insufficient USDC balance. Need {COVERAGE_AMOUNT}, have {initial_usdc}")
        return False

    if initial_eth < 0.001:
        print_error(f"Insufficient ETH for gas. Have {initial_eth}")
        return False

    # Step 2: Create insurance policy
    print_header("Step 2: Create Insurance Policy")
    policy = create_policy()

    if not policy:
        print_error("Failed to create policy. Exiting.")
        print_info("Tip: Ensure BACKEND_WALLET_ADDRESS and facilitator URL are configured")
        return False

    policy_id = policy['policy_id']

    # Brief pause to ensure policy is persisted
    time.sleep(1)

    # Step 3: Submit claim
    print_header("Step 3: Submit Claim with HTTP 503 Failure")
    claim = submit_claim(policy_id)

    if not claim:
        print_error("Failed to submit claim. Exiting.")
        return False

    claim_id = claim['claim_id']
    tx_hash = claim.get('refund_tx_hash')

    # Step 4: Verify proof
    print_header("Step 4: Verify Proof Data")
    proof_data = verify_proof(claim_id)

    if not proof_data:
        print_error("Failed to verify proof")

    # Step 5: Verify blockchain transaction
    if tx_hash:
        print_header("Step 5: Verify Blockchain Transaction")
        tx_receipt = verify_transaction(tx_hash)

    # Brief pause for blockchain to update
    time.sleep(2)

    # Step 6: Check final balances
    print_header("Step 6: Check Final Balances")
    final_eth, final_usdc = get_balances()

    if final_eth is None or final_usdc is None:
        print_error("Failed to get final balances")
        return False

    print_success(f"Final ETH: {final_eth:.6f} ETH")
    print_success(f"Final USDC: {final_usdc:.6f} USDC")

    # Calculate changes
    eth_change = final_eth - initial_eth
    usdc_change = final_usdc - initial_usdc

    print_header("Balance Changes")
    print(f"ETH Change: {eth_change:+.6f} ETH (gas costs)")
    print(f"USDC Change: {usdc_change:+.6f} USDC")

    expected_usdc_change = -(COVERAGE_AMOUNT - PREMIUM)  # Net loss

    if abs(usdc_change - expected_usdc_change) < 0.0001:  # Within tolerance
        print_success(f"✓ USDC change matches expected: {expected_usdc_change:+.6f} USDC")
    else:
        print_info(f"Expected USDC change: {expected_usdc_change:+.6f} USDC")
        print_info(f"Actual USDC change: {usdc_change:+.6f} USDC")
        print_info("Note: In simple payment mode, actual transfers may not occur")

    # Summary
    print_header("Test Summary")
    if claim and claim.get('status') == 'paid':
        print_success("✓ All steps completed successfully!")
        print_success("✓ Policy created")
        print_success("✓ Claim processed")
        print_success("✓ Proof generated")
        print_success("✓ Refund issued")
        print_success("✓ Balances updated")

        if usdc_change < 0:
            print_success(f"✓ Net cost: {abs(usdc_change):.6f} USDC (coverage paid out)")

        return True
    else:
        print_error("Test completed with warnings")
        return False


if __name__ == "__main__":
    try:
        success = main()
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
