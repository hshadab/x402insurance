"""
x402 Payment Verification Module (V2)

Handles verification of x402 payments including:
- V2: Facilitator-based verification and settlement via x402.org
- V2: Base64-encoded JSON PaymentPayload parsing
- V1 (fallback): EIP-712 signature verification
- Timestamp/expiry validation
- Replay attack prevention (via database-backed nonce storage)
- Amount verification
"""
from eth_account import Account
try:
    from eth_account.messages import encode_typed_data as encode_structured_data
except ImportError:
    from eth_account.messages import encode_structured_data
from web3 import Web3
import base64
import time
import json
import logging
import httpx
from typing import Optional, Dict
from dataclasses import dataclass

logger = logging.getLogger("x402insurance.payment_verifier")


@dataclass
class PaymentDetails:
    """Verified payment details"""
    payer: str
    amount_units: int
    asset: str
    pay_to: str
    timestamp: int
    nonce: str
    signature: str
    is_valid: bool
    settlement_tx: Optional[str] = None


class FacilitatorPaymentVerifier:
    """
    x402 V2 Payment Verifier using facilitator API.

    Delegates verification and settlement to a facilitator endpoint
    (e.g. https://x402.org/facilitator).
    """

    def __init__(
        self,
        backend_address: str,
        usdc_address: str,
        facilitator_url: str = "https://x402.org/facilitator",
        chain_id: int = 8453,
        database=None,
    ):
        self.backend_address = Web3.to_checksum_address(backend_address)
        self.usdc_address = Web3.to_checksum_address(usdc_address)
        self.facilitator_url = facilitator_url.rstrip("/")
        self.chain_id = chain_id
        self.caip2_network = f"eip155:{chain_id}"
        self._database = database
        self.cache_cleanup_interval = 3600
        self.last_cleanup = time.time()

        logger.info(
            "FacilitatorPaymentVerifier initialized (facilitator=%s, chain_id=%d)",
            self.facilitator_url, self.chain_id
        )

    @property
    def database(self):
        """Lazy access to database — allows ext.database to be set after init."""
        if self._database is not None:
            return self._database
        import extensions as ext
        return ext.database

    def verify_payment(
        self,
        payment_header: str,
        payer_address: Optional[str],
        required_amount: int,
        max_age_seconds: int = 300,
    ) -> PaymentDetails:
        """
        Verify x402 V2 payment via facilitator /verify endpoint.
        Falls back to V1 comma-separated parsing if base64 decode fails.
        """
        try:
            payment_payload = self._parse_v2_payment_header(payment_header)
            if payment_payload is None:
                payment_payload = self._parse_v1_payment_header(payment_header)

            if not payment_payload:
                return PaymentDetails(
                    payer="", amount_units=0, asset="", pay_to="",
                    timestamp=0, nonce="", signature="", is_valid=False
                )

            payment_requirements = {
                "scheme": "exact",
                "network": self.caip2_network,
                "maxAmountRequired": str(required_amount),
                "asset": self.usdc_address,
                "payTo": self.backend_address,
                "maxTimeoutSeconds": 60,
                "extra": {},
            }

            verify_result = self._call_facilitator_verify(
                payment_payload=payment_payload,
                payment_requirements=payment_requirements,
            )

            if not verify_result or not verify_result.get("isValid", False):
                payer = verify_result.get("payer", payer_address or "") if verify_result else (payer_address or "")
                logger.warning("Facilitator verification failed: %s", verify_result)
                return PaymentDetails(
                    payer=payer, amount_units=required_amount, asset=self.usdc_address,
                    pay_to=self.backend_address, timestamp=int(time.time()),
                    nonce="", signature="", is_valid=False
                )

            payer = verify_result.get("payer", payer_address or "")

            nonce = payment_payload.get("nonce", "") if isinstance(payment_payload, dict) else ""
            if nonce and self.database and self.database.is_nonce_used(payer, nonce):
                logger.warning("Nonce already used: payer=%s nonce=%s", payer, nonce)
                return PaymentDetails(
                    payer=payer, amount_units=required_amount, asset=self.usdc_address,
                    pay_to=self.backend_address, timestamp=int(time.time()),
                    nonce=nonce, signature="", is_valid=False
                )

            if nonce and self.database:
                self.database.mark_nonce_used(payer, nonce, int(time.time()))

            self._maybe_cleanup_nonces()

            logger.info("Payment verified via facilitator: payer=%s amount=%s", payer, required_amount)
            return PaymentDetails(
                payer=payer, amount_units=required_amount, asset=self.usdc_address,
                pay_to=self.backend_address, timestamp=int(time.time()),
                nonce=nonce, signature="", is_valid=True
            )

        except Exception as e:
            logger.exception("FacilitatorPaymentVerifier error: %s", e)
            return PaymentDetails(
                payer="", amount_units=0, asset="", pay_to="",
                timestamp=0, nonce="", signature="", is_valid=False
            )

    def settle_payment(
        self,
        payment_header: str,
        payment_requirements: dict,
    ) -> Optional[Dict]:
        """Call facilitator /settle to execute payment on-chain."""
        try:
            payment_payload = self._parse_v2_payment_header(payment_header)
            if payment_payload is None:
                payment_payload = self._parse_v1_payment_header(payment_header)

            if not payment_payload:
                return None

            response = httpx.post(
                f"{self.facilitator_url}/settle",
                json={
                    "paymentPayload": payment_payload,
                    "paymentRequirements": payment_requirements,
                },
                timeout=30.0,
            )

            if response.status_code == 200:
                result = response.json()
                logger.info("Payment settled: tx=%s", result.get("transaction"))
                return result
            else:
                logger.warning("Facilitator /settle failed: %s %s", response.status_code, response.text)
                return None

        except Exception as e:
            logger.exception("Settlement error: %s", e)
            return None

    def _call_facilitator_verify(self, payment_payload, payment_requirements) -> Optional[Dict]:
        """Call facilitator /verify endpoint."""
        try:
            response = httpx.post(
                f"{self.facilitator_url}/verify",
                json={
                    "paymentPayload": payment_payload,
                    "paymentRequirements": payment_requirements,
                },
                timeout=15.0,
            )

            if response.status_code == 200:
                return response.json()
            else:
                logger.warning("Facilitator /verify returned %s: %s", response.status_code, response.text)
                return None

        except Exception as e:
            logger.exception("Facilitator /verify error: %s", e)
            return None

    def _parse_v2_payment_header(self, payment_header: str) -> Optional[Dict]:
        """Parse V2 PAYMENT-SIGNATURE header (base64-encoded JSON)."""
        try:
            decoded = base64.b64decode(payment_header)
            payload = json.loads(decoded)
            if isinstance(payload, dict):
                return payload
            return None
        except (ValueError, json.JSONDecodeError):
            return None

    def _parse_v1_payment_header(self, payment_header: str) -> Optional[Dict]:
        """Parse V1 X-Payment header (comma-separated key=value)."""
        try:
            parts = {}
            for item in payment_header.split(","):
                if "=" in item:
                    key, value = item.split("=", 1)
                    parts[key.strip()] = value.strip()
            return parts if parts else None
        except (ValueError, AttributeError):
            return None

    def _maybe_cleanup_nonces(self):
        if time.time() - self.last_cleanup > self.cache_cleanup_interval:
            self.last_cleanup = time.time()
            if self.database:
                try:
                    self.database.cleanup_nonces()
                except Exception as e:
                    logger.warning("Nonce cleanup failed: %s", e)


class PaymentVerifier:
    """Verify x402 payments with proper EIP-712 signature validation (V1 fallback)"""

    def __init__(self, backend_address: str, usdc_address: str, chain_id: int = 8453, database=None):
        self.backend_address = Web3.to_checksum_address(backend_address)
        self.usdc_address = Web3.to_checksum_address(usdc_address)
        self.chain_id = chain_id
        self._database = database
        self.cache_cleanup_interval = 3600
        self.last_cleanup = time.time()
        logger.info(
            "PaymentVerifier initialized (chain_id: %d)", self.chain_id
        )

    @property
    def database(self):
        if self._database is not None:
            return self._database
        import extensions as ext
        return ext.database

    def verify_payment(
        self,
        payment_header: str,
        payer_address: Optional[str],
        required_amount: int,
        max_age_seconds: int = 300
    ) -> PaymentDetails:
        """Verify x402 payment from headers (V1 EIP-712 local verification)"""
        try:
            payment_data = self._parse_payment_header(payment_header)
            if not payment_data:
                return PaymentDetails(
                    payer="", amount_units=0, asset="", pay_to="",
                    timestamp=0, nonce="", signature="", is_valid=False
                )

            payer = payment_data.get('payer', payer_address or '')
            amount = int(payment_data.get('amount', 0))
            asset = payment_data.get('asset', self.usdc_address)
            pay_to = payment_data.get('payTo', self.backend_address)
            timestamp = int(payment_data.get('timestamp', 0))
            nonce = payment_data.get('nonce', '')
            signature = payment_data.get('signature', '')

            if not all([payer, amount, asset, pay_to, timestamp, nonce, signature]):
                logger.warning("Missing required payment fields")
                return PaymentDetails(
                    payer=payer, amount_units=amount, asset=asset, pay_to=pay_to,
                    timestamp=timestamp, nonce=nonce, signature=signature, is_valid=False
                )

            if amount != required_amount:
                logger.warning("Payment amount mismatch: provided=%s required=%s", amount, required_amount)
                return PaymentDetails(
                    payer=payer, amount_units=amount, asset=asset, pay_to=pay_to,
                    timestamp=timestamp, nonce=nonce, signature=signature, is_valid=False
                )

            if Web3.to_checksum_address(pay_to) != self.backend_address:
                logger.warning("Payment recipient mismatch: provided=%s expected=%s", pay_to, self.backend_address)
                return PaymentDetails(
                    payer=payer, amount_units=amount, asset=asset, pay_to=pay_to,
                    timestamp=timestamp, nonce=nonce, signature=signature, is_valid=False
                )

            if Web3.to_checksum_address(asset) != self.usdc_address:
                logger.warning("Payment asset mismatch: provided=%s expected=%s", asset, self.usdc_address)
                return PaymentDetails(
                    payer=payer, amount_units=amount, asset=asset, pay_to=pay_to,
                    timestamp=timestamp, nonce=nonce, signature=signature, is_valid=False
                )

            current_time = int(time.time())
            if timestamp > current_time + 60:
                logger.warning("Payment timestamp in future: %s", timestamp)
                return PaymentDetails(
                    payer=payer, amount_units=amount, asset=asset, pay_to=pay_to,
                    timestamp=timestamp, nonce=nonce, signature=signature, is_valid=False
                )

            if current_time - timestamp > max_age_seconds:
                logger.warning("Payment timestamp too old: %s (max age: %s)", current_time - timestamp, max_age_seconds)
                return PaymentDetails(
                    payer=payer, amount_units=amount, asset=asset, pay_to=pay_to,
                    timestamp=timestamp, nonce=nonce, signature=signature, is_valid=False
                )

            if self.database and self.database.is_nonce_used(payer, nonce):
                logger.warning("Nonce already used: payer=%s nonce=%s", payer, nonce)
                return PaymentDetails(
                    payer=payer, amount_units=amount, asset=asset, pay_to=pay_to,
                    timestamp=timestamp, nonce=nonce, signature=signature, is_valid=False
                )

            is_valid = self._verify_signature(
                payer=payer, amount=amount, asset=asset, pay_to=pay_to,
                timestamp=timestamp, nonce=nonce, signature=signature
            )

            if is_valid:
                if self.database:
                    self.database.mark_nonce_used(payer, nonce, timestamp)
                logger.info("Payment verified successfully: payer=%s amount=%s", payer, amount)
            else:
                logger.warning("Payment signature verification failed: payer=%s", payer)

            return PaymentDetails(
                payer=payer, amount_units=amount, asset=asset, pay_to=pay_to,
                timestamp=timestamp, nonce=nonce, signature=signature, is_valid=is_valid
            )

        except Exception as e:
            logger.exception("Payment verification error: %s", e)
            return PaymentDetails(
                payer="", amount_units=0, asset="", pay_to="",
                timestamp=0, nonce="", signature="", is_valid=False
            )

    def _parse_payment_header(self, payment_header: str) -> Optional[Dict]:
        """Parse x402 payment header (V1 comma-separated or V2 base64)"""
        try:
            decoded = base64.b64decode(payment_header)
            payload = json.loads(decoded)
            if isinstance(payload, dict):
                return payload
        except (ValueError, json.JSONDecodeError):
            pass

        try:
            parts = {}
            for item in payment_header.split(','):
                if '=' in item:
                    key, value = item.split('=', 1)
                    parts[key.strip()] = value.strip()
            return parts
        except (ValueError, AttributeError) as e:
            logger.exception("Error parsing payment header: %s", e)
            return None

    def _verify_signature(self, payer, amount, asset, pay_to, timestamp, nonce, signature) -> bool:
        try:
            domain_data = {
                "name": "x402 Payment",
                "version": "1",
                "chainId": self.chain_id,
            }
            message_types = {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                ],
                "Payment": [
                    {"name": "payer", "type": "address"},
                    {"name": "amount", "type": "uint256"},
                    {"name": "asset", "type": "address"},
                    {"name": "payTo", "type": "address"},
                    {"name": "timestamp", "type": "uint256"},
                    {"name": "nonce", "type": "string"},
                ]
            }
            message_data = {
                "payer": Web3.to_checksum_address(payer),
                "amount": amount,
                "asset": Web3.to_checksum_address(asset),
                "payTo": Web3.to_checksum_address(pay_to),
                "timestamp": timestamp,
                "nonce": nonce,
            }
            structured_msg = {
                "types": message_types,
                "primaryType": "Payment",
                "domain": domain_data,
                "message": message_data,
            }
            try:
                encoded_msg = encode_structured_data(full_message=structured_msg)
            except TypeError:
                encoded_msg = encode_structured_data(structured_msg)
            recovered_address = Account.recover_message(encoded_msg, signature=signature)
            return recovered_address.lower() == payer.lower()
        except Exception as e:
            logger.exception("Signature verification error: %s", e)
            return False

    def settle_payment(
        self,
        payment_header: str,
        payment_requirements: dict,
    ) -> Optional[Dict]:
        """No-op settlement for local EIP-712 mode (no facilitator)."""
        logger.info("Local EIP-712 mode: settlement skipped (no facilitator)")
        return {"success": True, "transaction": None}


