# Deployment Summary

**x402 Insurance v2.3.0** — AgentCore-first Architecture

## Architecture

| Component | Entry Point | Port | Role |
|-----------|-------------|------|------|
| **AgentCore** | `agentcore_agent.py` | 8080 | Primary service — all insurance logic, blockchain, proofs, payments |
| **App Runner** | `dashboard_server.py` | 8000 | Read-only dashboard — health, discovery, static UI |

## Live Deployment

- **AgentCore ARN**: `arn:aws:bedrock-agentcore:us-east-1:851725214068:runtime/agentcore_agent-mHkElJ7QNo`
- **Dashboard URL**: https://4axkjkepdx.us-east-1.awsapprunner.com
- **Region**: us-east-1
- **Network**: Base Mainnet (Chain ID: 8453)

## Docker Images

| Image | Dockerfile | Contents |
|-------|-----------|----------|
| Full service | `Dockerfile` | Python + Jolt binary + QEMU + ONNX model + all deps |
| Dashboard | `Dockerfile.dashboard` | Python + Flask + static files only |

## Quick Deploy

```bash
# AgentCore
agentcore configure -e agentcore_agent.py -r us-east-1
agentcore deploy

# Docker Compose (both services)
docker-compose up

# Dashboard only
docker build -f Dockerfile.dashboard -t x402-dashboard .
docker run -p 8000:8000 x402-dashboard
```

## Environment Variables

### AgentCore (full service)
- `BACKEND_WALLET_PRIVATE_KEY` — **required**
- `BACKEND_WALLET_ADDRESS` — **required**
- `BASE_RPC_URL` — **required**
- `JOLT_BINARY_PATH` — **required**
- `FACILITATOR_URL` — default: `https://x402.org/facilitator`
- `DATABASE_URL` — optional (PostgreSQL)

### Dashboard
- `AGENTCORE_SERVICE_URL` — URL of AgentCore service
- `ENV=production`

## Verification

```bash
curl http://localhost:8080/health   # AgentCore
curl http://localhost:8000/health   # Dashboard
pytest tests/unit/ -v               # Tests
```
