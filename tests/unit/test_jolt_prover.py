"""
Tests for Jolt Atlas prover binary requirement.
Tests for the Jolt Atlas proof client.
"""
import os
import pytest
from unittest.mock import patch


class TestJoltProverBinaryRequired:
    def test_missing_binary_raises_error(self):
        """Without a binary, JoltProofClient should raise RuntimeError."""
        with patch("proof_client.os.path.exists", return_value=False):
            from proof_client import JoltProofClient
            with pytest.raises(RuntimeError, match="binary not found"):
                JoltProofClient(binary_path="/nonexistent/path")

    def test_non_executable_binary_raises_error(self):
        """Binary exists but not executable should raise RuntimeError."""
        with patch("proof_client.os.path.exists", return_value=True), \
             patch("proof_client.os.access", return_value=False):
            from proof_client import JoltProofClient
            with pytest.raises(RuntimeError, match="not executable"):
                JoltProofClient(binary_path="/some/path")

    def test_valid_binary_initializes(self):
        """With a valid binary, JoltProofClient should initialize."""
        with patch("proof_client.os.path.exists", return_value=True), \
             patch("proof_client.os.access", return_value=True):
            from proof_client import JoltProofClient
            client = JoltProofClient(binary_path="./jolt-atlas/jolt_claims_prover")
            assert client.binary_path == "./jolt-atlas/jolt_claims_prover"

    def test_proof_system_is_jolt_atlas(self):
        """Proof output should use jolt-atlas-snark proof system."""
        with patch("proof_client.os.path.exists", return_value=True), \
             patch("proof_client.os.access", return_value=True):
            from proof_client import JoltProofClient
            client = JoltProofClient(binary_path="./jolt-atlas/jolt_claims_prover")

            proof_b64, public_inputs, gen_time = client.generate_proof(
                http_status=503, http_body="", http_headers={}
            )

            assert proof_b64  # base64 string, not hex
            assert public_inputs[0] == 1  # is_failure
            assert public_inputs[1] == 503

            proof_data = client.get_last_proof_data()
            assert proof_data["proof_system"] == "jolt-atlas-snark"
            assert proof_data["model_hash"]
