# Production Setup Guide

## Architecture

- **Primary service**: AWS Bedrock AgentCore (`agentcore_agent.py`, port 8080)
- **Dashboard**: AWS App Runner via ECR (`dashboard_server.py`, port 8000, read-only)

## Prerequisites

- Python 3.11+
- Access to Base Mainnet RPC (Alchemy recommended)
- USDC on Base Mainnet for reserves
- ETH on Base Mainnet for gas fees
- (Optional) PostgreSQL database
- (Optional) Redis for distributed rate limiting

## Step 1: Environment Configuration

```bash
cp .env.example .env.production
```

Edit `.env.production`:

```bash
# App Configuration
ENV=production
DEBUG=false
LOG_LEVEL=INFO

# Database (recommended for production)
DATABASE_URL=postgresql://username:password@host:port/database

# Blockchain (REQUIRED)
BASE_RPC_URL=https://base-mainnet.g.alchemy.com/v2/YOUR_ALCHEMY_KEY
USDC_CONTRACT_ADDRESS=0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
BACKEND_WALLET_PRIVATE_KEY=0xYOUR_PRIVATE_KEY_HERE
BACKEND_WALLET_ADDRESS=0xYOUR_WALLET_ADDRESS_HERE

# Jolt Atlas
JOLT_BINARY_PATH=./jolt-atlas/jolt_claims_prover

# Rate Limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_STORAGE_URL=redis://localhost:6379/0

# Payment
FACILITATOR_URL=https://x402.org/facilitator
PAYMENT_MAX_AGE_SECONDS=300

# Security
CORS_ORIGINS=https://yourdomain.com
```

## Step 2: Deploy AgentCore (Full Service)

```bash
# Build and deploy to AgentCore
agentcore configure -e agentcore_agent.py -r us-east-1
agentcore deploy
```

Or with Docker:
```bash
docker build -t x402insurance .
docker run -p 8080:8080 --env-file .env.production x402insurance
```

## Step 3: Deploy Dashboard (App Runner via ECR)

```bash
# Build
docker build -f Dockerfile.dashboard -t x402-dashboard .

# Test locally
docker run --rm -p 8001:8000 x402-dashboard
curl http://localhost:8001/health  # {"status":"healthy","mode":"dashboard-readonly",...}

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

The dashboard uses `dashboard_health_bp` (a lightweight health blueprint) instead of the full `health_bp`, so `/health` returns a simple healthy status without checking blockchain, database, or prover subsystems.

## Step 4: Fund Wallet

Minimum balances:
- **ETH**: 0.01 ETH for gas (~50-100 transactions)
- **USDC**: based on expected coverage volume

Reserve ratio recommendation: maintain 2x USDC relative to active coverage.

## Step 5: Verify

```bash
# AgentCore health
curl http://localhost:8080/health

# Dashboard health (lightweight — no blockchain/prover checks)
curl https://4axkjkepdx.us-east-1.awsapprunner.com/health
# Returns: {"status":"healthy","mode":"dashboard-readonly","checks":{"dashboard":{"status":"operational"}}}

# Agent discovery
curl https://4axkjkepdx.us-east-1.awsapprunner.com/.well-known/agent-card.json
```

## Step 6: Run Tests

```bash
pytest tests/unit/ -v
```

## Security Checklist

- [ ] `.env` files not committed to git
- [ ] `CORS_ORIGINS` configured (not `*`)
- [ ] PostgreSQL using strong password
- [ ] Private key stored as environment variable only
- [ ] HTTPS/SSL enabled
- [ ] Rate limiting enabled
- [ ] Reserve monitoring alerts configured
