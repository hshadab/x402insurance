# Production Ready Status

**Date**: 2026-01-31
**Version**: 2.3.0
**Status**: FULLY OPERATIONAL

## Architecture

| Component | Entry Point | Port | Role |
|-----------|-------------|------|------|
| **AWS Bedrock AgentCore** | `agentcore_agent.py` | 8080 | Primary service — all insurance logic |
| **AWS App Runner** | `dashboard_server.py` | 8000 | Read-only monitoring dashboard |

## Live Deployment

| | |
|---|---|
| **AgentCore ARN** | `arn:aws:bedrock-agentcore:us-east-1:851725214068:runtime/agentcore_agent-mHkElJ7QNo` |
| **Dashboard** | https://4axkjkepdx.us-east-1.awsapprunner.com |
| **Network** | Base Mainnet (Chain ID: 8453) |
| **Database** | JSON backend (operational) |
| **Payment Mode** | Facilitator (x402.org) |
| **Prover** | Jolt Atlas SNARK (binary compiled, operational) |

## System Components

### Jolt Atlas Proofs (REAL)
- **Binary**: `jolt-prover/target/release/jolt_claims_prover` (ELF x86-64 executable)
- **Source**: `jolt-prover/` (Rust, compiled from source)
- **Technology**: Jolt Atlas SNARK proofs over ONNX model inference (Dory commitment scheme)
- **Interface**: 3-argument prover (`http_status`, `body_length`, `coverage_amount_units`)
- **Model**: `models/claim_classifier.onnx` — 2-layer MLP (4-8-2), SHA-256 verified at startup

### USDC Refunds (REAL)
- **Network**: Base Mainnet (Chain ID: 8453)
- **Token**: USDC (`0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`)
- **Mechanism**: Real ERC-20 `transfer()` calls via `web3.py`
- **No mock mode**: If the wallet is unfunded or the RPC is down, refunds fail

### x402 V2 Payment Verification (REAL)
- **Mode**: Facilitator-based (`https://x402.org/facilitator`)
- **Flow**: Agent signs EIP-712 -> server calls facilitator `/verify` -> facilitator `/settle`
- **Nonce replay prevention**: Database-backed nonce storage

### Server-Side Fraud Detection (REAL)
- Server independently re-fetches `merchant_url` during claim processing
- Returns `server_verified` and `server_http_status` in claim response

## What Is NOT Mocked

1. **No mock proofs** — Jolt Atlas binary required; if missing, server refuses to start
2. **No mock transactions** — Real USDC on Base Mainnet
3. **No mock signatures** — x402 facilitator verification
4. **No mock fraud detection** — Server actually makes HTTP requests to merchant URLs
5. **No demo mode** — There is no flag to run the system with fake data

## Test Results

- **46 unit tests passing** (as of 2026-01-31)
- Unit tests mock external infrastructure but exercise all internal code paths

## Verification

```bash
# Check health (AgentCore)
curl http://localhost:8080/health | python3 -m json.tool

# Check health (Dashboard)
curl https://4axkjkepdx.us-east-1.awsapprunner.com/health

# Run unit tests
pytest tests/unit/ -v
```
