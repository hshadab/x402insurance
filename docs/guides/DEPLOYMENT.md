# Deployment Guide

## Architecture Overview

x402 Insurance uses a two-tier deployment:

1. **AWS Bedrock AgentCore** (primary) — full insurance service on port 8080 (blockchain, proofs, payments, claims)
2. **AWS App Runner** (dashboard) — read-only public dashboard on port 8000 via `Dockerfile.dashboard`

**Dashboard URL:** https://4axkjkepdx.us-east-1.awsapprunner.com

## AWS Deployment (Recommended)

### AgentCore — Full Service

The AgentCore service runs `agentcore_agent.py` with all insurance logic: blockchain, proofs, payments, claims.

```bash
# Configure and deploy
agentcore configure -e agentcore_agent.py -r us-east-1
agentcore deploy
```

**Required environment variables** (set in AgentCore configuration):
- `BACKEND_WALLET_PRIVATE_KEY` — funded Base Mainnet wallet
- `BACKEND_WALLET_ADDRESS` — corresponding address
- `BASE_RPC_URL` — Base Mainnet RPC (Alchemy recommended)
- `JOLT_BINARY_PATH` — path to Jolt Atlas prover binary
- `FACILITATOR_URL` — default: `https://x402.org/facilitator`

The Docker image (`Dockerfile`) includes:
- Jolt Atlas binary with QEMU x86_64 emulation (for ARM64 AgentCore runtime)
- ONNX model (`claim_classifier.onnx`)
- Dory SRS file
- All Python dependencies


### App Runner — Public Dashboard

Deploy `Dockerfile.dashboard` for the public read-only dashboard. No wallet keys or blockchain deps needed.

```bash
docker build -f Dockerfile.dashboard -t x402-dashboard .

aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin 851725214068.dkr.ecr.us-east-1.amazonaws.com
docker tag x402-dashboard 851725214068.dkr.ecr.us-east-1.amazonaws.com/x402-insurance-dashboard:latest
docker push 851725214068.dkr.ecr.us-east-1.amazonaws.com/x402-insurance-dashboard:latest
```

The dashboard runs with `DASHBOARD_ONLY=true`, which skips all blockchain/prover initialization and only registers discovery + health blueprints.

## Docker Compose (Local Development)

```bash
# Full stack: service (8080) + dashboard (8000) + PostgreSQL + Redis
docker-compose up

# Development mode with hot-reload
docker-compose -f docker-compose.dev.yml up
```

Services:
- `app` — Full insurance service on port 8080
- `dashboard` — Read-only public dashboard on port 8000
- `worker` — Huey background worker
- `postgres` — PostgreSQL database
- `redis` — Rate limiting and task queue


## Blockchain Costs (Base Mainnet)

- **Gas per refund:** ~0.000001 ETH (~$0.003)
- **USDC for refunds:** depends on coverage volume

## Security Best Practices

1. Never commit secrets — use environment variables
2. Use separate wallets for dev (Base Sepolia) and prod (Base Mainnet)
3. Limit wallet funds to expected refund volume
4. Set `CORS_ORIGINS` to specific domains in production (not `*`)
5. Enable rate limiting with Redis in production
