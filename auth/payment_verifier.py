"""
x402 Payment Verification Module

Handles proper verification of x402 payments including:
- EIP-712 signature verification
- Timestamp/expiry validation
- Replay attack prevention
- Amount verification
"""
from eth_account import Account
try:
    from eth_account.messages import encode_typed_data as encode_structured_data
except ImportError:
    from eth_account.messages import encode_structured_data
from web3 import Web3
import time
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

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


class PaymentVerifier:
    """Verify x402 payments with proper signature validation"""

    def __init__(self, backend_address: str, usdc_address: str, nonce_storage_path: Optional[Path] = None):
        self.backend_address = Web3.to_checksum_address(backend_address)
        self.usdc_address = Web3.to_checksum_address(usdc_address)
        self.nonce_storage_path = nonce_storage_path or Path("data/nonce_cache.json")
        self.cache_cleanup_interval = 3600  # Clean up old nonces every hour
        self.last_cleanup = time.time()

        # Load nonce cache from disk if it exists (survives restarts)
        self.nonce_cache = self._load_nonce_cache()
        logger.info(
            "PaymentVerifier initialized with %d cached nonces (persistent storage: %s)",
            len(self.nonce_cache), self.nonce_storage_path
        )

    def verify_payment(
        self,
        payment_header: str,
        payer_address: Optional[str],
        required_amount: int,
        max_age_seconds: int = 300  # 5 minutes
    ) -> PaymentDetails:
        """
        Verify x402 payment from headers

        Args:
            payment_header: X-Payment header value
            payer_address: X-Payer or X-From-Address header value
            required_amount: Expected payment amount in USDC units (6 decimals)
            max_age_seconds: Maximum age of payment timestamp

        Returns:
            PaymentDetails with is_valid flag
        """
        try:
            # Parse payment header
            payment_data = self._parse_payment_header(payment_header)

            if not payment_data:
                return PaymentDetails(
                    payer="", amount_units=0, asset="", pay_to="",
                    timestamp=0, nonce="", signature="", is_valid=False
                )

            # Extract fields
            payer = payment_data.get('payer', payer_address or '')
            amount = int(payment_data.get('amount', 0))
            asset = payment_data.get('asset', self.usdc_address)
            pay_to = payment_data.get('payTo', self.backend_address)
            timestamp = int(payment_data.get('timestamp', 0))
            nonce = payment_data.get('nonce', '')
            signature = payment_data.get('signature', '')

            # Validate basic fields
            if not all([payer, amount, asset, pay_to, timestamp, nonce, signature]):
                logger.warning("Missing required payment fields")
                return PaymentDetails(
                    payer=payer, amount_units=amount, asset=asset, pay_to=pay_to,
                    timestamp=timestamp, nonce=nonce, signature=signature, is_valid=False
                )

            # Validate amount matches
            if amount != required_amount:
                logger.warning(
                    "Payment amount mismatch: provided=%s required=%s",
                    amount, required_amount
                )
                return PaymentDetails(
                    payer=payer, amount_units=amount, asset=asset, pay_to=pay_to,
                    timestamp=timestamp, nonce=nonce, signature=signature, is_valid=False
                )

            # Validate recipient
            if Web3.to_checksum_address(pay_to) != self.backend_address:
                logger.warning(
                    "Payment recipient mismatch: provided=%s expected=%s",
                    pay_to, self.backend_address
                )
                return PaymentDetails(
                    payer=payer, amount_units=amount, asset=asset, pay_to=pay_to,
                    timestamp=timestamp, nonce=nonce, signature=signature, is_valid=False
                )

            # Validate asset
            if Web3.to_checksum_address(asset) != self.usdc_address:
                logger.warning(
                    "Payment asset mismatch: provided=%s expected=%s",
                    asset, self.usdc_address
                )
                return PaymentDetails(
                    payer=payer, amount_units=amount, asset=asset, pay_to=pay_to,
                    timestamp=timestamp, nonce=nonce, signature=signature, is_valid=False
                )

            # Validate timestamp (not too old, not in future)
            current_time = int(time.time())
            if timestamp > current_time + 60:  # Allow 60s clock skew
                logger.warning("Payment timestamp in future: %s", timestamp)
                return PaymentDetails(
                    payer=payer, amount_units=amount, asset=asset, pay_to=pay_to,
                    timestamp=timestamp, nonce=nonce, signature=signature, is_valid=False
                )

            if current_time - timestamp > max_age_seconds:
                logger.warning(
                    "Payment timestamp too old: %s (max age: %s)",
                    current_time - timestamp, max_age_seconds
                )
                return PaymentDetails(
                    payer=payer, amount_units=amount, asset=asset, pay_to=pay_to,
                    timestamp=timestamp, nonce=nonce, signature=signature, is_valid=False
                )

            # Check for replay attack (nonce reuse)
            if self._is_nonce_used(payer, nonce):
                logger.warning("Nonce already used: payer=%s nonce=%s", payer, nonce)
                return PaymentDetails(
                    payer=payer, amount_units=amount, asset=asset, pay_to=pay_to,
                    timestamp=timestamp, nonce=nonce, signature=signature, is_valid=False
                )

            # Verify EIP-712 signature
            is_valid = self._verify_signature(
                payer=payer,
                amount=amount,
                asset=asset,
                pay_to=pay_to,
                timestamp=timestamp,
                nonce=nonce,
                signature=signature
            )

            if is_valid:
                # Mark nonce as used
                self._mark_nonce_used(payer, nonce, timestamp)
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
        """Parse x402 payment header"""
        try:
            # Simple comma-separated format: key=value,key=value
            parts = {}
            for item in payment_header.split(','):
                if '=' in item:
                    key, value = item.split('=', 1)
                    parts[key.strip()] = value.strip()
            return parts
        except Exception as e:
            logger.exception("Error parsing payment header: %s", e)
            return None

    def _verify_signature(
        self,
        payer: str,
        amount: int,
        asset: str,
        pay_to: str,
        timestamp: int,
        nonce: str,
        signature: str
    ) -> bool:
        """
        Verify EIP-712 signature for x402 payment

        This implements a simplified EIP-712 signature verification.
        In production, use the exact domain and message structure from x402 spec.
        """
        try:
            # Define EIP-712 domain
            domain_data = {
                "name": "x402 Payment",
                "version": "1",
                "chainId": 8453,  # Base Mainnet
            }

            # Define message structure
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

            # Encode structured data
            structured_msg = {
                "types": message_types,
                "primaryType": "Payment",
                "domain": domain_data,
                "message": message_data,
            }

            encoded_msg = encode_structured_data(structured_msg)

            # Recover signer address from signature
            recovered_address = Account.recover_message(encoded_msg, signature=signature)

            # Verify recovered address matches payer
            is_valid = recovered_address.lower() == payer.lower()

            return is_valid

        except Exception as e:
            logger.exception("Signature verification error: %s", e)
            return False

    def _load_nonce_cache(self) -> Dict[str, int]:
        """Load nonce cache from disk (persistent storage)"""
        try:
            if self.nonce_storage_path.exists():
                with open(self.nonce_storage_path, 'r') as f:
                    cache = json.load(f)
                    # Clean up old nonces on load
                    current_time = int(time.time())
                    cutoff_time = current_time - 3600  # 1 hour ago
                    cleaned_cache = {
                        k: v for k, v in cache.items()
                        if v >= cutoff_time
                    }
                    logger.info(
                        "Loaded %d nonces from cache (%d expired, %d active)",
                        len(cache), len(cache) - len(cleaned_cache), len(cleaned_cache)
                    )
                    return cleaned_cache
            return {}
        except Exception as e:
            logger.warning("Failed to load nonce cache, starting fresh: %s", e)
            return {}

    def _save_nonce_cache(self):
        """Save nonce cache to disk (persistent storage)"""
        try:
            # Ensure directory exists
            self.nonce_storage_path.parent.mkdir(parents=True, exist_ok=True)

            # Write atomically
            tmp_path = self.nonce_storage_path.with_suffix('.tmp')
            with open(tmp_path, 'w') as f:
                json.dump(self.nonce_cache, f, indent=2)
            tmp_path.replace(self.nonce_storage_path)
        except Exception as e:
            logger.error("Failed to save nonce cache: %s", e)

    def _is_nonce_used(self, payer: str, nonce: str) -> bool:
        """Check if nonce has been used (replay attack prevention)"""
        key = f"{payer.lower()}:{nonce}"

        # Cleanup old nonces periodically
        if time.time() - self.last_cleanup > self.cache_cleanup_interval:
            self._cleanup_old_nonces()

        return key in self.nonce_cache

    def _mark_nonce_used(self, payer: str, nonce: str, timestamp: int):
        """Mark nonce as used and persist to disk"""
        key = f"{payer.lower()}:{nonce}"
        self.nonce_cache[key] = timestamp

        # Save to disk (survives restart)
        self._save_nonce_cache()

    def _cleanup_old_nonces(self):
        """Remove nonces older than 1 hour"""
        current_time = int(time.time())
        cutoff_time = current_time - 3600  # 1 hour ago

        old_nonces = [
            key for key, timestamp in self.nonce_cache.items()
            if timestamp < cutoff_time
        ]

        for key in old_nonces:
            del self.nonce_cache[key]

        self.last_cleanup = current_time

        # Save cleaned cache to disk
        if old_nonces:
            self._save_nonce_cache()
            logger.info("Cleaned up %d old nonces, %d remain", len(old_nonces), len(self.nonce_cache))


class SimplePaymentVerifier:
    """
    Simplified payment verifier for testing/development

    Only validates amount and basic fields, skips signature verification.
    Use PaymentVerifier for production.
    """

    def __init__(self, backend_address: str, usdc_address: str):
        self.backend_address = backend_address
        self.usdc_address = usdc_address

    def verify_payment(
        self,
        payment_header: str,
        payer_address: Optional[str],
        required_amount: int,
        max_age_seconds: int = 300
    ) -> PaymentDetails:
        """Simple payment verification for testing"""
        try:
            # Parse simple format: token=...,amount=...,signature=...
            parts = {}
            for item in payment_header.split(','):
                if '=' in item:
                    key, value = item.split('=', 1)
                    parts[key.strip().lower()] = value.strip()

            amount = int(parts.get('amount', 0)) if parts.get('amount') else None

            if amount is None or amount != required_amount:
                return PaymentDetails(
                    payer=payer_address or "",
                    amount_units=amount or 0,
                    asset=self.usdc_address,
                    pay_to=self.backend_address,
                    timestamp=int(time.time()),
                    nonce="",
                    signature=parts.get('signature', ''),
                    is_valid=False
                )

            return PaymentDetails(
                payer=payer_address or "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0",
                amount_units=amount,
                asset=self.usdc_address,
                pay_to=self.backend_address,
                timestamp=int(time.time()),
                nonce=parts.get('token', ''),
                signature=parts.get('signature', ''),
                is_valid=True
            )

        except Exception as e:
            logger.exception("Simple payment verification error: %s", e)
            return PaymentDetails(
                payer="", amount_units=0, asset="", pay_to="",
                timestamp=0, nonce="", signature="", is_valid=False
            )
