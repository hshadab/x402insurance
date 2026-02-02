"""
Dashboard-only entry point for App Runner.

Runs the Flask app in read-only dashboard mode (DASHBOARD_ONLY=true).
No blockchain, wallet, prover, or payment verification dependencies needed.
Serves the dashboard UI, agent discovery card, health checks, and pricing info.

Public URL: https://4axkjkepdx.us-east-1.awsapprunner.com
"""
import os
import logging

os.environ.setdefault("DASHBOARD_ONLY", "true")
os.environ.setdefault("PORT", "8000")

from app import create_app

app = create_app(dashboard_only=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logging.getLogger("x402insurance").info(
        "Starting x402 Insurance Dashboard on port %d (read-only)", port
    )
    app.run(host="0.0.0.0", port=port)
