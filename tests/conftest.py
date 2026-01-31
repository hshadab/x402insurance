"""
Shared test fixtures for x402 Insurance tests.

Tests mock external infrastructure only:
- Blockchain RPC (web3 calls)
- x402.org facilitator HTTP API
- Jolt Atlas prover binary (subprocess)
"""
import os
import json
import base64
import hashlib
import tempfile
import subprocess
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from pathlib import Path

# Set testing env before imports
os.environ["ENV"] = "testing"

# Required env vars (real code now demands these)
os.environ["BACKEND_WALLET_PRIVATE_KEY"] = "0x" + "ab" * 32  # fake but valid format
os.environ["BACKEND_WALLET_ADDRESS"] = "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0"
os.environ["JOLT_BINARY_PATH"] = "/tmp/jolt_claims_prover"  # placeholder, patched in fixture
os.environ["ONNX_MODEL_PATH"] = "./models/claim_classifier.onnx"
os.environ["FACILITATOR_URL"] = "https://x402.org/facilitator"
os.environ["HUEY_IMMEDIATE"] = "true"


def _make_jolt_proof_output(http_status, body_length):
    """Generate realistic Jolt Atlas prover binary stdout."""
    is_failure = 1 if (500 <= http_status <= 504 or body_length == 0) else 0
    payout_amount = 10000 if is_failure else 0

    # Build a fake but structurally correct base64 proof
    proof_bytes = hashlib.sha256(
        f"jolt-proof:{http_status}:{body_length}".encode()
    ).digest() * 2  # 64 bytes
    proof_b64 = base64.b64encode(proof_bytes).decode()

    # program_io mimics serialized Jolt ProgramIO (base64-encoded JSON)
    program_io_json = json.dumps({"inputs": [http_status, body_length], "outputs": [is_failure]})
    program_io_b64 = base64.b64encode(program_io_json.encode()).decode()

    return json.dumps({
        "proof": proof_b64,
        "program_io": program_io_b64,
        "public_inputs": [is_failure, http_status, body_length, payout_amount],
        "model_hash": "a" * 64,
        "proof_system": "jolt-atlas-snark",
        "proving_time_ms": 100,
        "proof_size_bytes": 128,
    })


def _make_jolt_verify_output():
    """Generate realistic Jolt Atlas verify output."""
    return json.dumps({"valid": True})


_original_subprocess_run = subprocess.run


def _mock_subprocess_run(*args, **kwargs):
    """Mock subprocess.run to simulate Jolt prover binary, pass through other calls."""
    cmd_args = args[0] if args else kwargs.get("args", [])
    is_jolt = (
        isinstance(cmd_args, (list, tuple)) and len(cmd_args) >= 2
        and (
            "jolt_claims_prover" in str(cmd_args[0])
            or "jolt-atlas" in str(cmd_args[0]).lower()
        )
    )
    if is_jolt:
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""

        if len(cmd_args) >= 2 and cmd_args[1] == "--verify":
            result.stdout = _make_jolt_verify_output()
        elif len(cmd_args) >= 3:
            http_status = int(cmd_args[1])
            body_length = int(cmd_args[2])
            result.stdout = _make_jolt_proof_output(http_status, body_length)
        else:
            result.stdout = _make_jolt_proof_output(200, 100)
        return result
    return _original_subprocess_run(*args, **kwargs)


# Monkeypatch subprocess.run at module level so it's active for ALL imports
subprocess.run = _mock_subprocess_run

# Also save originals for os.path.exists and os.access
_original_exists = os.path.exists
_original_access = os.access


def _patched_exists(path):
    if "jolt_claims_prover" in str(path) or "jolt-atlas" in str(path):
        return True
    return _original_exists(path)


def _patched_access(path, mode):
    if "jolt_claims_prover" in str(path) or "jolt-atlas" in str(path):
        return True
    return _original_access(path, mode)


@pytest.fixture(autouse=True)
def _patch_external_services():
    """
    Patch external infrastructure so tests exercise real internal code
    but don't require a blockchain node, facilitator, or Jolt binary.
    """
    with patch("proof_client.os.path.exists", side_effect=_patched_exists), \
         patch("proof_client.os.access", side_effect=_patched_access):

        with patch("blockchain.Web3") as MockWeb3:
            mock_w3 = MagicMock()
            MockWeb3.return_value = mock_w3
            MockWeb3.HTTPProvider.return_value = MagicMock()
            MockWeb3.to_checksum_address = lambda addr: addr

            mock_account = MagicMock()
            mock_account.address = os.environ["BACKEND_WALLET_ADDRESS"]
            mock_account.key = b"\xab" * 32
            mock_w3.eth.account.from_key.return_value = mock_account
            mock_w3.eth.contract.return_value = MagicMock()
            mock_w3.eth.get_balance.return_value = 10**18
            mock_w3.eth.gas_price = 1_000_000_000
            mock_w3.eth.chain_id = 84532
            mock_w3.eth.get_transaction_count.return_value = 0
            mock_w3.to_wei = lambda val, unit: int(val * 10**18) if unit == 'ether' else int(val * 10**9)
            mock_w3.from_wei = lambda val, unit: val / 10**18 if unit == 'ether' else val / 10**9

            mock_balance_fn = MagicMock()
            mock_balance_fn.call.return_value = 100_000_000
            mock_contract = MagicMock()
            mock_contract.functions.balanceOf.return_value = mock_balance_fn
            mock_contract.functions.transfer.return_value.build_transaction.return_value = {
                "from": mock_account.address, "nonce": 0, "gas": 100000,
                "gasPrice": 1_000_000_000, "chainId": 84532
            }
            mock_w3.eth.contract.return_value = mock_contract

            mock_tx_hash = bytes.fromhex("a" * 64)
            mock_w3.eth.send_raw_transaction.return_value = mock_tx_hash
            mock_receipt = MagicMock()
            mock_receipt.status = 1
            mock_w3.eth.wait_for_transaction_receipt.return_value = mock_receipt

            mock_signed = MagicMock()
            mock_signed.raw_transaction = b"\x00" * 100
            mock_w3.eth.account.sign_transaction.return_value = mock_signed

            with patch("blueprints.claims.httpx.get") as mock_httpx_get, \
                 patch("auth.payment_verifier.httpx.post") as mock_httpx:
                # Mock server-side re-fetch: return 503 to match agent-reported failures
                mock_server_resp = MagicMock()
                mock_server_resp.status_code = 503
                mock_httpx_get.return_value = mock_server_resp
                def mock_facilitator_post(url, **kwargs):
                    resp = MagicMock()
                    resp.status_code = 200
                    if "/verify" in url:
                        resp.json.return_value = {
                            "isValid": True,
                            "payer": os.environ["BACKEND_WALLET_ADDRESS"],
                        }
                    elif "/settle" in url:
                        resp.json.return_value = {
                            "success": True,
                            "transaction": "0x" + "bb" * 32,
                        }
                    else:
                        resp.status_code = 404
                        resp.text = "Not found"
                    return resp

                mock_httpx.side_effect = mock_facilitator_post

                yield


@pytest.fixture
def app():
    """Create application for testing."""
    from app import create_app
    app = create_app("testing")
    app.config["TESTING"] = True
    yield app


@pytest.fixture
def client(app):
    """Test client."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Test CLI runner."""
    return app.test_cli_runner()
