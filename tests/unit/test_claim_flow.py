"""
Tests for claim submission flow (sync/async), idempotency, policy validation,
concurrent claim rejection, and refund failure handling.
"""
import os
import json
import base64
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def _clean_extensions():
    """Reset extensions between tests to avoid stale state."""
    import extensions as ext
    yield
    if ext.CLAIMS_FILE and ext.CLAIMS_FILE.exists():
        ext.CLAIMS_FILE.unlink(missing_ok=True)
    if ext.POLICIES_FILE and ext.POLICIES_FILE.exists():
        ext.POLICIES_FILE.unlink(missing_ok=True)


@pytest.fixture
def app():
    from app import create_app
    a = create_app("testing")
    a.config["TESTING"] = True
    return a


@pytest.fixture
def client(app):
    return app.test_client()


def _v2_payment_header(amount=100):
    """Build a base64-encoded V2 payment header."""
    payload = {"x402Version": 2, "amount": amount, "signature": "0xabc123"}
    return base64.b64encode(json.dumps(payload).encode()).decode()


def _create_policy(client):
    """Helper: create a policy and return policy data."""
    resp = client.post('/insure', json={
        "merchant_url": "https://api.example.com/test",
        "coverage_amount": 0.01
    }, headers={
        "PAYMENT-SIGNATURE": _v2_payment_header(100),
        "X-Payer": os.environ["BACKEND_WALLET_ADDRESS"]
    })
    return resp.get_json()


class TestClaimSubmission:
    def test_claim_sync_requires_policy_id(self, client):
        resp = client.post('/claim', json={"merchant_url": "https://api.example.com/test", "http_response": {"status": 503, "body": ""}},
                           headers={"PAYMENT-SIGNATURE": _v2_payment_header(100),
                                    "X-Payer": os.environ["BACKEND_WALLET_ADDRESS"]})
        assert resp.status_code == 400

    def test_claim_sync_requires_http_response(self, client):
        resp = client.post('/claim', json={"policy_id": "nonexistent"},
                           headers={"PAYMENT-SIGNATURE": _v2_payment_header(100),
                                    "X-Payer": os.environ["BACKEND_WALLET_ADDRESS"]})
        assert resp.status_code == 400

    def test_claim_policy_not_found(self, client):
        resp = client.post('/claim', json={
            "policy_id": "nonexistent-id",
            "merchant_url": "https://api.example.com/test", "http_response": {"status": 503, "body": ""}
        }, headers={
            "PAYMENT-SIGNATURE": _v2_payment_header(100),
            "X-Payer": os.environ["BACKEND_WALLET_ADDRESS"]
        })
        assert resp.status_code == 404

    def test_claim_sync_success(self, client):
        policy = _create_policy(client)
        assert "policy_id" in policy

        resp = client.post('/claim', json={
            "policy_id": policy["policy_id"],
            "merchant_url": "https://api.example.com/test", "http_response": {"status": 503, "body": ""}
        }, headers={
            "PAYMENT-SIGNATURE": _v2_payment_header(100),
            "X-Payer": os.environ["BACKEND_WALLET_ADDRESS"]
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "paid"
        assert "proof" in data
        assert "refund_tx_hash" in data

    def test_claim_async_returns_202(self, client):
        policy = _create_policy(client)
        resp = client.post('/claim?async=true', json={
            "policy_id": policy["policy_id"],
            "merchant_url": "https://api.example.com/test", "http_response": {"status": 500, "body": ""}
        }, headers={
            "PAYMENT-SIGNATURE": _v2_payment_header(100),
            "X-Payer": os.environ["BACKEND_WALLET_ADDRESS"]
        })
        assert resp.status_code == 202
        data = resp.get_json()
        assert data["status"] == "processing"
        assert "poll_url" in data


class TestClaimIdempotency:
    def test_idempotent_claim(self, client):
        policy = _create_policy(client)
        headers = {
            "Idempotency-Key": "test-idem-key-123",
            "PAYMENT-SIGNATURE": _v2_payment_header(100),
            "X-Payer": os.environ["BACKEND_WALLET_ADDRESS"],
        }

        resp1 = client.post('/claim', json={
            "policy_id": policy["policy_id"],
            "merchant_url": "https://api.example.com/test", "http_response": {"status": 503, "body": ""}
        }, headers=headers)
        assert resp1.status_code == 201

        # Second request with same idempotency key returns cached result
        policy2 = _create_policy(client)
        resp2 = client.post('/claim', json={
            "policy_id": policy2["policy_id"],
            "merchant_url": "https://api.example.com/test", "http_response": {"status": 503, "body": ""}
        }, headers=headers)
        assert resp2.status_code == 200
        assert resp2.get_json()["idempotent"] is True


class TestClaimInputValidation:
    def test_invalid_http_status(self, client):
        policy = _create_policy(client)
        resp = client.post('/claim', json={
            "policy_id": policy["policy_id"],
            "merchant_url": "https://api.example.com/test", "http_response": {"status": 9999, "body": ""}
        }, headers={
            "PAYMENT-SIGNATURE": _v2_payment_header(100),
            "X-Payer": os.environ["BACKEND_WALLET_ADDRESS"]
        })
        assert resp.status_code == 400

    def test_body_too_large(self, client):
        policy = _create_policy(client)
        large_body = "x" * (500 * 1024 + 1)
        resp = client.post('/claim', json={
            "policy_id": policy["policy_id"],
            "merchant_url": "https://api.example.com/test", "http_response": {"status": 503, "body": large_body}
        }, headers={
            "PAYMENT-SIGNATURE": _v2_payment_header(100),
            "X-Payer": os.environ["BACKEND_WALLET_ADDRESS"]
        })
        assert resp.status_code == 400

    def test_headers_must_be_dict(self, client):
        policy = _create_policy(client)
        resp = client.post('/claim', json={
            "policy_id": policy["policy_id"],
            "merchant_url": "https://api.example.com/test", "http_response": {"status": 503, "body": "", "headers": "not-a-dict"}
        }, headers={
            "PAYMENT-SIGNATURE": _v2_payment_header(100),
            "X-Payer": os.environ["BACKEND_WALLET_ADDRESS"]
        })
        assert resp.status_code == 400


class TestConcurrentClaimRejection:
    """Verify that the second claim on the same policy is rejected."""

    def test_second_claim_on_same_policy_returns_conflict(self, client):
        policy = _create_policy(client)
        pid = policy["policy_id"]
        claim_headers = {
            "PAYMENT-SIGNATURE": _v2_payment_header(100),
            "X-Payer": os.environ["BACKEND_WALLET_ADDRESS"],
        }

        resp1 = client.post('/claim', json={
            "policy_id": pid,
            "merchant_url": "https://api.example.com/test", "http_response": {"status": 503, "body": ""}
        }, headers=claim_headers)
        assert resp1.status_code == 201

        resp2 = client.post('/claim', json={
            "policy_id": pid,
            "merchant_url": "https://api.example.com/test", "http_response": {"status": 503, "body": ""}
        }, headers=claim_headers)
        assert resp2.status_code == 409


class TestRefundFailureHandling:
    """Verify that refund failure results in refund_failed status."""

    def test_refund_failure_creates_claim_with_refund_failed_status(self, client, app):
        policy = _create_policy(client)
        pid = policy["policy_id"]

        with app.app_context():
            import extensions as ext
            with patch.object(ext.blockchain, 'issue_refund', side_effect=Exception("Insufficient USDC")):
                resp = client.post('/claim', json={
                    "policy_id": pid,
                    "merchant_url": "https://api.example.com/test", "http_response": {"status": 503, "body": ""}
                }, headers={
                    "PAYMENT-SIGNATURE": _v2_payment_header(100),
                    "X-Payer": os.environ["BACKEND_WALLET_ADDRESS"],
                })
                assert resp.status_code == 500
                data = resp.get_json()
                assert data["status"] == "refund_failed"
                assert "claim_id" in data
