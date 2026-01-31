"""
Tests for policy renewal endpoint.
"""
import os
import json
import base64
import pytest


def _v2_payment_header(amount=100):
    payload = {"x402Version": 2, "amount": amount, "signature": "0xabc123"}
    return base64.b64encode(json.dumps(payload).encode()).decode()


@pytest.fixture
def app():
    from app import create_app
    app = create_app("testing")
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _create_policy(client, payer=None):
    payer = payer or os.environ["BACKEND_WALLET_ADDRESS"]
    resp = client.post('/insure', json={
        "merchant_url": "https://api.example.com/test",
        "coverage_amount": 0.01
    }, headers={
        "PAYMENT-SIGNATURE": _v2_payment_header(100),
        "X-Payer": payer
    })
    return resp.get_json()


class TestRenewPolicy:
    def test_renew_missing_policy_id(self, client):
        resp = client.post('/renew', json={"extend_hours": 24},
                           headers={"PAYMENT-SIGNATURE": _v2_payment_header(100),
                                    "X-Payer": os.environ["BACKEND_WALLET_ADDRESS"]})
        assert resp.status_code == 400

    def test_renew_policy_not_found(self, client):
        resp = client.post('/renew', json={"policy_id": "nonexistent", "extend_hours": 24},
                           headers={"PAYMENT-SIGNATURE": _v2_payment_header(100),
                                    "X-Payer": os.environ["BACKEND_WALLET_ADDRESS"]})
        assert resp.status_code == 404

    def test_renew_returns_402_without_payment(self, client):
        policy = _create_policy(client)
        resp = client.post('/renew', json={
            "policy_id": policy["policy_id"],
            "extend_hours": 24
        })
        assert resp.status_code == 402

    def test_renew_invalid_extend_hours(self, client):
        resp = client.post('/renew', json={"policy_id": "test", "extend_hours": 200},
                           headers={"PAYMENT-SIGNATURE": _v2_payment_header(100),
                                    "X-Payer": os.environ["BACKEND_WALLET_ADDRESS"]})
        assert resp.status_code == 400
