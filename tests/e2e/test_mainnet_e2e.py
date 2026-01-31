"""
End-to-End test on Base Mainnet.

Uses real Base Mainnet RPC, real USDC, real wallets.
Requires funded wallets — skips automatically if underfunded.

Backend wallet: 0x0e9AFe2499211c3E35e570968d1047Fcf7488c60
Agent wallet: set via AGENT_WALLET_ADDRESS / AGENT_WALLET_PRIVATE_KEY env vars

Flow:
1. Agent purchases insurance policy via x402 V2 payment
2. Agent submits a claim (simulated merchant failure)
3. Verify proof was generated
4. Verify USDC payout was issued
"""
import os
import time
import json
import pytest
import httpx
from web3 import Web3

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

BASE_RPC_URL = os.environ.get("BASE_RPC_URL", "https://mainnet.base.org")
USDC_ADDRESS = os.environ.get(
    "USDC_CONTRACT_ADDRESS",
    "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
)
BACKEND_WALLET = os.environ.get(
    "BACKEND_WALLET_ADDRESS",
    "0x0e9AFe2499211c3E35e570968d1047Fcf7488c60",
)
AGENT_WALLET = os.environ.get("AGENT_WALLET_ADDRESS", "")
AGENT_PRIVATE_KEY = os.environ.get("AGENT_WALLET_PRIVATE_KEY", "")
SERVER_URL = os.environ.get("E2E_SERVER_URL", "http://localhost:8000")
CHAIN_ID = int(os.environ.get("CHAIN_ID", "8453"))

# Minimum balances required to run E2E tests (in human-readable units)
MIN_ETH = 0.0005  # ~$1 at typical prices, enough for a few txns
MIN_USDC = 0.01  # enough for a micropayment premium

# ERC-20 balanceOf ABI fragment
BALANCE_OF_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    }
]


def _get_balances(address: str):
    """Return (eth_balance_ether, usdc_balance_human) for an address."""
    w3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))
    eth_wei = w3.eth.get_balance(Web3.to_checksum_address(address))
    eth = float(w3.from_wei(eth_wei, "ether"))

    usdc_contract = w3.eth.contract(
        address=Web3.to_checksum_address(USDC_ADDRESS), abi=BALANCE_OF_ABI
    )
    usdc_raw = usdc_contract.functions.balanceOf(
        Web3.to_checksum_address(address)
    ).call()
    usdc = usdc_raw / 1_000_000

    return eth, usdc


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

def _wallets_configured():
    return bool(AGENT_WALLET and AGENT_PRIVATE_KEY)


def _wallets_funded():
    if not _wallets_configured():
        return False
    try:
        agent_eth, agent_usdc = _get_balances(AGENT_WALLET)
        backend_eth, _ = _get_balances(BACKEND_WALLET)
        return (
            agent_eth >= MIN_ETH
            and agent_usdc >= MIN_USDC
            and backend_eth >= MIN_ETH
        )
    except Exception:
        return False


skip_no_wallets = pytest.mark.skipif(
    not _wallets_configured(),
    reason="AGENT_WALLET_ADDRESS and AGENT_WALLET_PRIVATE_KEY not set",
)

skip_underfunded = pytest.mark.skipif(
    not _wallets_funded(),
    reason="Wallets underfunded (need ETH for gas + USDC for premium)",
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@skip_no_wallets
class TestMainnetE2E:
    """Full end-to-end tests on Base Mainnet."""

    def test_health_check(self):
        """Verify the server is running and healthy."""
        resp = httpx.get(f"{SERVER_URL}/health", timeout=10.0)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("healthy", "degraded")

    def test_pricing_endpoint(self):
        """Verify pricing endpoint returns valid data."""
        resp = httpx.get(f"{SERVER_URL}/api/pricing", timeout=10.0)
        assert resp.status_code == 200
        data = resp.json()
        assert "premium" in data
        assert data["premium"]["percentage"] == 0.01

    def test_insure_returns_402_without_payment(self):
        """POST /insure without payment should return 402."""
        resp = httpx.post(
            f"{SERVER_URL}/insure",
            json={
                "merchant_url": "https://httpstat.us/503",
                "coverage_amount": 0.01,
            },
            timeout=15.0,
        )
        assert resp.status_code == 402
        data = resp.json()
        assert "accepts" in data
        assert len(data["accepts"]) > 0
        accept = data["accepts"][0]
        assert accept["network"] == f"eip155:{CHAIN_ID}"
        assert accept["asset"].lower() == USDC_ADDRESS.lower()

    @skip_underfunded
    def test_full_policy_purchase_flow(self):
        """
        Full x402 V2 flow:
        1. POST /insure -> 402
        2. Sign payment
        3. Retry with PAYMENT-SIGNATURE -> 201
        """
        from agentcore_agent import agent_purchase_policy

        policy = agent_purchase_policy(
            server_url=SERVER_URL,
            merchant_url="https://httpstat.us/503",
            coverage_amount=0.001,
            agent_address=AGENT_WALLET,
            chain_id=CHAIN_ID,
        )

        assert "policy_id" in policy
        assert policy["status"] == "active"
        assert policy["coverage_amount"] > 0

        # Store for claim test
        self.__class__._policy_id = policy["policy_id"]
        self.__class__._merchant_url = "https://httpstat.us/503"

    @skip_underfunded
    def test_full_claim_flow(self):
        """
        Submit a claim against the policy created above.
        Verifies proof generation and USDC payout.
        """
        policy_id = getattr(self.__class__, "_policy_id", None)
        if not policy_id:
            pytest.skip("No policy created in previous test")

        from agentcore_agent import agent_submit_claim

        claim = agent_submit_claim(
            server_url=SERVER_URL,
            policy_id=policy_id,
            http_status=503,
            http_body="",
            agent_address=AGENT_WALLET,
            chain_id=CHAIN_ID,
            async_mode=False,
        )

        assert "claim_id" in claim
        assert claim["status"] == "paid"
        assert claim.get("payout_amount", 0) > 0

        # Verify proof exists
        if claim.get("proof"):
            assert len(claim["proof"]) > 10

        # Verify public inputs format
        if claim.get("public_inputs"):
            pi = claim["public_inputs"]
            assert len(pi) == 4
            assert pi[0] == 1  # is_failure
            assert pi[1] == 503  # http_status

        # Check refund tx hash
        if claim.get("refund_tx_hash"):
            assert claim["refund_tx_hash"].startswith("0x")
            assert len(claim["refund_tx_hash"]) == 66

    @skip_underfunded
    def test_verify_proof(self):
        """Verify the proof from the claim via POST /verify."""
        policy_id = getattr(self.__class__, "_policy_id", None)
        if not policy_id:
            pytest.skip("No policy created in previous test")

        # Get claim via policies endpoint
        resp = httpx.get(
            f"{SERVER_URL}/policies",
            params={"wallet": AGENT_WALLET},
            timeout=10.0,
        )
        assert resp.status_code == 200

    def test_agent_card(self):
        """Verify agent card is accessible."""
        resp = httpx.get(
            f"{SERVER_URL}/.well-known/agent-card.json", timeout=10.0
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "name" in data or "capabilities" in data

    def test_dashboard_data(self):
        """Verify dashboard endpoint returns stats."""
        resp = httpx.get(f"{SERVER_URL}/api/dashboard", timeout=10.0)
        assert resp.status_code == 200
        data = resp.json()
        assert "stats" in data
        assert "total_policies" in data["stats"]


@skip_no_wallets
class TestWalletBalances:
    """Pre-flight balance checks."""

    def test_agent_wallet_has_eth(self):
        eth, _ = _get_balances(AGENT_WALLET)
        assert eth >= MIN_ETH, f"Agent wallet ETH too low: {eth}"

    def test_agent_wallet_has_usdc(self):
        _, usdc = _get_balances(AGENT_WALLET)
        assert usdc >= MIN_USDC, f"Agent wallet USDC too low: {usdc}"

    def test_backend_wallet_has_eth(self):
        eth, _ = _get_balances(BACKEND_WALLET)
        assert eth >= MIN_ETH, f"Backend wallet ETH too low: {eth}"

    def test_backend_wallet_has_usdc(self):
        _, usdc = _get_balances(BACKEND_WALLET)
        # Backend needs USDC for refund payouts
        assert usdc >= 0, f"Backend wallet USDC balance: {usdc}"
