"""
Jolt Atlas proof client — wrapper for jolt_claims_prover binary.
Handles SNARK proof generation and verification via ONNX model inference.
"""
import subprocess
import json
import base64
import time
import hashlib
import os
import tempfile
import logging
from typing import Tuple, List


class JoltProofClient:
    def __init__(self, binary_path: str = None, timeout: int = 60, model_path: str = None):
        self.binary_path = binary_path or os.environ.get(
            "JOLT_BINARY_PATH", "./jolt-atlas/jolt_claims_prover"
        )
        self.timeout = timeout
        self.model_path = model_path or os.environ.get(
            "ONNX_MODEL_PATH", "./models/claim_classifier.onnx"
        )
        self.logger = logging.getLogger("x402insurance.jolt")

        self._last_proof = None
        self._last_instance = None

        if not os.path.exists(self.binary_path):
            raise RuntimeError(
                f"Jolt prover binary not found at {self.binary_path}. "
                "Build it with: cd jolt-prover && cargo build --release"
            )

        if not os.access(self.binary_path, os.X_OK):
            raise RuntimeError(
                f"Jolt prover binary at {self.binary_path} is not executable. "
                "Run: chmod +x " + self.binary_path
            )

        self.logger.info(
            "Jolt Atlas prover binary found at %s (timeout: %ds)",
            self.binary_path, timeout
        )

        # Compute model hash at startup for health checks
        self._model_hash = self._compute_model_hash()

    def _extract_json_from_output(self, stdout: str) -> dict:
        """Extract JSON object from binary stdout that may contain debug lines."""
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith('{'):
                return json.loads(line)
        raise ValueError(f"No JSON found in output: {stdout[:500]}")

    def _compute_model_hash(self) -> str:
        """Compute SHA-256 hash of the ONNX model file."""
        try:
            with open(self.model_path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except FileNotFoundError:
            self.logger.warning("ONNX model not found at %s", self.model_path)
            return ""

    @property
    def model_hash(self) -> str:
        return self._model_hash

    def generate_proof(
        self,
        http_status: int,
        http_body: str,
        http_headers: dict,
        coverage_amount_units: int = 10000
    ) -> Tuple[str, List[int], int]:
        """
        Generate Jolt Atlas SNARK proof of claim classification.

        Returns:
            (proof_b64, public_inputs, generation_time_ms)
            public_inputs format: [is_failure, http_status, body_length, payout_amount]
        """
        start_time = time.time()

        body_length = len(http_body)
        binary_abs_path = os.path.abspath(self.binary_path)

        env = os.environ.copy()
        env["ONNX_MODEL_PATH"] = os.path.abspath(self.model_path)

        result = subprocess.run(
            [binary_abs_path, str(http_status), str(body_length), str(coverage_amount_units)],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            env=env
        )

        if result.returncode != 0:
            raise Exception(f"Jolt proof generation failed: {result.stderr}")

        try:
            output = self._extract_json_from_output(result.stdout)
            proof_b64 = output["proof"]
            public_inputs = output["public_inputs"]
            model_hash = output["model_hash"]
            proof_system = output["proof_system"]
            proving_time_ms = output.get("proving_time_ms", 0)

            # program_io is the serialized Jolt execution trace (required for verification)
            program_io_b64 = output.get("program_io", "")
            proof_size_bytes = output.get("proof_size_bytes", 0)

            self._last_proof = {
                "proof": proof_b64,
                "program_io": program_io_b64,
                "public_inputs": public_inputs,
                "model_hash": model_hash,
                "proof_system": proof_system,
                "proof_size_bytes": proof_size_bytes,
            }
            self._last_instance = {
                "http_status": http_status,
                "body_length": body_length,
                "model_hash": model_hash,
            }

        except (json.JSONDecodeError, KeyError) as e:
            raise Exception(
                f"Failed to parse Jolt prover output: {e}\nOutput: {result.stdout[:500]}"
            )

        generation_time_ms = int((time.time() - start_time) * 1000)

        return proof_b64, public_inputs, generation_time_ms

    def get_last_proof_data(self):
        return self._last_proof

    def get_last_instance_data(self):
        return self._last_instance

    def verify_proof(
        self, proof: str, public_inputs: List[int],
        proof_data=None, instance_data=None
    ) -> bool:
        """Verify Jolt Atlas SNARK proof via the prover binary."""
        resolved_proof_data = proof_data or self._last_proof

        if not resolved_proof_data:
            self.logger.warning("Cannot verify proof without proof data")
            return False

        if len(public_inputs) != 4:
            self.logger.error("Invalid public_inputs length: %d", len(public_inputs))
            return False

        if public_inputs[0] not in [0, 1]:
            self.logger.error("Invalid is_failure value: %s", public_inputs[0])
            return False

        # Build proof JSON for the binary verifier (includes program_io for real SNARK verification)
        verify_payload = {
            "proof": proof,
            "program_io": resolved_proof_data.get("program_io", ""),
            "public_inputs": public_inputs,
            "model_hash": resolved_proof_data.get("model_hash", self._model_hash),
            "proof_system": resolved_proof_data.get("proof_system", "jolt-atlas-snark"),
        }

        tmpfile = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.json', delete=False
            ) as f:
                json.dump(verify_payload, f)
                tmpfile = f.name

            binary_abs_path = os.path.abspath(self.binary_path)

            env = os.environ.copy()
            env["ONNX_MODEL_PATH"] = os.path.abspath(self.model_path)

            result = subprocess.run(
                [binary_abs_path, "--verify", tmpfile],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env
            )

            if result.returncode != 0:
                self.logger.error("Jolt verify failed: %s", result.stderr)
                return False

            output = self._extract_json_from_output(result.stdout)
            is_valid = output.get("valid", False)

            if is_valid:
                self.logger.info("Jolt Atlas SNARK proof verified successfully")
            else:
                self.logger.error("Jolt Atlas SNARK proof verification failed")

            return is_valid

        except Exception as e:
            self.logger.error("Proof verification error: %s", e)
            return False
        finally:
            if tmpfile:
                try:
                    os.unlink(tmpfile)
                except OSError:
                    pass

    # Payout cap check (called by verify endpoint)
    def check_payout_cap(self, public_inputs: List[int]) -> bool:
        """Check that payout does not exceed max coverage."""
        from flask import current_app
        max_coverage = current_app.config.get("MAX_COVERAGE_USDC", 0.1)
        max_payout = int(max_coverage * 1_000_000)
        payout_amount = public_inputs[3] if len(public_inputs) > 3 else 0
        if payout_amount > max_payout:
            self.logger.error(
                "Payout %d exceeds max coverage %d", payout_amount, max_payout
            )
            return False
        return True
