# x402 Insurance

**Zero-Knowledge Proof Verified Insurance Against x402 Merchant Fraud**

Protect your micropayment API calls with instant, cryptographically-verified refunds on Base Mainnet.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![x402 Protocol](https://img.shields.io/badge/x402-Compatible-blue)](https://github.com/coinbase/x402)
[![A2A Protocol](https://img.shields.io/badge/A2A-Discoverable-green)](https://github.com/coinbase/agentkit)

## Status

🟢 **Production Ready** (Base Mainnet) | 🤖 **Agent Discoverable** | 🌐 **x402 Bazaar Ready**
Version: 1.0.0
Date: 2025-11-06

## The Problem

AI agents pay for x402 APIs but have **zero recourse** when merchants fail:
- Return empty responses (HTTP 200 with no data)
- Fail with server errors (503, 500, 502)
- Go offline after receiving payment

**Your USDC is gone forever.** x402 has no refund mechanism. ([GitHub Issue #508](https://github.com/coinbase/x402/issues/508))

## Our Solution

**Micropayment Insurance for x402 Agents:**

Pay a 1% premium → Get coverage (up to $0.1 USDC per claim) → If merchant fails, instant refund

✅ **1% Percentage Premium** - Pay only 1% of your coverage amount
✅ **Up to 100x Protection** - Get 100% coverage for just 1% cost
✅ **Instant USDC Refunds** - Get your money back in 15-30 seconds
✅ **Zero-Knowledge Proofs** - Fraud verification using zkEngine (Nova/Arecibo SNARKs)
✅ **Agent Discoverable** - Full A2A and x402 Bazaar compatibility
✅ **Public Auditability** - Anyone can verify we paid legitimate claims
✅ **Privacy-Preserving** - Merchant identity & API content stay private
✅ **x402 Native** - Seamless integration with x402 payment protocol

## How It Works

### The Insurance Flow

```
1. Agent chooses coverage amount (e.g., 0.01 USDC) for their API call
   → Pays 1% premium TO US (e.g., 0.0001 USDC)
   → Policy created for 24 hours
                    ↓
2. Agent pays X USDC TO MERCHANT (via x402)
   → Merchant receives payment (they keep it regardless)
   → Example: Agent pays 0.01 USDC for API call
                    ↓
3. Merchant fails: Returns 503 error / empty response / goes offline
                    ↓
4. Agent submits fraud claim with HTTP response data
                    ↓
5. zkEngine generates cryptographic proof (~15s)
   → Math proves: "status >= 500 AND payout ≤ coverage"
                    ↓
6. Proof verified → We pay agent X USDC FROM OUR RESERVES
   → Merchant keeps their payment, we absorb the loss
   → Example: Agent receives 0.01 USDC refund (100% of coverage)
                    ↓
7. Public proof published on-chain
   → Anyone can verify we paid a legitimate claim
```

**Pricing Model:**
- **Percentage Premium**: 1% of coverage amount
- **Max Coverage**: 0.1 USDC per claim (ideal for micropayment protection)
- **Duration**: 24 hours

**Examples:**
- **0.01 USDC coverage** → 0.0001 USDC premium (1%) = 100x protection
- **0.05 USDC coverage** → 0.0005 USDC premium (1%) = 100x protection
- **0.1 USDC coverage** → 0.001 USDC premium (1%) = 100x protection

**Important:** This is insurance (we pay from reserves), not chargebacks (reversing merchant payment). From the agent's perspective, the outcome is the same: money back when merchant fails.

### Fraud Detection Rules

**We issue refunds when merchants:**
- Return HTTP status >= 500 (server errors: 500, 502, 503, 504)
- Return empty response body (0 bytes)
- Become unresponsive or timeout

**We do NOT refund when:**
- HTTP 200-299 (successful responses, even if content is bad)
- HTTP 400-499 (client errors - agent's fault)
- Response has content (even if it's garbage)

### Why Zero-Knowledge Proofs?

**Problem:** How do we prove merchant failed without exposing private data?

**Solution:** zkEngine SNARKs prove the fraud mathematically

**What gets proven (public):**
- ✅ HTTP status was >= 500 OR body length was 0
- ✅ Fraud detection logic executed correctly
- ✅ Payout amount ≤ policy coverage
- ✅ Agent had an active policy

**What stays private (hidden):**
- 🔒 Actual API response content
- 🔒 Merchant URL/identity (only hash visible)
- 🔒 HTTP headers and metadata
- 🔒 Business logic details

**Three Key Benefits:**

1. **Public Auditability** - Anyone can verify we're paying legitimate claims (prevents us from fraud)
2. **Privacy Preservation** - Merchant identity protected, no public shaming
3. **Trustless Verification** - Math proves fraud, not our word (future: fully on-chain)

**Technology:** Nova IVC (Incremental Verifiable Computation) + Spartan SNARKs on Bn256 curve

## Quick Start

```bash
# 1. Install dependencies
cd /home/hshadab/x402insurance
source venv/bin/activate
pip install -r requirements.txt
pip install /tmp/x402/python/x402

# 2. Configure environment (already done for Base Mainnet)
# .env is configured with:
#   - Base Mainnet RPC (Alchemy)
#   - USDC contract address
#   - Backend wallet credentials

# 3. Fund wallet (REQUIRED)
# Send ETH for gas: 0xba72eD392dB9d67813D68D562D2d67c36fFF566b
# Send USDC for refunds: 0xba72eD392dB9d67813D68D562D2d67c36fFF566b

# 4. Run server
python server.py
```

Server runs on **http://localhost:8000**

📖 **Full Documentation:** See `AGENT_DISCOVERY.md`, `DEPLOYMENT.md` and other guides

## 🤖 Agent Discovery

Your service is fully discoverable by autonomous agents via:

### A2A Protocol (Agent-to-Agent)
```bash
# Discover service via agent card
curl https://your-domain.com/.well-known/agent-card.json

# Returns complete service metadata:
# - Identity and capabilities
# - All available services with schemas
# - x402 payment requirements
# - Performance metrics
```

### x402 Bazaar
Ready for listing in the x402 Bazaar discovery service:
- ✅ Complete input/output JSON schemas
- ✅ Rich metadata (category, tags, pricing)
- ✅ x402Version field
- ✅ Performance metrics
- ✅ Automatic registration via CDP facilitator

### Discovery Endpoints

| Endpoint | Description |
|----------|-------------|
| `/.well-known/agent-card.json` | A2A agent card (complete service discovery) |
| `/api` | API information & x402 metadata |
| `/api/pricing` | Detailed pricing information |
| `/api/schema` | OpenAPI 3.0 specification (JSON/YAML) |
| `/api/dashboard` | Live statistics and metrics |

See [AGENT_DISCOVERY.md](AGENT_DISCOVERY.md) for complete integration guide.

## API Endpoints

### 1. Create Insurance Policy (x402 Payment Required)

**Important:** This endpoint requires a valid x402 payment. Without payment, you'll receive a 402 Payment Required response with payment details.

```bash
POST /insure
Headers:
  X-PAYMENT: <base64-encoded x402 payment>
  Content-Type: application/json

Body:
{
  "merchant_url": "https://api.example.com",
  "coverage_amount": 10000
}

Response (with valid payment):
{
  "policy_id": "uuid",
  "agent_address": "0x...",
  "coverage_amount": 10000,
  "premium": 1000,
  "status": "active",
  "expires_at": "2025-11-07T10:00:00"
}

Response (without payment):
{
  "x402Version": 1,
  "accepts": [{
    "network": "base",
    "maxAmountRequired": "1000000000",
    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "payTo": "0xba72eD392dB9d67813D68D562D2d67c36fFF566b",
    ...
  }],
  "error": "No X-PAYMENT header provided"
}
```

### 2. Submit Fraud Claim

```bash
POST /claim
Body:
{
  "policy_id": "uuid",
  "http_response": {
    "status": 503,
    "body": "",
    "headers": {}
  }
}

Response:
{
  "claim_id": "uuid",
  "proof": "0xabc...",
  "public_inputs": [1, 503, 0, 10000],
  "payout_amount": 10000,
  "refund_tx_hash": "0x...",
  "status": "paid",
  "proof_url": "/proofs/uuid"
}
```

### 3. Verify Proof (Public)

```bash
POST /verify
Body:
{
  "proof": "0xabc...",
  "public_inputs": [1, 503, 0, 10000]
}

Response:
{
  "valid": true,
  "fraud_detected": true,
  "payout_amount": 10000
}
```

### 4. Get Proof Data (Public)

```bash
GET /proofs/<claim_id>

Response:
{
  "claim_id": "uuid",
  "proof": "0xabc...",
  "public_inputs": [1, 503, 0, 10000],
  "http_status": 503,
  "payout_amount": 10000,
  "refund_tx_hash": "0x...",
  ...
}
```

## Agent Example

```python
import httpx

# 1. Buy insurance
policy = httpx.post(
    "http://localhost:8000/insure",
    headers={"X-Payment": "token=xyz,amount=1000,signature=abc"},
    json={"merchant_url": "https://api.com", "coverage": 10000}
).json()

# 2. Make API call
response = httpx.get("https://api.com/data")

# 3. If fraud, file claim
if response.status_code >= 400 or response.text == "":
    claim = httpx.post(
        "http://localhost:8000/claim",
        json={
            "policy_id": policy["policy_id"],
            "http_response": {
                "status": response.status_code,
                "body": response.text,
                "headers": dict(response.headers)
            }
        }
    ).json()

    print(f"Refund issued: {claim['refund_tx_hash']}")
```

## Testing Locally

```bash
# Test with curl
curl -X POST http://localhost:8000/insure \
  -H "X-Payment: token=test,amount=1,signature=test" \
  -H "Content-Type: application/json" \
  -d '{"merchant_url": "https://api.com", "coverage_amount": 50}'

# File a test claim
curl -X POST http://localhost:8000/claim \
  -H "Content-Type: application/json" \
  -d '{
    "policy_id": "POLICY_ID_FROM_ABOVE",
    "http_response": {
      "status": 503,
      "body": "",
      "headers": {}
    }
  }'
```

## 📚 Documentation

- **[README.md](README.md)** (this file) - Overview and quick start
- **[AGENT_DISCOVERY.md](AGENT_DISCOVERY.md)** - Agent integration guide (A2A, x402 Bazaar)
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Deployment guide for Render
- **[DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md)** - Step-by-step deployment checklist
- **[openapi.yaml](openapi.yaml)** - OpenAPI 3.0 specification
- **[render.yaml](render.yaml)** - Render deployment configuration

## Architecture

```
┌─────────────────┐
│  x402 Client    │
│  (Agent)        │
└────────┬────────┘
         │ X-PAYMENT header
         ▼
┌─────────────────┐
│ Flask Server    │
│ (x402 middleware)│
└──┬───────┬──────┘
   │       │
   ▼       ▼
┌────┐  ┌──────────┐
│zkEng│ │Blockchain│
│Nova │ │Base USDC │
└────┘  └──────────┘
```

## Technology Stack

- **x402 Protocol** - Decentralized HTTP payments (Coinbase)
- **zkEngine** - Nova/Arecibo zero-knowledge proofs
- **Base Mainnet** - Ethereum L2 for USDC refunds
- **Alchemy** - Reliable RPC provider
- **Flask** - Minimal Python web framework

## Deployment

Ready to deploy to Render.com:

1. Push to GitHub
2. Connect repository to Render
3. Set environment variables from .env
4. Deploy!

**Cost:** $7-25/month

## Security

⚠️ **NEVER commit .env to git** - contains private keys
🟢 **Base Mainnet** - Production blockchain
✅ **Zero-knowledge proofs** - Protect merchant privacy
✅ **Public auditability** - All claims verifiable

## Why This Matters

### The Unsolved Problem

**[GitHub Issue #508](https://github.com/coinbase/x402/issues/508)** (Open since 2024)

Kyle Den Hartog (Brave Security) identified a critical gap:
> "The agent needs a way to request a chargeback as they paid for a product they didn't receive."

**Current situation:**
- x402 has NO refund mechanism when merchants fail
- Agents have NO protection against merchant fraud
- USDC payments are irreversible
- Community has been asking for a solution for over a year

**Our solution:** First production implementation of merchant failure insurance for x402

### What Makes This Different

**Insurance (what we built):**
- Agent pays premium to us → We pay refund from our reserves
- Merchant keeps their original payment
- We absorb the financial loss

**vs. Chargebacks (what doesn't exist):**
- Would reverse merchant's payment directly
- Merchant loses what they received
- Requires protocol-level support (x402 doesn't have this)

**Why this matters:** We provide the OUTCOME of chargebacks (agent gets money back) through an insurance mechanism. Same result for agents, different mechanics.

### Real-World Impact

**Recent incidents:**
- October 2025: 402Bridge security breach (USDC disappeared)
- GitHub Issue #545: Python middleware producing 500 errors
- Twitter reports: "x402 protocol API experiencing frequent lags"

**Without insurance:**
- Agent loses 0.01-0.1 USDC per failed API call → funds gone forever
- No recourse, no dispute, no refund
- Add up over many calls = significant losses

**With our insurance:**
- Agent pays 1% premium for protection (e.g., 0.0001 USDC to protect 0.01 USDC)
- If merchant fails: Agent files claim → zkEngine proof → automatic refund in 30 seconds
- Cryptographic proof of fraud → no disputes, no manual review
- Public auditability → anyone can verify we're legitimate
- Only 1% overhead for complete protection

### Differentiation

**vs. x402-secure (t54.ai):**
- **They do:** Pre-transaction risk assessment (prevention)
  - Analyze AI agent context, prompts, model details
  - Assign risk scores (low/medium/high)
  - Prevent fraud before it happens
- **We do:** Post-transaction protection (recovery)
  - Pay refunds when merchant actually fails
  - Prove fraud with zero-knowledge proofs
  - Recover lost funds
- **Relationship:** Complementary, not competitive - use both for maximum protection!

**vs. Traditional insurance:**
- ✅ Instant settlement (30s vs 30 days)
- ✅ No human review required (math proves fraud)
- ✅ Public verifiability (anyone can audit claims)
- ✅ Privacy-preserving (zkp hides sensitive data)
- ✅ Trustless (future: fully on-chain automation)

## Support

**Wallet:** 0xba72eD392dB9d67813D68D562D2d67c36fFF566b
**Network:** Base Mainnet (Chain ID: 8453)
**Block Explorer:** https://basescan.org

**Documentation:**
- Full positioning: See `POSITIONING.md` for market analysis
- GitHub Issue: https://github.com/coinbase/x402/issues/508
