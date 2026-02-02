"""
E2E test: real Jolt Atlas prover binary proof generation and verification.

Requires:
  - jolt-atlas/jolt_claims_prover binary present
  - models/claim_classifier.onnx model present

Run:
  pytest tests/e2e/test_real_proofs.py -v
"""
import os
import time
import json
import pytest

# Skip entire module if binary not available
BINARY_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'jolt-atlas', 'jolt_claims_prover')
BINARY_EXISTS = os.path.exists(BINARY_PATH)

pytestmark = pytest.mark.skipif(
    not BINARY_EXISTS,
    reason="Jolt prover binary not found at jolt-atlas/jolt_claims_prover"
)


@pytest.fixture(scope="module")
def app():
    """Create app with real Jolt Atlas prover."""
    os.environ.setdefault("JOLT_BINARY_PATH", "./jolt-atlas/jolt_claims_prover")
    os.environ.setdefault("ONNX_MODEL_PATH", "./models/claim_classifier.onnx")
    os.environ.setdefault("BACKEND_WALLET_ADDRESS", "0xf36B80afFb2e41418874FfA56B069f1Fe671FC35")
    os.environ.setdefault("ENV", "testing")

    from app import create_app
    app = create_app("testing")
    return app


@pytest.fixture(scope="module")
def client(app):
    return app.test_client()


@pytest.fixture(scope="module")
def proof_client():
    from core.proof_client import JoltProofClient
    return JoltProofClient(
        binary_path="./jolt-atlas/jolt_claims_prover",
        timeout=120,
        model_path="./models/claim_classifier.onnx",
    )


class TestRealProofGeneration:
    """Test real SNARK proof generation with the Jolt Atlas binary."""

    def test_failure_proof_503_empty_body(self, proof_client):
        """503 + empty body should produce failure proof."""
        start = time.time()
        proof_b64, public_inputs, gen_time_ms = proof_client.generate_proof(
            http_status=503, http_body="", http_headers={}
        )
        elapsed = time.time() - start

        assert proof_b64  # base64 string
        assert public_inputs[0] == 1, "is_failure should be 1"
        assert public_inputs[1] == 503, "http_status should be 503"
        assert public_inputs[2] == 0, "body_length should be 0"
        assert public_inputs[3] > 0, "payout should be > 0"
        assert gen_time_ms > 0, "generation time should be recorded"

        # Verify proof metadata
        proof_data = proof_client.get_last_proof_data()
        assert proof_data is not None
        assert proof_data["proof_system"] == "jolt-atlas-snark"
        assert proof_data["model_hash"]

        print(f"\nProof generated in {elapsed:.1f}s ({gen_time_ms}ms)")
        print(f"Proof (b64): {proof_b64[:40]}...")
        print(f"Public inputs: {public_inputs}")
        print(f"Model hash: {proof_data['model_hash'][:16]}...")

    def test_no_failure_200_with_body(self, proof_client):
        """200 + non-empty body should produce no-failure proof."""
        proof_b64, public_inputs, gen_time_ms = proof_client.generate_proof(
            http_status=200, http_body='{"data": "ok"}', http_headers={}
        )

        assert public_inputs[0] == 0, "is_failure should be 0"
        assert public_inputs[1] == 200, "http_status should be 200"
        assert public_inputs[2] > 0, "body_length should be > 0"
        assert public_inputs[3] == 0, "payout should be 0"

    def test_failure_proof_500(self, proof_client):
        """500 status should produce failure proof regardless of body."""
        proof_b64, public_inputs, _ = proof_client.generate_proof(
            http_status=500, http_body="Internal Server Error", http_headers={}
        )

        assert public_inputs[0] == 1, "is_failure should be 1 for 500"
        assert public_inputs[3] > 0, "payout should be > 0"


class TestRealProofVerification:
    """Test proof verification with real proof data."""

    def test_verify_valid_proof(self, proof_client):
        """Generated proof should verify successfully."""
        proof_b64, public_inputs, _ = proof_client.generate_proof(
            http_status=503, http_body="", http_headers={}
        )

        is_valid = proof_client.verify_proof(proof_b64, public_inputs)
        assert is_valid, "Real proof should verify"

    def test_verify_tampered_proof_rejected(self, proof_client):
        """Tampered proof should be rejected."""
        proof_b64, public_inputs, _ = proof_client.generate_proof(
            http_status=503, http_body="", http_headers={}
        )

        # Tamper with the base64 proof
        tampered = proof_b64[:-4] + "XXXX"
        is_valid = proof_client.verify_proof(tampered, public_inputs)
        assert not is_valid, "Tampered proof should not verify"


class TestVerifyEndpoint:
    """Test the /verify HTTP endpoint with real proofs."""

    def test_verify_endpoint_with_real_proof(self, client, proof_client):
        """POST /verify with real proof data should return valid=True."""
        proof_b64, public_inputs, _ = proof_client.generate_proof(
            http_status=502, http_body="", http_headers={}
        )
        proof_data = proof_client.get_last_proof_data()
        instance_data = proof_client.get_last_instance_data()

        resp = client.post('/verify', json={
            "proof": proof_b64,
            "public_inputs": public_inputs,
            "proof_data": proof_data,
            "instance_data": instance_data,
        })

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["valid"] is True
        assert data["failure_detected"] is True
        assert data["payout_amount"] > 0
