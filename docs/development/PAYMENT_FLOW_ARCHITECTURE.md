# x402 Payment Flow - Visual Architecture

## High-Level Payment Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         AI AGENT                                 │
│                                                                   │
│  1. Wants insurance coverage for API call                        │
│  2. Sends POST /insure with coverage_amount                      │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       │ POST /insure
                       │ Body: {"coverage_amount": 0.01}
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│              x402 INSURANCE SERVICE                              │
│                                                                   │
│  1. Receives request                                             │
│  2. Checks for X-Payment header (payment not provided yet)       │
│  3. Calculates premium = 0.01 * 0.01 = 0.0001 USDC              │
│  4. Converts to microunits: 0.0001 * 1,000,000 = 100 units      │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       │ HTTP 402 Payment Required
                       │ Returns: Payment details
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                         AI AGENT                                 │
│                                                                   │
│  Receives 402, extracts payment requirements:                    │
│  - amount: 100 (microunits)                                      │
│  - asset: USDC address                                           │
│  - pay_to: backend address                                       │
│  - maxTimeoutSeconds: 60                                         │
│                                                                   │
│  5. Creates EIP-712 payment signature:                           │
│     - Structures payment data                                    │
│     - Signs with private key                                     │
│     - Gets signature: 0xabc123...                                │
│                                                                   │
│  6. Retries with payment headers:                                │
│     X-Payment: payer=0x...,amount=100,...,signature=0x...       │
│     X-Payer: 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0       │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       │ POST /insure + X-Payment header
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│              x402 INSURANCE SERVICE                              │
│                                                                   │
│  Payment Verification (server.py lines 978-983):                │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ payment_verifier.verify_payment(                          │  │
│  │   payment_header=header,                                 │  │
│  │   payer_address=payer,                                   │  │
│  │   required_amount=100,                                   │  │
│  │   max_age_seconds=300                                    │  │
│  │ )                                                         │  │
│  └────────────────────┬────────────────────────────────────┘  │
│                       │                                        │
│                       ▼ Verification Steps                     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ 1. Parse payment header (comma-separated format)         │  │
│  │ 2. Validate fields present (amount, asset, payTo, etc)   │  │
│  │ 3. Amount check: provided == required? (100 == 100) ✓    │  │
│  │ 4. Recipient check: payTo == backend_address? ✓          │  │
│  │ 5. Asset check: asset == USDC_address? ✓                │  │
│  │ 6. Timestamp validation:                                 │  │
│  │    - Not in future? (allow 60s skew)                     │  │
│  │    - Not too old? (max 300s)                             │  │
│  │ 7. Replay attack check:                                  │  │
│  │    - Is nonce already used? (check cache)                │  │
│  │    - Key: "{payer}:{nonce}" persists in JSON file        │  │
│  │ 8. Signature verification (EIP-712):                     │  │
│  │    - Encode structured data                              │  │
│  │    - Recover signer from signature                        │  │
│  │    - Compare recovered address == payer? ✓               │  │
│  │ 9. Mark nonce as used (persist to disk)                  │  │
│  │ 10. Return PaymentDetails(is_valid=True)                │  │
│  └───────────────────────────────────────────────────────────┘  │
│                       │                                        │
│  7. All checks pass: Create policy                             │
│     - policy_id: uuid                                          │
│     - agent_address: payer from payment                        │
│     - coverage_amount: 0.01 USDC                               │
│     - premium: 0.0001 USDC                                     │
│     - status: active                                           │
│     - expires_at: now() + 24 hours                             │
│                                                                 │
│  8. Save policy to database                                    │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       │ HTTP 201 Created
                       │ Response: Policy details
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                         AI AGENT                                 │
│                                                                   │
│  Insurance policy active!                                        │
│  Now protected for next 24 hours                                │
│  Can file claim if API fails                                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## EIP-712 Signature Structure

```
┌─────────────────────────────────────────────────────────────┐
│              EIP-712 Structured Data                        │
│                                                             │
│  Signed Message Contents:                                  │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ DOMAIN (chainId separation - prevent replay)        │  │
│  │  name:    "x402 Payment"                            │  │
│  │  version: "1"                                       │  │
│  │  chainId: 8453 (Base Mainnet)                       │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ MESSAGE (payment details)                           │  │
│  │  payer:     0x742d35Cc6634C0532925a3b844Bc9e7595f  │  │
│  │  amount:    100 (microunits)                        │  │
│  │  asset:     0x036CbD53842c5426634e7929541eC2318f   │  │
│  │  payTo:     0xBackendWallet...                      │  │
│  │  timestamp: 1699466400 (unix time)                  │  │
│  │  nonce:     "8f7d6c4b-3a2b-1c0d-9e8f-7a6b5c4d3e2f" │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                             │
│  Agent signs with private key → 65-byte signature         │
│  Server recovers public key from signature                │
│  Compares recovered key == declared payer ✓               │
└─────────────────────────────────────────────────────────────┘
```

---

## Replay Attack Prevention

```
┌──────────────────────────────────────────────────────────────┐
│              NONCE TRACKING (Persistent)                     │
│                                                              │
│  File: data/nonce_cache.json                               │
│                                                              │
│  Structure:                                                 │
│  {                                                          │
│    "0x742d35...:{nonce-uuid-1}": 1699466400,  ← timestamp  │
│    "0x742d35...:{nonce-uuid-2}": 1699466500,               │
│    "0x123abc...:{nonce-uuid-3}": 1699466600,               │
│  }                                                          │
│                                                              │
│  Lifecycle:                                                 │
│  1. Payment received with nonce X                           │
│  2. Server checks: Is key in cache? NO ✓                   │
│  3. Verify signature (only if nonce unused)                │
│  4. Add to cache: "{payer}:{nonce}" = timestamp            │
│  5. Cleanup: Every 1 hour, remove entries > 1 hour old     │
│  6. Persistence: Cache saved to disk on each update        │
│                                                              │
│  Result: Cannot replay same payment twice                  │
│          (even across server restarts)                      │
└──────────────────────────────────────────────────────────────┘
```

---

## Payment Verification Decision Tree

```
                    ┌─ X-Payment Header Received? ─┐
                    │                               │
                    NO (First request)              YES (Retry)
                    │                               │
                    ▼                               ▼
            Return 402                    Parse payment header
            Payment Required
                    │                       │
                    │                       ├─ All fields present?
                    │                       │ (payer, amount, asset, etc.)
                    │                       │
                    │                       NO ──▶ REJECT (402)
                    │                       │
                    │                       YES
                    │                       │
                    │                       ├─ Amount == Required?
                    │                       │
                    │                       NO ──▶ REJECT (402)
                    │                       │
                    │                       YES
                    │                       │
                    │                       ├─ Asset == USDC?
                    │                       │
                    │                       NO ──▶ REJECT (402)
                    │                       │
                    │                       YES
                    │                       │
                    │                       ├─ PayTo == Backend?
                    │                       │
                    │                       NO ──▶ REJECT (402)
                    │                       │
                    │                       YES
                    │                       │
                    │                       ├─ Timestamp valid?
                    │                       │ (not too old/future)
                    │                       │
                    │                       NO ──▶ REJECT (402)
                    │                       │
                    │                       YES
                    │                       │
                    │                       ├─ Nonce unused?
                    │                       │
                    │                       NO ──▶ REJECT (402)
                    │                       │      [Replay Attack!]
                    │                       │
                    │                       YES
                    │                       │
                    │                       ├─ Signature valid?
                    │                       │ (EIP-712 recover)
                    │                       │
                    │                       NO ──▶ REJECT (402)
                    │                       │
                    │                       YES
                    │                       │
                    │                       ├─ Mark nonce used
                    │                       │ (persist to disk)
                    │                       │
                    └──────────────┬────────┘
                                   │
                                   ▼
                          Create Policy (201)
                          Agent covered!
```

---

## Configuration Scenarios

### Development (Testing)

```
FLASK_ENV = development
PAYMENT_VERIFICATION_MODE = "simple"  # Only checks amount
USE_MOCK_BLOCKCHAIN = true

Result: Easy testing without real keys
        But: No signature verification!
```

### Production (Mainnet)

```
FLASK_ENV = production
PAYMENT_VERIFICATION_MODE = "full"    # Full EIP-712 verification
BASE_RPC_URL = https://mainnet.base.org
BACKEND_WALLET_ADDRESS = 0x...
BACKEND_WALLET_PRIVATE_KEY = 0x...
USDC_CONTRACT_ADDRESS = 0x833589fCD6eDb6E08f4c7C32D4f71b1566915a7d

Result: Production-grade security
        Real blockchain transactions
        Persistent nonce storage
```

---

## Microunit Denomination Examples

```
Coverage Request    Premium (1%)         Microunits (6 decimals)
─────────────────────────────────────────────────────────────
$0.001 USDC      = 0.00001 USDC       = 10 units
$0.01 USDC       = 0.0001 USDC        = 100 units
$0.05 USDC       = 0.0005 USDC        = 500 units
$0.1 USDC        = 0.001 USDC         = 1000 units
$1.0 USDC        = 0.01 USDC          = 10000 units
$100 USDC        = 1.0 USDC           = 1000000 units
```

---

## Security Checklist

```
EIP-712 Signature Verification:
  ✓ Domain structure matches spec
  ✓ Message types properly defined
  ✓ Signature recovery using eth-account
  ✓ Case-insensitive address comparison

Replay Attack Prevention:
  ✓ Nonce tracking (persistent JSON)
  ✓ Nonce expiration (1 hour)
  ✓ Per-payer nonce isolation
  ✓ Survives server restarts

Timestamp Validation:
  ✓ Not in future (60s clock skew)
  ✓ Not too old (300s max)
  ✓ Prevents age-based attacks

Amount Verification:
  ✓ Exact amount matching
  ✓ Prevents over/under payment
  ✓ Prevents unit confusion

Recipient Validation:
  ✓ Backend address matches
  ✓ Prevents payment to attacker

Asset Verification:
  ✓ USDC contract address matches
  ✓ Prevents token substitution attacks

Error Handling:
  ✓ Malformed signatures caught
  ✓ Invalid addresses handled
  ✓ Missing fields detected
  ✓ All errors return 402 (not crash)
```

---

## File Dependencies

```
payment_verifier.py (414 lines)
├── Imports: eth-account, web3.py
├── Exports: PaymentVerifier, SimplePaymentVerifier, PaymentDetails
└── Uses: Python 3.7+, type hints

server.py (1623 lines)
├── Imports: payment_verifier
├── Uses: PaymentVerifier / SimplePaymentVerifier (lines 119-129)
├── Calls: verify_payment() (lines 978, 1168)
└── Handles: 402 responses, payment validation, policy creation

config.py
├── Sets: PAYMENT_VERIFICATION_MODE
├── Sets: PAYMENT_MAX_AGE_SECONDS
└── Sets: BACKEND_WALLET_ADDRESS, BACKEND_WALLET_PRIVATE_KEY

Test Coverage:
tests/unit/test_payment_verifier.py (69 lines)
├── Tests: SimplePaymentVerifier only
├── Gap: No tests for PaymentVerifier (full mode)
└── Gap: No EIP-712 signature tests
```

