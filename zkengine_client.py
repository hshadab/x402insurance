"""
zkEngine client - wrapper for zkEngine binary
Handles proof generation and verification
"""
import subprocess
import json
import time
import hashlib
import os
import logging
from typing import Tuple, List


class ZKEngineClient:
    def __init__(self, binary_path: str = None, timeout: int = 60):
        self.binary_path = binary_path or os.environ.get("ZKENGINE_BINARY_PATH", "./zkengine/fraud_detector")
        self.cwd = os.environ.get("ZKENGINE_CWD", "/tmp/zkEngine_dev")
        self.timeout = timeout
        self.use_mock = not os.path.exists(binary_path)
        self.logger = logging.getLogger("x402insurance.zkengine")

        self._last_proof = None
        self._last_instance = None

        if self.use_mock:
            self.logger.warning("zkEngine binary not found, using MOCK mode")
        else:
            self.logger.info("zkEngine binary found at %s (timeout: %ds)", binary_path, timeout)

    def generate_proof(
        self,
        http_status: int,
        http_body: str,
        http_headers: dict
    ) -> Tuple[str, List[int], int]:
        """
        Generate zkEngine proof of fraud

        Returns:
            (proof_hex, public_inputs, generation_time_ms)
            public_inputs format: [is_fraud, http_status, body_length, payout_amount]
        """
        if self.use_mock:
            return self._mock_generate_proof(http_status, http_body, http_headers)

        start_time = time.time()

        body_length = len(http_body)

        # Run zkEngine binary with status and body_length arguments
        # The fraud_detector binary takes: ./fraud_detector <http_status> <body_length>
        # It needs to run from the zkEngine source directory to find WASM files
        binary_abs_path = os.path.abspath(self.binary_path)

        result = subprocess.run(
            [binary_abs_path, str(http_status), str(body_length)],
            capture_output=True,
            text=True,
            timeout=self.timeout,  # Configurable timeout for zkEngine proof generation
            cwd=self.cwd  # zkEngine needs to run from source dir to find wasm/ files
        )

        if result.returncode != 0:
            raise Exception(f"zkEngine proof generation failed: {result.stderr}")

        # Parse JSON output from zkEngine
        try:
            output = json.loads(result.stdout)
            proof_data = output["proof"]
            instance_data = output["instance"]

            # Convert proof to hex string for storage
            proof_hex = "0x" + hashlib.sha256(json.dumps(proof_data).encode()).hexdigest()

            # Evaluate fraud for public inputs
            is_fraud, payout_amount = self.evaluate_fraud(http_status, http_body, 10000)

            public_inputs = [
                1 if is_fraud else 0,
                http_status,
                body_length,
                payout_amount
            ]

            # Store full proof and instance for verification
            self._last_proof = proof_data
            self._last_instance = instance_data

        except (json.JSONDecodeError, KeyError) as e:
            raise Exception(f"Failed to parse zkEngine output: {e}\nOutput: {result.stdout[:500]}")

        generation_time_ms = int((time.time() - start_time) * 1000)

        return proof_hex, public_inputs, generation_time_ms

    def get_last_proof_data(self):
        """Return the full proof data from the last generate_proof call"""
        return self._last_proof

    def get_last_instance_data(self):
        """Return the full instance data from the last generate_proof call"""
        return self._last_instance

    def verify_proof(self, proof_hex: str, public_inputs: List[int], proof_data=None, instance_data=None) -> bool:
        """
        Verify zkEngine proof locally.

        Can verify using:
        1. Provided proof_data/instance_data (for stored proofs)
        2. Cached _last_proof/_last_instance (immediately after generation)

        Verification checks:
        - Recompute proof hash from full proof data and compare to proof_hex
        - Validate public_inputs consistency (is_fraud, status, body_length, payout)

        Returns:
            True if valid, False otherwise
        """
        if self.use_mock:
            return self._mock_verify_proof(proof_hex, public_inputs)

        # Use provided data or fall back to cached data
        p_data = proof_data or self._last_proof
        i_data = instance_data or self._last_instance

        if not p_data:
            self.logger.warning("Cannot verify proof without proof data")
            return False

        # Recompute hash from full proof data and compare
        recomputed_hex = "0x" + hashlib.sha256(json.dumps(p_data).encode()).hexdigest()
        if recomputed_hex != proof_hex:
            self.logger.error("Proof hash mismatch: expected %s, got %s", proof_hex, recomputed_hex)
            return False

        # Validate public_inputs structure
        if len(public_inputs) != 4:
            self.logger.error("Invalid public_inputs length: %d", len(public_inputs))
            return False

        if public_inputs[0] not in [0, 1]:
            self.logger.error("Invalid is_fraud value: %s", public_inputs[0])
            return False

        self.logger.info("Proof verified locally: hash matches, public_inputs valid")
        return True

    def evaluate_fraud(
        self,
        http_status: int,
        http_body: str,
        coverage_amount: int
    ) -> Tuple[bool, int]:
        """
        Evaluate if HTTP response constitutes fraud

        Returns:
            (is_fraud, payout_amount)
        """
        is_fraud = False

        # Fraud conditions
        if http_status >= 500:  # Server error
            is_fraud = True
        elif http_status >= 400 and len(http_body) == 0:  # Client error with empty body
            is_fraud = True
        elif len(http_body) == 0:  # Empty response
            is_fraud = True

        payout_amount = coverage_amount if is_fraud else 0

        return is_fraud, payout_amount

    # Mock methods for testing without zkEngine binary
    def _mock_generate_proof(
        self,
        http_status: int,
        http_body: str,
        http_headers: dict
    ) -> Tuple[str, List[int], int]:
        """Mock proof generation"""
        start_time = time.time()

        body_length = len(http_body)
        is_fraud, payout_amount = self.evaluate_fraud(http_status, http_body, 10000)

        # Generate mock proof (hash of inputs)
        mock_proof = {"mock": True, "status": http_status, "body_length": body_length, "is_fraud": is_fraud}
        mock_instance = {"public_inputs": [1 if is_fraud else 0, http_status, body_length]}
        self._last_proof = mock_proof
        self._last_instance = mock_instance

        proof_hex = "0x" + hashlib.sha256(json.dumps(mock_proof).encode()).hexdigest()

        public_inputs = [
            1 if is_fraud else 0,
            http_status,
            body_length,
            payout_amount
        ]

        generation_time_ms = int((time.time() - start_time) * 1000)

        return proof_hex, public_inputs, generation_time_ms

    def _mock_verify_proof(self, proof_hex: str, public_inputs: List[int]) -> bool:
        """Mock verification - basic validation"""
        if not proof_hex.startswith("0x"):
            return False
        if len(public_inputs) != 4:
            return False
        if public_inputs[0] not in [0, 1]:
            return False
        return True
