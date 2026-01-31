# x402 Insurance v2.3.0

**Jolt Atlas zkML SNARK-Verified Insurance for x402 API Failures**

Live on **AWS Bedrock AgentCore** (us-east-1). Protect your AI agents from API downtime,
timeouts, and service interruptions with instant, cryptographically-verified refunds on
Base Mainnet.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![x402 Protocol](https://img.shields.io/badge/x402-Compatible-blue)](https://github.com/coinbase/x402)
[![AgentCore](https://img.shields.io/badge/AWS-AgentCore-orange)](https://docs.aws.amazon.com/bedrock/latest/userguide/agentcore.html)

## Architecture

```
                    ┌─────────────────────────────────┐
                    │   AWS Bedrock AgentCore (8080)   │  ← Primary service
                    │   agentcore_agent.py             │
                    │                                  │
                    │   All insurance logic:           │
                    │   - POST /insure, /claim, /renew │
                    │   - POST /verify                 │
                    │   - Jolt Atlas SNARK proofs       │
                    │   - USDC refunds on Base Mainnet │
                    │   - x402 V2 payment verification │
                    └─────────────────────────────────┘
                                   │
              Agent-to-agent via AgentCore runtime
                                   │
┌──────────────────────┐   ┌──────────────────────────────┐
│  AI Agent / Client   │   │  App Runner Dashboard (8000) │  ← Read-only
│  x402 V2 payments    │   │  dashboard_server.py         │
│  PAYMENT-SIGNATURE   │   │                              │
│  header              │   │  - Static dashboard UI       │
└──────────────────────┘   │  - GET /health, /ping        │
                           │  - GET /.well-known/agent-card│
                           │  - GET /api, /api/pricing     │
                           └──────────────────────────────┘
```

**AgentCore** runs the full insurance service — blockchain, proofs, payments, claims.
**App Runner** serves a lightweight read-only dashboard for monitoring and agent discovery.

## Live Deployment

### Primary Service (Bedrock AgentCore)

| | |
|---|---|
| **Agent** | `agentcore_agent` |
| **ARN** | `arn:aws:bedrock-agentcore:us-east-1:851725214068:runtime/agentcore_agent-mHkElJ7QNo` |
| **Region** | us-east-1 |
| **Entry point** | `agentcore_agent.py` |

### Dashboard (App Runner — Read-Only)

| | |
|---|---|
| **URL** | **https://4axkjkepdx.us-east-1.awsapprunner.com** |
| **Dashboard** | https://4axkjkepdx.us-east-1.awsapprunner.com/ |
| **Agent Card** | https://4axkjkepdx.us-east-1.awsapprunner.com/.well-known/agent-card.json |
| **Health** | https://4axkjkepdx.us-east-1.awsapprunner.com/health |
| **Entry point** | `dashboard_server.py` |

## The Problem

AI agents pay for x402 APIs but have **zero recourse** when services fail:
- Server errors (503, 500, 502) from overload or bugs
- Empty responses from timeouts or crashes
- Service downtime during maintenance or outages

**Your USDC is gone forever.** x402 has no refund mechanism.

## Our Solution

**API Failure Insurance for x402 Agents:**

Pay a 1% premium -> Get coverage (up to $0.1 USDC per claim) -> If API fails, instant refund

- **1% Percentage Premium** — Pay only 1% of your coverage amount
- **Up to 100x Protection** — Get 100% coverage for just 1% cost
- **Instant USDC Refunds** — Get your money back in 15-30 seconds
- **Jolt Atlas zkML Proofs** — Failure verification using ONNX model inference + SNARK proofs
- **x402 V2 Payment Flow** — Facilitator-verified payments with on-chain settlement
- **Server-Side Fraud Detection** — Server independently re-fetches merchant URL to verify claims
- **Public Auditability** — Anyone can verify we paid legitimate claims

## What's New in v2.3.0

- **AgentCore-first architecture**: AgentCore is the primary service; App Runner serves a read-only dashboard
- **x402 V2 Payment Flow**: Full facilitator-based verification and settlement via `https://x402.org/facilitator`
- **Server-Side Re-fetch Fraud Detection**: `merchant_url` is required on policies — the server independently re-fetches it during claim processing to verify the failure
- **Jolt Atlas 3-Argument Prover**: The prover binary now accepts `http_status`, `body_length`, and `coverage_amount_units` for accurate payout calculation in proofs
- **Claim Response Enrichment**: Responses include `server_verified`, `server_http_status`, and `merchant_url`
- **Agent Runner**: `agentcore_agent.py` includes autonomous x402 V2 payment helpers (`agent_purchase_policy`, `agent_submit_claim`)

## Service Layout

```
x402insurance/
├── agentcore_agent.py          AWS Bedrock AgentCore entry point (port 8080)
│                                Full service: policies, claims, proofs, payments
│                                + x402 V2 agent payment helpers
├── dashboard_server.py         App Runner entry point (port 8000)
│                                Read-only: health, discovery, static dashboard
├── app.py                      Flask factories
│   ├── create_app()            Full service factory (all blueprints + services)
│   └── create_dashboard_app()  Dashboard factory (health + discovery only)
├── blueprints/
│     policies.py    POST /insure, GET /policies, POST /renew
│     claims.py      POST /claim, GET /claims/<id>, GET /proofs/<id>
│     verify.py      POST /verify (public, rate-limited)
│     discovery.py   GET /, /.well-known/agent-card.json, /api/*
│     health.py      GET /health, /ping, /metrics, /api/reserves, /invocations
├── Core Services
│     auth/payment_verifier.py    x402 V2 facilitator verification
│     database.py                 JSONFileBackend (dev) | PostgreSQLBackend (prod)
│     blockchain.py               USDC refunds on Base via web3.py
│     proof_client.py             Jolt Atlas SNARK proof generation & verification
│     tasks/claim_processor.py    Async claims via Huey + periodic cleanup
│     tasks/reserve_monitor.py    Reserve health monitoring & alerts
│     extensions.py               Shared service instances + thread-safe metrics
├── Dockerfile                  Full service image (Jolt binary + QEMU)
└── Dockerfile.dashboard        Lightweight dashboard image (no Jolt/ONNX)
```

## x402 V2 Payment Flow

All payment-protected endpoints (`/insure`, `/claim`, `/renew`) use the x402 V2 protocol:

1. **POST without payment** — Server responds `402 Payment Required` with an `accepts` array:
   ```json
   {
     "x402Version": 2,
     "accepts": [{
       "scheme": "exact",
       "network": "eip155:8453",
       "amount": "1000",
       "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
       "payTo": "0x0e9AFe2499211c3E35e570968d1047Fcf7488c60",
       "maxTimeoutSeconds": 60
     }]
   }
   ```

2. **Sign EIP-712 typed data** with your wallet key, encoding payment details

3. **Retry with `PAYMENT-SIGNATURE` header** — Base64-encoded JSON payment payload

4. **Server verifies via facilitator** (`https://x402.org/facilitator/verify`) and settles on-chain

The `agentcore_agent.py` module provides ready-to-use helper functions:
```python
from agentcore_agent import agent_purchase_policy, agent_submit_claim

policy = agent_purchase_policy(
    server_url="http://localhost:8080",
    merchant_url="https://api.example.com/data",
    coverage_amount=0.01,
    agent_address="0xYourAgentWallet",
)

claim = agent_submit_claim(
    server_url="http://localhost:8080",
    policy_id=policy["policy_id"],
    http_status=503,
    http_body="",
    agent_address="0xYourAgentWallet",
)
```

## Server-Side Fraud Detection

When a claim is submitted, the server:
1. Validates the policy is active and `merchant_url` matches
2. **Independently re-fetches** the `merchant_url` to verify the failure
3. Compares the agent-reported failure with the server's own observation
4. Generates a Jolt Atlas SNARK proof over both data points
5. Returns `server_verified` and `server_http_status` in the response

This prevents agents from fabricating failures.

## zkML Proof Pipeline (Jolt Atlas 3-Arg)

Claims are verified using a **Jolt Atlas SNARK proof** of ONNX model inference:

```
HTTP response (status, body_length, coverage_amount_units)
    |
    v
Jolt Atlas Prover Binary (3 arguments)
    ./jolt_claims_prover <http_status> <body_length> <coverage_amount_units>
    |
    v
ONNX Classifier (claim_classifier.onnx)
    Model: 2-layer neural net trained on HTTP failure patterns
    |
    v
SNARK Proof Generation
    Proves correct inference execution (Dory commitment scheme)
    Public inputs: [is_failure, http_status, body_length, payout_amount]
    |
    v
Proof Verification + USDC Refund (if valid)
```

**Public inputs format:** `[is_failure, http_status, body_length, payout_amount]`
- `is_failure`: 1 = API failure detected, 0 = no failure
- `http_status`: Original HTTP status code (e.g. 503)
- `body_length`: Response body length in bytes
- `payout_amount`: Refund amount in micro-USDC (e.g. 10000 = $0.01)

## Quick Start

```bash
# 1. Install dependencies
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
# Copy .env.example to .env and set ALL required values:
#   BACKEND_WALLET_PRIVATE_KEY (funded with ETH + USDC)
#   BACKEND_WALLET_ADDRESS
#   BASE_RPC_URL
#   JOLT_BINARY_PATH (must point to Jolt Atlas prover binary)
#   FACILITATOR_URL (default: https://x402.org/facilitator)

# 3. Build Jolt Atlas prover (requires Rust)
cd jolt-prover && cargo build --release
# Copy target/release/jolt_claims_prover to ./jolt-atlas/

# 4. Run full service (AgentCore mode, port 8080)
python agentcore_agent.py

# 5. Run dashboard only (port 8000, no blockchain deps)
python dashboard_server.py
```

## Deployment

### AWS (Primary — Recommended)

**AgentCore** (full service):
```bash
agentcore configure -e agentcore_agent.py -r us-east-1
agentcore deploy
```

**App Runner** (dashboard):
Deploy using `Dockerfile.dashboard` — auto-deploys from `main` branch.

### Docker Compose

```bash
# Full stack: service (8080) + dashboard (8000) + PostgreSQL + Redis
docker-compose up

# Dashboard image only
docker build -f Dockerfile.dashboard -t x402-dashboard .
docker run -p 8000:8000 x402-dashboard
```

### Render (Dashboard Only — Legacy)

`render.yaml` is configured to deploy the dashboard via `dashboard_server.py`.
Set `AGENTCORE_SERVICE_URL` to point to the AgentCore service.

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/insure` | POST | x402 | Create insurance policy |
| `/claim` | POST | x402 | Submit fraud claim |
| `/renew` | POST | x402 | Extend policy duration |
| `/policies?wallet=0x...` | GET | Public | List policies by wallet |
| `/claims/<id>` | GET | Public | Get claim status |
| `/proofs/<id>` | GET | Public | Get proof data |
| `/verify` | POST | Public | Verify a SNARK proof (30/hr) |
| `/.well-known/agent-card.json` | GET | Public | Agent discovery card |
| `/api/pricing` | GET | Public | Pricing information |
| `/api/schema` | GET | Public | OpenAPI 3.0 spec |
| `/health` | GET | Public | Health check |
| `/ping` | GET | Public | Liveness probe |

## Configuration

Key environment variables (see `.env.example` for full list):

| Variable | Description | Required |
|----------|-------------|----------|
| `BACKEND_WALLET_PRIVATE_KEY` | Wallet key for USDC refunds | **Yes** |
| `BACKEND_WALLET_ADDRESS` | Corresponding wallet address | **Yes** |
| `JOLT_BINARY_PATH` | Path to Jolt Atlas prover binary | **Yes** |
| `BASE_RPC_URL` | Base chain RPC endpoint | **Yes** |
| `FACILITATOR_URL` | x402 facilitator endpoint | Yes (default: `https://x402.org/facilitator`) |
| `AGENTCORE_SERVICE_URL` | AgentCore URL (for dashboard) | No (default: App Runner URL) |
| `USDC_CONTRACT_ADDRESS` | USDC on Base Mainnet | No (default: `0x833589...`) |
| `DATABASE_URL` | PostgreSQL URL (omit for JSON files) | No |

## Testing

```bash
# Unit tests (all should pass)
pytest tests/unit/ -v

# E2E tests on Base Mainnet (requires funded wallets)
export AGENT_WALLET_ADDRESS=0x...
export AGENT_WALLET_PRIVATE_KEY=0x...
pytest tests/e2e/test_mainnet_e2e.py -v
```

Tests mock external infrastructure (blockchain RPC, facilitator HTTP API, Jolt Atlas subprocess)
but exercise all real internal code paths.

## Security

- **Claim authentication** always required (x402 payment)
- **Payment verification** via x402.org facilitator (signature, nonce, amount)
- **Server-side fraud detection** via independent merchant URL re-fetch
- **Nonce replay prevention** via database-backed nonce storage
- **Real blockchain refunds** — no mock fallbacks
- **Real SNARK proofs** — Jolt Atlas binary required, no mock mode
- **Atomic database operations** — `claim_policy()` prevents double-claiming

## Support

**Wallet:** 0x0e9AFe2499211c3E35e570968d1047Fcf7488c60
**Network:** Base Mainnet (Chain ID: 8453)
