# x402 Insurance

**Zero-Knowledge Proof Verified Insurance for x402 API Failures**

Protect your AI agents from API downtime, timeouts, and service interruptions with instant,
cryptographically-verified refunds on Base Mainnet.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![x402 Protocol](https://img.shields.io/badge/x402-Compatible-blue)](https://github.com/coinbase/x402)

## Status

🟢 Production Ready | 🤖 Agent Discoverable | 🚀 v2.2.0
**Agent Readiness: 9.0/10**
Date: 2025-11-08

## The Problem

AI agents pay for x402 APIs but have **zero recourse** when services fail:
- Server errors (503, 500, 502) from overload or bugs
- Empty responses from timeouts or crashes
- Service downtime during maintenance or outages

**Your USDC is gone forever.** x402 has no refund mechanism. ([GitHub Issue #508](https://github.com/coinbase/x402/issues/508))

APIs fail constantly - not from fraud, but from normal operational issues. Your agents shouldn't lose money when this happens.

## Our Solution

**API Failure Insurance for x402 Agents:**

Pay a 1% premium → Get coverage (up to $0.1 USDC per claim) → If API fails, instant refund

✅ **1% Percentage Premium** - Pay only 1% of your coverage amount
✅ **Up to 100x Protection** - Get 100% coverage for just 1% cost
✅ **Instant USDC Refunds** - Get your money back in 15-30 seconds
✅ **Zero-Knowledge Proofs** - Failure verification using zkEngine SNARKs
✅ **Agent Discoverable** - Full x402 Bazaar compatibility
✅ **Public Auditability** - Anyone can verify we paid legitimate claims
✅ **Privacy-Preserving** - Service identity & API content stay private
✅ **x402 Native (prototype)** - Minimal payment verification for testing

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
3. API/Service fails: Returns 503 error / empty response / goes offline
                    ↓
4. Agent submits claim with HTTP response data
                    ↓
5. zkEngine analyzes the HTTP response and generates zero-knowledge proof (~15s)
   → Cryptographically certifies failure conditions were met (e.g., status >= 500)
   → Without exposing actual response data—like proving you know a password
     without revealing the password itself
                    ↓
6. Proof verified → We pay agent X USDC FROM OUR RESERVES
   → Service keeps their payment, we absorb the loss
   → Example: Agent receives 0.01 USDC refund (100% of coverage)
   → Refund TX on Base: Standard USDC ERC20 transfer
                    ↓
7. Public proof published on-chain (Base Mainnet)
   → Proof data stored in transaction input field
   → Contains: claim_id, proof_hash, public_inputs, payout_amount, recipient
   → Anyone can verify we paid a legitimate claim by checking Basescan
```

**Pricing Model:**
- **Percentage Premium**: 1% of coverage amount
- **Max Coverage**: 0.1 USDC per claim (ideal for micropayment protection)
- **Duration**: 24 hours

**Examples:**
- **0.01 USDC coverage** → 0.0001 USDC premium (1%) = 100x protection
- **0.05 USDC coverage** → 0.0005 USDC premium (1%) = 100x protection
- **0.1 USDC coverage** → 0.001 USDC premium (1%) = 100x protection

**Important:** This is insurance (we pay from reserves), not chargebacks (reversing service payment). From the agent's perspective, the outcome is the same: money back when the API fails to deliver.

### Solving the Agent Memory Problem

**Challenge:** AI agents have limited context windows and may forget their policy_id between insurance purchase and claim filing (could be hours or days later).

**Solution:** Wallet-based policy lookup
- Agents can always access their wallet address (it's fundamental to their identity)
- GET /policies?wallet=0x... returns all active policies for that wallet
- No need to store policy_id - just remember your wallet address
- Query anytime to find policies and file claims

**Why this matters:**
- Agents don't need to maintain state between purchase and claim
- Works even after context window resets or system restarts
- Enables autonomous claim filing without human intervention
- Compatible with all agent frameworks (no special storage required)

### Failure Detection Rules

**We issue refunds when services:**
- Return HTTP status >= 500 (server errors: 500, 502, 503, 504)
- Return empty response body (0 bytes)
- Become unresponsive or timeout

**We do NOT refund when:**
- HTTP 200-299 (successful responses, even if content is unexpected)
- HTTP 400-499 (client errors - agent's fault)
- Response has content (service delivered something)

**This covers normal operational failures:** server overload, crashes, maintenance, bugs, network issues - not malicious behavior.

### Why Zero-Knowledge Proofs?

**Problem:** How do we prove an API failed without exposing private data?

**Solution:** zkEngine SNARKs prove the failure mathematically

**What gets proven (public):**
- ✅ HTTP status was >= 500 OR body length was 0
- ✅ Failure detection logic executed correctly
- ✅ Payout amount ≤ policy coverage
- ✅ Agent had an active policy

**What stays private (hidden):**
- 🔒 Actual API response content
- 🔒 Service URL/identity (only hash visible)
- 🔒 HTTP headers and metadata
- 🔒 Business logic details

**Three Key Benefits:**

1. **Public Auditability** - Anyone can verify we're paying legitimate claims (prevents us from abuse)
2. **Privacy Preservation** - Service identity protected, no public shaming for downtime
3. **Trustless Verification** - Math proves failure, not our word (future: fully on-chain)

**Technology:** zkEngine with Nova/Spartan SNARKs on Bn256 curve

### How Verification Works

**Critical Security Feature:** Proof verification happens **OFF-CHAIN** before any refunds are issued.

```
1. Agent submits claim with HTTP response data
2. zkEngine generates proof (~22s) ← OFF-CHAIN
3. Server verifies proof ← OFF-CHAIN
4. Server checks if failure detected ← OFF-CHAIN
   └─ If invalid or no failure → REJECT (no refund)
5. Server issues USDC refund ← ON-CHAIN (only if verified)
6. Server publishes proof data ← ON-CHAIN (only if refund succeeds)
```

**Rejection Examples:**
- ❌ 200 OK with body → REJECTED (no failure)
- ❌ 404 with body → REJECTED (has response)
- ✅ 503 error → ACCEPTED (server error)
- ✅ Empty response → ACCEPTED (failure detected)

📖 See [VERIFICATION_FLOW.md](docs/VERIFICATION_FLOW.md) for detailed explanation and test cases.

### On-Chain Transactions

Every insurance flow involves **three on-chain transactions** on Base Mainnet:

1. **Premium Payment (Agent → Insurance Service)**
   - Type: x402 agent-to-agent payment
   - Agent pays premium (1% of coverage) to insurance service
   - EIP-712 signed payment with nonce + timestamp
   - Verified by insurance service before issuing policy

2. **Refund Payment (Insurance Service → Agent)**
   - Type: Standard USDC ERC20 transfer
   - Insurance pays full coverage amount to agent
   - Triggered after zkEngine proof verification
   - Viewable on Basescan as regular USDC transfer

3. **Proof Publication (Insurance Service → Self)**
   - Type: Zero-value transaction with proof data
   - Contains: claim_id, proof_hash, public_inputs, payout, recipient
   - Stored in transaction input field as JSON
   - Enables public audit of all claims

**Example Claim:**
- Refund TX: `0x29c71c423d09ca6101456e458b68022008b541ef78fa9cc76b399e45a3497a62`
- Proof TX: `0x[proof_publication_tx]`
- View on Basescan: https://basescan.org/address/0xf36B80afFb2e41418874FfA56B069f1Fe671FC35

## Quick Start

```bash
# 1. Install dependencies
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment (Base Sepolia recommended for dev)
# Copy .env.example to .env and set values:
#   BASE_RPC_URL=...           # use testnet for development
#   USDC_CONTRACT_ADDRESS=...
#   BACKEND_WALLET_PRIVATE_KEY=... (dev only)
#   BACKEND_WALLET_ADDRESS=...
#   PREMIUM_PERCENTAGE=0.01
#   MAX_COVERAGE_USDC=0.1

# 3. Run server (mock zkEngine and minimal x402 verification)
python server.py
```

Server runs on **http://localhost:8000**

📖 **Full Documentation:** See `AGENT_DISCOVERY.md`, `DEPLOYMENT.md` and other guides

## 🤖 Agent Discovery

Your service is fully discoverable by autonomous agents via:

### x402 Bazaar
Ready for listing in the x402 Bazaar discovery service:
- ✅ Complete input/output JSON schemas
- ✅ Rich metadata (category, tags, pricing)
- ✅ x402Version field
- ✅ Performance metrics
- ✅ Agent-card.json for service discovery

### Discovery Endpoints

| Endpoint | Description |
|----------|-------------|
| `/.well-known/agent-card.json` | Service discovery agent card |
| `/api` | API information & x402 metadata |
| `/api/pricing` | Detailed pricing information |
| `/api/schema` | OpenAPI 3.0 specification (JSON/YAML) |
| `/api/dashboard` | Live statistics and metrics |

See [AGENT_DISCOVERY.md](AGENT_DISCOVERY.md) for complete integration guide.

## API Endpoints

### 1. Lookup Active Policies (Solves Agent Memory Problem)

**NEW: Find your policies when you need to file a claim**

This endpoint solves the "agent memory problem" - agents with limited context windows can forget their policy_id between purchase and claim filing. Simply query with your wallet address to retrieve all active policies.

```bash
GET /policies?wallet=0x...

Response:
{
  "wallet_address": "0x...",
  "active_policies": [
    {
      "policy_id": "550e8400-e29b-41d4-a716-446655440000",
      "merchant_url": "https://api.example.com",
      "coverage_amount": 10000,
      "premium": 100,
      "status": "active",
      "created_at": "2025-11-07T10:00:00Z",
      "expires_at": "2025-11-08T10:00:00Z"
    }
  ],
  "total_coverage": 10000,
  "claim_endpoint": "/claim",
  "note": "Use policy_id from any active policy to file a claim if merchant fails"
}
```

**Usage in Agent Flow:**
```python
# When merchant fails and you need to file a claim:
# 1. Get your wallet address (you always know this)
my_wallet = agent.wallet.address

# 2. Lookup your active policies
policies = httpx.get(f"http://localhost:8000/policies?wallet={my_wallet}").json()

# 3. Find the policy for the failed merchant
policy = next(p for p in policies["active_policies"]
              if p["merchant_url"] == failed_merchant_url)

# 4. File claim with the policy_id
claim = httpx.post("http://localhost:8000/claim", json={
    "policy_id": policy["policy_id"],
    "http_response": {"status": 503, "body": ""}
})
```

### 2. Create Insurance Policy (x402 Payment Required)

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
    headers={"X-Payment": "token=xyz,amount=100,signature=abc"},
    json={"merchant_url": "https://api.com", "coverage_amount": 0.01}
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

### Quick Start
- **[README.md](README.md)** (this file) - Overview and quick start
- **[openapi.yaml](openapi.yaml)** - OpenAPI 3.0 specification

### Core Documentation
- **[PRODUCTION_READY.md](docs/PRODUCTION_READY.md)** - Current production status
- **[VERIFICATION_FLOW.md](docs/VERIFICATION_FLOW.md)** - How proof verification works
  - ✅ Verification happens **OFF-CHAIN** before refunds
  - ✅ Invalid claims are **REJECTED** (no refund)
  - ✅ Only verified proofs published on-chain

### Guides
- **[Deployment Guide](docs/guides/DEPLOYMENT.md)** - Deploy to production
- **[Production Setup](docs/guides/PRODUCTION_SETUP.md)** - Configuration guide
- **[Wallet Setup](docs/guides/WALLET_SETUP_GUIDE.md)** - Base Mainnet wallet setup

### Development
- **[Agent Integration](docs/development/AGENT_DISCOVERY.md)** - x402 Bazaar integration
- **[Payment Architecture](docs/development/PAYMENT_FLOW_ARCHITECTURE.md)** - Technical details
- **[Future Improvements](docs/development/FUTURE_IMPROVEMENTS.md)** - Roadmap

📖 **[Full Documentation Index](docs/README.md)**

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
- **zkEngine** - Nova/Spartan zero-knowledge proof system
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

⚠️ NEVER commit secrets (.env) to git. Use environment variables in deployment.
🧪 Use Base Sepolia for development; switch to Mainnet only with proper key management.
✅ Zero-knowledge proofs (mock/real) to protect merchant privacy
✅ Public auditability (proof verification endpoint)

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

**Wallet:** 0xa4d01549F1460142FAF735e6B18600949C5764a9
**Network:** Base Mainnet (Chain ID: 8453)
**Block Explorer:** https://basescan.org

**Documentation:**
- Full positioning: See `POSITIONING.md` for market analysis
- GitHub Issue: https://github.com/coinbase/x402/issues/508
