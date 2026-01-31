# Deployment Guide

## Architecture Overview

x402 Insurance uses a two-tier deployment:

1. **AWS Bedrock AgentCore** (primary) — runs the full insurance service on port 8080
2. **App Runner / Render** (dashboard) — serves a read-only monitoring dashboard on port 8000

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

### App Runner — Dashboard

Deploy using `Dockerfile.dashboard` for a lightweight read-only dashboard. The dashboard image is pushed to ECR and App Runner pulls from there.

**ECR repository:** `851725214068.dkr.ecr.us-east-1.amazonaws.com/x402-insurance-dashboard`

```bash
# Build the dashboard image
docker build -f Dockerfile.dashboard -t x402-dashboard .

# Push to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin 851725214068.dkr.ecr.us-east-1.amazonaws.com
docker tag x402-dashboard 851725214068.dkr.ecr.us-east-1.amazonaws.com/x402-insurance-dashboard:latest
docker push 851725214068.dkr.ecr.us-east-1.amazonaws.com/x402-insurance-dashboard:latest

# Trigger App Runner redeployment
aws apprunner start-deployment \
  --service-arn arn:aws:apprunner:us-east-1:851725214068:service/x402insurance/a54c141ba18a4b59b2adfb21bff52730 \
  --region us-east-1
```

**App Runner service:** `x402insurance` (service ID: `a54c141ba18a4b59b2adfb21bff52730`)
**ECR access role:** `AppRunnerECRAccessRole`
**Health check path:** `/ping`
**Port:** 8000

The dashboard uses a lightweight health blueprint (`dashboard_health_bp`) that returns `{"status": "healthy", "mode": "dashboard-readonly"}` without checking blockchain, database, or prover subsystems.

**Optional environment variables:**
- `AGENTCORE_SERVICE_URL` — URL of the AgentCore service
- `ENV=production`

No wallet keys, blockchain deps, or Jolt binary needed.

## Docker Compose (Local Development)

```bash
# Full stack: service (8080) + dashboard (8000) + PostgreSQL + Redis
docker-compose up

# Development mode with hot-reload
docker-compose -f docker-compose.dev.yml up
```

Services:
- `app` — Full insurance service on port 8080
- `dashboard` — Read-only dashboard on port 8000
- `worker` — Huey background worker
- `postgres` — PostgreSQL database
- `redis` — Rate limiting and task queue

## Render (Dashboard Only — Legacy)

`render.yaml` deploys the dashboard via `dashboard_server.py`. This is suitable for hosting the public-facing dashboard but does not run the full service.

Set `AGENTCORE_SERVICE_URL` in the Render dashboard to point to the AgentCore service.

## Blockchain Costs (Base Mainnet)

- **Gas per refund:** ~0.000001 ETH (~$0.003)
- **USDC for refunds:** depends on coverage volume

## Security Best Practices

1. Never commit secrets — use environment variables
2. Use separate wallets for dev (Base Sepolia) and prod (Base Mainnet)
3. Limit wallet funds to expected refund volume
4. Set `CORS_ORIGINS` to specific domains in production (not `*`)
5. Enable rate limiting with Redis in production
