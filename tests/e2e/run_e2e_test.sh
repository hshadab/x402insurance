#!/bin/bash
#
# End-to-End Test Runner with Real Payments
#
# This script:
# 1. Prompts for wallet credentials (not saved to disk)
# 2. Runs the E2E test with real blockchain interactions
# 3. Cleans up environment variables
#
# Usage: ./run_e2e_test.sh
#

set -e

echo "======================================================================"
echo "  x402 Insurance - End-to-End Test with Real Payments"
echo "======================================================================"
echo ""
echo "⚠️  WARNING: This test will use real USDC and ETH from your wallet"
echo "    Expected cost: ~0.0099 USDC + gas fees"
echo ""
read -p "Do you want to continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Test cancelled."
    exit 0
fi

echo ""
echo "Please provide your wallet credentials for testing:"
echo "(These will only be used for this test session and not saved)"
echo ""

# Prompt for credentials
read -p "BASE_RPC_URL: " rpc_url
read -p "BACKEND_WALLET_ADDRESS: " wallet_address
read -sp "BACKEND_WALLET_PRIVATE_KEY: " private_key
echo ""

# Validate inputs
if [ -z "$rpc_url" ] || [ -z "$wallet_address" ] || [ -z "$private_key" ]; then
    echo "❌ Error: All credentials are required"
    exit 1
fi

echo ""
echo "✓ Credentials provided"
echo "✓ Wallet: $wallet_address"
echo ""

# Export environment variables (only for this shell session)
export BASE_RPC_URL="$rpc_url"
export BACKEND_WALLET_ADDRESS="$wallet_address"
export BACKEND_WALLET_PRIVATE_KEY="$private_key"
export USDC_CONTRACT_ADDRESS="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
export PAYMENT_VERIFICATION_MODE="simple"  # Use simple mode for testing
export REQUIRE_CLAIM_AUTHENTICATION="false"  # Disable claim auth for testing
export ENV="development"  # Use development mode

echo "Starting E2E test..."
echo ""

# Run the test
python3 test_e2e_real.py

# Capture exit code
test_result=$?

# Cleanup (unset sensitive variables)
unset BASE_RPC_URL
unset BACKEND_WALLET_PRIVATE_KEY
unset BACKEND_WALLET_ADDRESS

echo ""
if [ $test_result -eq 0 ]; then
    echo "✅ Test completed successfully!"
else
    echo "❌ Test failed with exit code: $test_result"
fi

exit $test_result
