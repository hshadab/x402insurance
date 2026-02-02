# x402 Insurance

Insurance for AI agents that pay for APIs using the [x402 protocol](https://github.com/coinbase/x402). When a paid API fails, the agent gets a refund.

## What this does

AI agents use x402 to pay for API calls with USDC on the Base blockchain. The problem: if the API takes your money and then returns an error (500, 503, timeout), you lose your USDC with no way to get it back. x402 has no built-in refund mechanism.

This service fixes that. An agent buys an insurance policy before making an API call. If the API fails, the agent submits a claim with the failed HTTP response. The service verifies the failure actually happened, generates a cryptographic proof, and sends the agent a USDC refund on Base Mainnet.

## How it works

1. **Agent buys a policy** — `POST /insure` with a 1% premium payment. For example, to insure a $0.01 API call, the agent pays $0.0001 USDC. The policy covers one merchant URL for 24 hours.

2. **Agent makes its API call** — If the merchant works fine, great. The agent spent $0.0001 on insurance and got the service it paid for.

3. **If the API fails** — The agent sends `POST /claim` with the policy ID and the failed HTTP response (status code + body).

4. **Server verifies the failure** — The server independently re-fetches the merchant URL to confirm the API is actually down. If the agent reports 503 but the server sees 200, the claim is rejected.

5. **Cryptographic proof generation** — A [Jolt Atlas](https://github.com/ICME-Lab/jolt-atlas) prover runs an ONNX neural network classifier over the HTTP response data and generates a zero-knowledge proof (SNARK) that the failure is genuine. This proof is publicly verifiable by anyone.

6. **USDC refund** — If the proof is valid, the service sends the full coverage amount back to the agent's wallet as USDC on Base Mainnet. The refund typically arrives in 15-30 seconds.

## Live dashboard

**https://4axkjkepdx.us-east-1.awsapprunner.com**

The public dashboard runs on AWS App Runner. It's a read-only view of the service — you can browse the API docs, check health, look up pricing, and see the agent discovery card. It doesn't need wallet keys or blockchain access.

The full insurance service (policy creation, claims, proofs, refunds) runs on AWS Bedrock AgentCore. Agents interact with it through AgentCore's runtime API, not through the dashboard URL.

For local development, `docker-compose up` gives you both: the full service on port 8080 and the dashboard on port 8000.

## Payments

All payment-protected endpoints (`/insure`, `/claim`, `/renew`) use the x402 V2 protocol:

1. Agent sends a request without payment
2. Server responds `402 Payment Required` with the amount, asset (USDC), and recipient address
3. Agent signs an EIP-712 typed-data payment message with its wallet key
4. Agent retries the request with a `PAYMENT-SIGNATURE` header containing the signed payment
5. Server verifies the payment via the [x402.org facilitator](https://x402.org/facilitator) and settles it on-chain

Python helper functions for this flow are in `agent_helpers.py`:

```python
from agent_helpers import agent_purchase_policy, agent_submit_claim

# Buy insurance
policy = agent_purchase_policy(
    server_url="http://localhost:8080",
    merchant_url="https://api.example.com/data",
    coverage_amount=0.01,
    agent_address="0xYourWallet",
)

# Submit a claim if the API fails
claim = agent_submit_claim(
    server_url="http://localhost:8080",
    policy_id=policy["policy_id"],
    http_status=503,
    http_body="Service Unavailable",
    agent_address="0xYourWallet",
)
```

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/insure` | POST | x402 | Buy an insurance policy (supports `Idempotency-Key` header) |
| `/claim` | POST | x402 | Submit a claim (supports `Idempotency-Key`, `webhook_url`, `?async=true`) |
| `/renew` | POST | x402 | Extend a policy's duration (supports `Idempotency-Key` header) |
| `/policies?wallet=0x...` | GET | Public | List policies by wallet address |
| `/claims/<id>` | GET | Public | Check claim status |
| `/proofs/<id>` | GET | Public | Get the cryptographic proof for a claim |
| `/verify` | POST | Public | Independently verify a SNARK proof |
| `/.well-known/agent-card.json` | GET | Public | Agent discovery card (A2A compatible) |
| `/api/pricing` | GET | Public | Pricing and coverage details |
| `/health` | GET | Public | Service health check |

## Running locally

```bash
# Install dependencies
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Configure environment — copy .env.example to .env and set:
#   BACKEND_WALLET_PRIVATE_KEY  (Base Mainnet wallet funded with ETH + USDC)
#   BACKEND_WALLET_ADDRESS
#   BASE_RPC_URL                (Alchemy or similar)

# Start the service on port 8080
python agentcore_agent.py

# Visit http://localhost:8080/ for the dashboard
```

## Running with Docker

```bash
# Full stack: service (8080) + dashboard (8000) + PostgreSQL + Redis
docker-compose up

# Development mode with hot-reload
docker-compose -f docker-compose.dev.yml up
```

## Deploying to AWS

**AgentCore** (full service):
```bash
agentcore configure -e agentcore_agent.py -r us-east-1
agentcore deploy
```

**App Runner** (public dashboard):
```bash
docker build -f Dockerfile.dashboard -t x402-dashboard .

aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin 851725214068.dkr.ecr.us-east-1.amazonaws.com
docker tag x402-dashboard 851725214068.dkr.ecr.us-east-1.amazonaws.com/x402-insurance-dashboard:latest
docker push 851725214068.dkr.ecr.us-east-1.amazonaws.com/x402-insurance-dashboard:latest
```

## Configuration

| Variable | Description | Required |
|----------|-------------|----------|
| `BACKEND_WALLET_PRIVATE_KEY` | Wallet private key for issuing USDC refunds | Yes |
| `BACKEND_WALLET_ADDRESS` | Corresponding wallet address | Yes |
| `BASE_RPC_URL` | Base Mainnet RPC endpoint | Yes |
| `JOLT_BINARY_PATH` | Path to the Jolt Atlas prover binary | Yes |
| `FACILITATOR_URL` | x402 facilitator URL (default: `https://x402.org/facilitator`) | No |
| `USDC_CONTRACT_ADDRESS` | USDC contract on Base (default: mainnet USDC) | No |
| `DATABASE_URL` | PostgreSQL connection string (omit for JSON file storage) | No |
| `CHAIN_ID` | Blockchain chain ID (default: 8453 for Base Mainnet) | No |
| `MERCHANT_REQUEST_TIMEOUT` | Timeout for merchant URL re-fetch in seconds (default: 10) | No |
| `CLAIM_TASK_TIMEOUT` | Max seconds for async claim processing (default: 300) | No |
| `WEBHOOK_ENABLED` | Enable webhook delivery for async claims (default: true) | No |
| `WEBHOOK_TIMEOUT` | Timeout for webhook POST in seconds (default: 10) | No |
| `LOG_FORMAT` | `plain` or `json` for structured logging (default: plain) | No |

## Project structure

```
agentcore_agent.py       Full service entry point (port 8080, AgentCore)
dashboard_server.py      Dashboard-only entry point (port 8000, App Runner)
agent_helpers.py         x402 V2 payment helpers for autonomous agents
app.py                   Flask application factory (supports dashboard_only mode)
config.py                Environment-based configuration
extensions.py            Shared service instances

core/
  blockchain.py          USDC refunds on Base via web3.py
  database.py            JSON file backend (dev) or PostgreSQL (prod)
  proof_client.py        Jolt Atlas SNARK proof generation and verification
  utils.py               Monetary helpers, URL validation, datetime utils

auth/
  payment_verifier.py    x402 V2 payment verification via facilitator

blueprints/
  discovery.py           GET / (dashboard), /.well-known/agent-card.json, /api/*
  health.py              GET /health, /ping, /metrics
  policies.py            POST /insure, GET /policies, POST /renew
  claims.py              POST /claim, GET /claims/<id>, GET /proofs/<id>
  verify.py              POST /verify

services/
  claim_service.py       Shared claim processing logic (proof + refund)

tasks/                   Huey background jobs (async claims, reserve monitoring)
static/dashboard.html    Single-page dashboard UI
jolt-atlas/              Jolt Atlas prover binary + SRS file
Dockerfile               Full service image (Jolt binary + QEMU)
Dockerfile.dashboard     Lightweight dashboard image for App Runner
```

## Testing

```bash
pip install -r requirements-dev.txt
pytest tests/unit/ -v
```

## Security

- All payments (premiums, claim fees, renewals) are settled on-chain before any state change — no "pending" payments
- Claim records are persisted before issuing refunds, so a crash never loses a valid claim
- Reserve solvency check on every new policy — rejects if wallet can't cover outstanding liabilities
- Stuck policies auto-recover: if claim processing crashes, policies unlock after 10 minutes
- All claim submissions require x402 payment authentication
- Payments verified via the x402.org facilitator (signature, nonce, amount)
- Server-side failure verification: independently re-fetches merchant URLs to confirm downtime
- SSRF prevention on merchant URLs (blocks private IPs, loopback, internal hostnames)
- Atomic database operations prevent double-claiming
- Request correlation IDs (`X-Request-ID`) on every request for traceability
- Rate limit headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `Retry-After`) in all responses
- Structured JSON logging available via `LOG_FORMAT=json`
- Prometheus metrics for claims, refunds, and reserve ratio
- Webhook URLs validated against SSRF before delivery
- Stuck async claims auto-recover after configurable timeout
- No mock modes — real blockchain transactions and real SNARK proofs only
