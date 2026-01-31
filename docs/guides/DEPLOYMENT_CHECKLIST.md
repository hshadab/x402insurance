# Deployment Checklist

Use this checklist for deploying or redeploying the x402 Insurance service.

## Architecture

| Component | Platform | Entry Point | Port |
|-----------|----------|-------------|------|
| **Primary service** | AWS Bedrock AgentCore | `agentcore_agent.py` | 8080 |
| **Dashboard** | AWS App Runner (ECR) | `dashboard_server.py` | 8000 |

## Pre-Deployment

- [ ] **Verify AWS credentials**
  ```bash
  aws sts get-caller-identity  # Account: 851725214068
  ```

- [ ] **Verify wallet has funds** (for AgentCore service)
  - [ ] ETH for gas: ~0.005 ETH minimum
  - [ ] USDC for refunds: based on expected coverage
  - [ ] Check balance at https://basescan.org

- [ ] **Test locally**
  ```bash
  # Full service
  python agentcore_agent.py

  # Dashboard only
  python dashboard_server.py
  # Test at http://localhost:8000
  ```

## AgentCore Deployment (Full Service)

- [ ] **Configure and deploy**
  ```bash
  agentcore configure -e agentcore_agent.py -r us-east-1
  agentcore deploy
  ```

- [ ] **Set environment variables** in AgentCore configuration:
  - `BACKEND_WALLET_PRIVATE_KEY` — funded Base Mainnet wallet
  - `BACKEND_WALLET_ADDRESS` — corresponding address
  - `BASE_RPC_URL` — Base Mainnet RPC endpoint
  - `JOLT_BINARY_PATH` — path to Jolt Atlas prover binary
  - `FACILITATOR_URL` — default: `https://x402.org/facilitator`

## Dashboard Deployment (App Runner via ECR)

- [ ] **Build the dashboard image**
  ```bash
  docker build -f Dockerfile.dashboard -t x402-dashboard .
  ```

- [ ] **Test locally before pushing**
  ```bash
  docker run --rm -p 8001:8000 x402-dashboard
  curl http://localhost:8001/ping    # Should return {"status":"Healthy",...}
  curl http://localhost:8001/health  # Should return {"status":"healthy","mode":"dashboard-readonly",...}
  ```

- [ ] **Login to ECR**
  ```bash
  aws ecr get-login-password --region us-east-1 | \
    docker login --username AWS --password-stdin 851725214068.dkr.ecr.us-east-1.amazonaws.com
  ```

- [ ] **Push to ECR**
  ```bash
  docker tag x402-dashboard 851725214068.dkr.ecr.us-east-1.amazonaws.com/x402-insurance-dashboard:latest
  docker push 851725214068.dkr.ecr.us-east-1.amazonaws.com/x402-insurance-dashboard:latest
  ```

- [ ] **Trigger App Runner redeployment**
  ```bash
  aws apprunner start-deployment \
    --service-arn arn:aws:apprunner:us-east-1:851725214068:service/x402insurance/a54c141ba18a4b59b2adfb21bff52730 \
    --region us-east-1
  ```

- [ ] **Wait for deployment to complete**
  ```bash
  # Poll until status is RUNNING
  aws apprunner describe-service \
    --service-arn arn:aws:apprunner:us-east-1:851725214068:service/x402insurance/a54c141ba18a4b59b2adfb21bff52730 \
    --region us-east-1 --query 'Service.Status' --output text
  ```

## Post-Deployment Verification

- [ ] **Check dashboard health**
  ```bash
  curl https://4axkjkepdx.us-east-1.awsapprunner.com/health
  # Expected: {"status":"healthy","mode":"dashboard-readonly","checks":{"dashboard":{"status":"operational"}}}
  ```

- [ ] **Check dashboard UI**
  - Visit https://4axkjkepdx.us-east-1.awsapprunner.com/
  - Title should show "NovNet x402 Insurance - Service Dashboard (Read-Only)"

- [ ] **Check agent discovery**
  ```bash
  curl https://4axkjkepdx.us-east-1.awsapprunner.com/.well-known/agent-card.json
  ```

- [ ] **Check API endpoints**
  ```bash
  curl https://4axkjkepdx.us-east-1.awsapprunner.com/api
  curl https://4axkjkepdx.us-east-1.awsapprunner.com/api/pricing
  ```

- [ ] **Run unit tests**
  ```bash
  pytest tests/unit/ -v
  ```

## Troubleshooting

### App Runner deployment rolls back

1. **Container crashes on startup** — check that `Dockerfile.dashboard` copies all required files (`utils.py`, `extensions.py`, `config.py`, `app.py`, `dashboard_server.py`, `blueprints/`, `static/`)
2. **Health check fails** — App Runner uses `/ping` as the health check path; verify the container responds to it
3. **ECR access denied** — verify the `AppRunnerECRAccessRole` IAM role has `ecr:GetDownloadUrlForLayer`, `ecr:BatchGetImage`, `ecr:GetAuthorizationToken`

### Check deployment operation status

```bash
aws apprunner list-operations \
  --service-arn arn:aws:apprunner:us-east-1:851725214068:service/x402insurance/a54c141ba18a4b59b2adfb21bff52730 \
  --region us-east-1 --query 'OperationSummaryList[0]'
```

## Key References

| Resource | Value |
|----------|-------|
| **App Runner Service ARN** | `arn:aws:apprunner:us-east-1:851725214068:service/x402insurance/a54c141ba18a4b59b2adfb21bff52730` |
| **ECR Repository** | `851725214068.dkr.ecr.us-east-1.amazonaws.com/x402-insurance-dashboard` |
| **ECR Access Role** | `arn:aws:iam::851725214068:role/AppRunnerECRAccessRole` |
| **Dashboard URL** | https://4axkjkepdx.us-east-1.awsapprunner.com |
| **AgentCore ARN** | `arn:aws:bedrock-agentcore:us-east-1:851725214068:runtime/agentcore_agent-mHkElJ7QNo` |
