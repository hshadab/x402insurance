"""
x402 Insurance Dashboard — Lightweight Entry Point for App Runner.

Serves the read-only informational dashboard and health/discovery
endpoints only.  No blockchain, wallet, prover, or payment deps.
"""
from app import create_dashboard_app
from config import get_config

app = create_dashboard_app()

if __name__ == '__main__':
    config = get_config()
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
