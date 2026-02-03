"""
Unit tests for payment verification (V1 + V2)
SimplePaymentVerifier has been removed — only FacilitatorPaymentVerifier exists.
"""
import base64
import json
import pytest
from auth.payment_verifier import PaymentDetails, FacilitatorPaymentVerifier


class TestPaymentDetails:
    """Test PaymentDetails dataclass"""

    def test_payment_details_creation(self):
        details = PaymentDetails(
            payer="0xTest",
            amount_units=1000,
            asset="0xUSDC",
            pay_to="0xBackend",
            timestamp=123456,
            nonce="abc",
            signature="0xsig",
            is_valid=True
        )

        assert details.payer == "0xTest"
        assert details.amount_units == 1000
        assert details.is_valid is True
        assert details.settlement_tx is None

    def test_payment_details_with_settlement(self):
        details = PaymentDetails(
            payer="0xTest",
            amount_units=1000,
            asset="0xUSDC",
            pay_to="0xBackend",
            timestamp=123456,
            nonce="abc",
            signature="0xsig",
            is_valid=True,
            settlement_tx="0xabc123"
        )

        assert details.settlement_tx == "0xabc123"


class TestV2PayloadParsing:
    """Test V2 base64 JSON payment payload parsing"""

    def test_v2_payload_round_trip(self):
        payload = {
            "x402Version": 2,
            "resource": {"url": "/insure", "method": "POST"},
            "accepted": {
                "scheme": "exact",
                "network": "eip155:8453",
                "amount": "1000",
            },
            "payload": {"signature": "0xabc"},
        }
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        decoded = json.loads(base64.b64decode(encoded))

        assert decoded["x402Version"] == 2
        assert decoded["accepted"]["network"] == "eip155:8453"


class TestFacilitatorPaymentVerifierParsing:
    """Test that FacilitatorPaymentVerifier correctly parses V1 and V2 headers."""

    def setup_method(self):
        self.verifier = FacilitatorPaymentVerifier(
            backend_address="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0",
            usdc_address="0x036CbD53842c5426634e7929541eC2318f3dCF7e",
            facilitator_url="https://api.cdp.coinbase.com/platform/v2/x402",
            chain_id=84532,
        )

    def test_parse_v2_header(self):
        payload = {"x402Version": 2, "amount": 1000}
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        result = self.verifier._parse_v2_payment_header(encoded)
        assert result is not None
        assert result["x402Version"] == 2

    def test_parse_v1_header(self):
        result = self.verifier._parse_v1_payment_header("token=test,amount=1000,signature=abc")
        assert result is not None
        assert result["amount"] == "1000"

    def test_parse_v2_invalid_base64(self):
        result = self.verifier._parse_v2_payment_header("not-base64!!!")
        assert result is None
