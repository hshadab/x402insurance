"""
AWS Bedrock AgentCore entry point for x402 Insurance Service.

This is the PRIMARY entry point for the full insurance service.
Runs on AgentCore infrastructure at port 8080 with all capabilities:
- Policy creation, claims processing, proof generation
- Blockchain USDC refunds on Base Mainnet
- x402 V2 payment verification via facilitator
- Server-side fraud detection

Also provides autonomous agent helpers:
1. Purchase insurance policies via x402 V2 payment flow
2. Submit claims when merchant APIs fail
3. Handle 402 -> sign payment -> retry with payment header

For the read-only dashboard, see dashboard_server.py.
"""
import os
import json
import logging
import time
import base64
import uuid

logger = logging.getLogger("x402insurance.agentcore")

# Set port to 8080 for AgentCore before importing Flask app
os.environ.setdefault("PORT", "8080")

from app import create_app

flask_app = create_app()


# ---------------------------------------------------------------------------
# x402 V2 Agent Payment Helpers
# ---------------------------------------------------------------------------

def _build_eip712_payment(
    payer_address: str,
    amount_units: int,
    asset_address: str,
    pay_to: str,
    chain_id: int = 8453,
) -> dict:
    """
    Build an x402 V2 payment payload dict suitable for base64-encoding
    into a PAYMENT-SIGNATURE header.

    This uses EIP-712 typed-data signing.  The caller must have access to
    the agent's private key (via AGENT_WALLET_PRIVATE_KEY env var).
    """
    from eth_account import Account
    from web3 import Web3

    private_key = os.environ.get("AGENT_WALLET_PRIVATE_KEY")
    if not private_key:
        raise RuntimeError("AGENT_WALLET_PRIVATE_KEY is required for agent payment signing")

    nonce = uuid.uuid4().hex
    timestamp = int(time.time())

    domain_data = {
        "name": "x402 Payment",
        "version": "1",
        "chainId": chain_id,
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
        ],
    }

    message_data = {
        "payer": Web3.to_checksum_address(payer_address),
        "amount": amount_units,
        "asset": Web3.to_checksum_address(asset_address),
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
        from eth_account.messages import encode_typed_data as encode_structured_data
    except ImportError:
        from eth_account.messages import encode_structured_data

    try:
        encoded = encode_structured_data(full_message=structured_msg)
    except TypeError:
        encoded = encode_structured_data(structured_msg)

    acct = Account.from_key(private_key)
    signed = acct.sign_message(encoded)

    payload = {
        "x402Version": 2,
        "scheme": "exact",
        "network": f"eip155:{chain_id}",
        "payer": Web3.to_checksum_address(payer_address),
        "amount": str(amount_units),
        "asset": Web3.to_checksum_address(asset_address),
        "payTo": Web3.to_checksum_address(pay_to),
        "timestamp": timestamp,
        "nonce": nonce,
        "signature": signed.signature.hex(),
    }
    return payload


def _encode_payment_header(payload: dict) -> str:
    """Base64-encode a payment payload dict for the PAYMENT-SIGNATURE header."""
    return base64.b64encode(json.dumps(payload).encode()).decode()


def agent_purchase_policy(
    server_url: str,
    merchant_url: str,
    coverage_amount: float,
    agent_address: str,
    chain_id: int = 8453,
):
    """
    Full x402 V2 flow: POST /insure -> detect 402 -> sign payment -> retry.

    Returns the policy response dict on success, or raises on failure.
    """
    import httpx

    # Step 1: POST without payment to get 402 requirements
    resp = httpx.post(
        f"{server_url}/insure",
        json={"merchant_url": merchant_url, "coverage_amount": coverage_amount},
        timeout=30.0,
    )

    if resp.status_code == 201:
        # Already paid (unlikely on first call)
        return resp.json()

    if resp.status_code != 402:
        raise RuntimeError(f"Expected 402, got {resp.status_code}: {resp.text}")

    # Step 2: Parse payment requirements from 402 response
    payment_info = resp.json()
    accepts = payment_info.get("accepts", [])
    if not accepts:
        raise RuntimeError("No payment options in 402 response")

    accept = accepts[0]
    amount = int(accept["amount"])
    asset = accept["asset"]
    pay_to = accept["payTo"]

    logger.info(
        "402 received: amount=%d asset=%s payTo=%s",
        amount, asset, pay_to,
    )

    # Step 3: Sign payment
    payment_payload = _build_eip712_payment(
        payer_address=agent_address,
        amount_units=amount,
        asset_address=asset,
        pay_to=pay_to,
        chain_id=chain_id,
    )
    payment_header = _encode_payment_header(payment_payload)

    # Step 4: Retry with payment
    resp2 = httpx.post(
        f"{server_url}/insure",
        json={"merchant_url": merchant_url, "coverage_amount": coverage_amount},
        headers={
            "PAYMENT-SIGNATURE": payment_header,
            "X-Payer": agent_address,
        },
        timeout=30.0,
    )

    if resp2.status_code == 201:
        logger.info("Policy created successfully")
        return resp2.json()

    raise RuntimeError(f"Policy creation failed: {resp2.status_code} {resp2.text}")


def agent_submit_claim(
    server_url: str,
    policy_id: str,
    http_status: int,
    http_body: str,
    agent_address: str,
    chain_id: int = 8453,
    async_mode: bool = False,
):
    """
    Submit a claim with x402 V2 payment authentication.

    The /claim endpoint requires payment authentication to prevent abuse.
    """
    import httpx

    claim_body = {
        "policy_id": policy_id,
        "http_response": {
            "status": http_status,
            "body": http_body,
            "headers": {},
        },
    }

    url = f"{server_url}/claim"
    if async_mode:
        url += "?async=true"

    # Step 1: POST without payment to get 402
    resp = httpx.post(url, json=claim_body, timeout=60.0)

    if resp.status_code in (201, 202):
        return resp.json()

    if resp.status_code != 402:
        raise RuntimeError(f"Expected 402, got {resp.status_code}: {resp.text}")

    # Step 2: Parse and sign
    payment_info = resp.json()
    accepts = payment_info.get("accepts", [])
    if not accepts:
        raise RuntimeError("No payment options in 402 response")

    accept = accepts[0]
    payment_payload = _build_eip712_payment(
        payer_address=agent_address,
        amount_units=int(accept["amount"]),
        asset_address=accept["asset"],
        pay_to=accept["payTo"],
        chain_id=chain_id,
    )
    payment_header = _encode_payment_header(payment_payload)

    # Step 3: Retry with payment
    resp2 = httpx.post(
        url,
        json=claim_body,
        headers={
            "PAYMENT-SIGNATURE": payment_header,
            "X-Payer": agent_address,
        },
        timeout=120.0,
    )

    if resp2.status_code in (201, 202):
        logger.info("Claim submitted successfully: %s", resp2.json().get("claim_id"))
        return resp2.json()

    raise RuntimeError(f"Claim submission failed: {resp2.status_code} {resp2.text}")


# ---------------------------------------------------------------------------
# AgentCore App (existing functionality)
# ---------------------------------------------------------------------------

def create_agentcore_app():
    """Create and configure the AgentCore-wrapped Flask app."""
    try:
        from bedrock_agentcore import BedrockAgentCoreApp

        agentcore_app = BedrockAgentCoreApp()

        @agentcore_app.entrypoint
        def invoke(payload):
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = {"prompt": payload}

            endpoint = payload.get("endpoint", "/api")
            method = payload.get("method", "GET").upper()
            body = payload.get("body", {})
            headers = payload.get("headers", {})

            with flask_app.test_client() as client:
                if method == "POST":
                    response = client.post(endpoint, json=body, headers=headers)
                elif method == "GET":
                    response = client.get(endpoint, headers=headers, query_string=payload.get("query", {}))
                else:
                    response = client.get(endpoint)

                result = {
                    "statusCode": response.status_code,
                    "body": response.get_json(silent=True) or response.get_data(as_text=True),
                    "headers": dict(response.headers),
                }

            return result

        return agentcore_app

    except ImportError:
        logger.warning("bedrock-agentcore not installed, running Flask directly")
        return None


if __name__ == "__main__":
    agentcore_app = create_agentcore_app()

    if agentcore_app:
        logger.info("Starting x402 Insurance via AgentCore on port 8080")
        agentcore_app.run()
    else:
        logger.info("Starting x402 Insurance Flask app on port 8080 (no AgentCore)")
        flask_app.run(host="0.0.0.0", port=8080)
