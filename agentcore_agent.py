"""
AWS Bedrock AgentCore entry point for x402 Insurance Service.

This is the PRIMARY entry point for the full insurance service.
Runs on AgentCore infrastructure at port 8080 with all capabilities:
- Policy creation, claims processing, proof generation
- Blockchain USDC refunds on Base Mainnet
- x402 V2 payment verification via facilitator
- Server-side failure verification

Agent helpers (agent_purchase_policy, agent_submit_claim) are in agent_helpers.py.
"""
import os
import json
import logging

logger = logging.getLogger("x402insurance.agentcore")

# Set port to 8080 for AgentCore before importing Flask app
os.environ.setdefault("PORT", "8080")

from app import create_app

flask_app = create_app()


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
