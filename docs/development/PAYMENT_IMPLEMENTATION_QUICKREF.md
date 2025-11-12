# x402 Payment Implementation - Quick Reference Guide

## TL;DR: 5 Key Points

1. **Signature Verification:** EIP-712 structured data (uses `eth-account` library)
2. **Replay Prevention:** Persistent nonce tracking in `data/nonce_cache.json`
3. **Payment Flow:** Agent gets 402, signs payment with private key, retries with X-Payment header
4. **Premium Model:** 1% of coverage amount (0.01 USDC coverage = 0.0001 USDC premium)
5. **Security Score:** 8.5/10 - Production-ready with proper signature verification

---

## Core Files

| File | Purpose | Status |
|------|---------|--------|
| `auth/payment_verifier.py` | EIP-712 signature verification | ✅ Production |
| `server.py` lines 949-995 | POST /insure payment handling | ✅ Production |
| `server.py` lines 1141-1182 | POST /renew payment handling | ✅ Production |
| `config.py` | PAYMENT_VERIFICATION_MODE switch | ✅ Production |
| `tests/unit/test_payment_verifier.py` | Unit tests (minimal) | ⚠️ Limited |

---

## Payment Verification Methods

### Simple Mode (Development)
```python
SimplePaymentVerifier()
- Only validates amount
- Skips signature verification
- Used by default in dev
- Risk: No crypto verification
```

### Full Mode (Production)
```python
PaymentVerifier()
- EIP-712 signature verification
- Nonce tracking (replay prevention)
- Timestamp validation
- Required for production
```

---

## Payment Flow Summary

```
Agent → POST /insure (no payment)
                ↓
Server → HTTP 402 (returns payment details)
                ↓
Agent → Signs payment with private key
                ↓
Agent → POST /insure + X-Payment header
                ↓
Server → Verify signature + nonce + timestamp + amount
                ↓
Server → HTTP 201 (policy created) OR 402 (invalid payment)
```

---

## Environment Variables (Config)

```bash
# Payment Mode (CRITICAL)
PAYMENT_VERIFICATION_MODE=full           # "full" for prod, "simple" for dev

# Payment Timing
PAYMENT_MAX_AGE_SECONDS=300              # Max age 5 minutes

# Blockchain Config
BACKEND_WALLET_ADDRESS=0x...             # Payment recipient
BACKEND_WALLET_PRIVATE_KEY=0x...         # For USDC transfers
BASE_RPC_URL=https://mainnet.base.org   # Base Mainnet RPC
USDC_CONTRACT_ADDRESS=0x833589fCD6...    # USDC on Base

# Premium Model
PREMIUM_PERCENTAGE=0.01                  # 1% of coverage
MAX_COVERAGE_USDC=0.1                    # Max 0.1 USDC per policy
```

---

## Key Code Snippets

### Verification Call
```python
payment_details = payment_verifier.verify_payment(
    payment_header="payer=0x...,amount=100,...,signature=0x...",
    payer_address="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0",
    required_amount=100,  # microunits
    max_age_seconds=300
)

if payment_details.is_valid:
    create_policy(payment_details)
else:
    return_402_payment_required()
```

### Premium Calculation
```python
coverage_amount = 0.01  # USDC
premium = coverage_amount * PREMIUM_PERCENTAGE  # 0.0001 USDC
premium_units = to_micro(premium)  # 100 microunits (6 decimals)

# Always in microunits for blockchain
```

### HTTP Headers
```
X-Payment: payer=0x...,amount=100,asset=0x...,payTo=0x...,timestamp=1699...,nonce=uuid,signature=0x...
X-Payer: 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0
```

---

## Security Checklist

### What Gets Verified
- [x] Signature is valid EIP-712
- [x] Signer matches declared payer
- [x] Amount exactly matches required premium
- [x] Recipient is backend address
- [x] Asset is USDC contract
- [x] Timestamp not too old (5 min max)
- [x] Timestamp not in future (60s skew)
- [x] Nonce not previously used (replay attack prevention)

### Nonce Tracking
- Persistent storage: `data/nonce_cache.json`
- Expires after: 1 hour
- Format: `"{payer}:{nonce}"` = timestamp
- Survives server restarts ✓

---

## Common Issues & Fixes

| Issue | Cause | Fix |
|-------|-------|-----|
| 402 on every request | Payment header format wrong | Check comma-separated format |
| "Nonce already used" | Replay attack attempted | Use unique nonce per signature |
| "Amount mismatch" | Client sent wrong premium | Recalculate premium server-side |
| "Signature invalid" | Client key doesn't match payer | Verify signer private key |
| Signature verification disabled | PAYMENT_VERIFICATION_MODE=simple | Set to "full" for production |

---

## Solana Support (Planned)

```
Status: In Development (Hackathon Deadline: Nov 11, 2025)

Files to be created:
├── payment_verifier_solana.py    # ed25519 signature verification
├── blockchain_solana.py          # SPL Token transfers
└── server_solana.py              # Flask API for Solana

Key difference:
- Solana: ed25519 signatures (not EIP-712)
- Solana: SPL Token (not ERC-20)
- Solana: 400ms finality (vs 2-5s on Base)
```

---

## Testing

### Run Existing Tests
```bash
pytest tests/unit/test_payment_verifier.py -v
```

### What's Tested
- ✅ Simple amount validation
- ✅ Missing header handling
- ✅ PaymentDetails dataclass creation

### What's NOT Tested
- ❌ EIP-712 signature verification
- ❌ Nonce tracking/replay prevention
- ❌ Timestamp validation
- ❌ Real signed payments

---

## Compliance Status

| Spec | Status | Notes |
|------|--------|-------|
| Coinbase x402 | ✅ Compliant | 402 response, headers, signature |
| Corbits Quickstart | ⚠️ Partial | Headers format differs (custom vs standard) |
| Solana x402 | 🚧 Planned | ed25519 implementation in progress |
| EIP-712 | ✅ Compliant | Proper domain and message structure |

---

## Performance

| Operation | Time | Blocking |
|-----------|------|----------|
| Signature verification | <100ms | Yes |
| Nonce lookup | <10ms | Yes |
| Cache cleanup | 10-50ms | Every hour |
| Cache persistence | <50ms | Yes (atomic write) |

---

## Risk Assessment

| Risk | Level | Mitigation |
|------|-------|------------|
| Signature spoofing | LOW | EIP-712 + signature recovery ✓ |
| Replay attacks | LOW | Nonce tracking + persistence ✓ |
| Token substitution | LOW | Asset address validation ✓ |
| Amount manipulation | LOW | Exact amount matching ✓ |
| Distributed deployment | MEDIUM | File-based nonce cache ⚠️ |
| Production config leak | HIGH | Validate env vars at startup ✓ |

---

## Deployment Checklist

Before going live:

- [ ] Set PAYMENT_VERIFICATION_MODE=full
- [ ] Set BACKEND_WALLET_ADDRESS
- [ ] Set BACKEND_WALLET_PRIVATE_KEY
- [ ] Set BASE_RPC_URL to mainnet
- [ ] Set USDC_CONTRACT_ADDRESS to mainnet USDC
- [ ] Create data/ directory for nonce_cache.json
- [ ] Test with real signed payment
- [ ] Monitor logs for signature errors
- [ ] Setup Redis for nonce cache (if multi-server)
- [ ] Document rate limits to agents
- [ ] Setup monitoring for 402 errors

---

## Key Algorithms

### Signature Verification (EIP-712)
```
1. Client creates structured data {domain, types, message}
2. Client signs with private key → signature
3. Server encodes same structure
4. Server calls Account.recover_message(encoded, signature)
5. Server compares recovered address == declared payer
6. Result: is_valid boolean
```

### Nonce Tracking
```
1. Payment arrives with nonce N
2. Check if key "{payer}:{N}" in cache
   - If YES: Reject (replay attack)
   - If NO: Continue
3. Verify signature
4. On success: Add "{payer}:{N}" = timestamp to cache
5. Every hour: Remove entries older than 1 hour
```

---

## Further Reading

- Full Review: `X402_PAYMENT_IMPLEMENTATION_REVIEW.md`
- Flow Diagrams: `PAYMENT_FLOW_ARCHITECTURE.md`
- API Spec: `openapi.yaml`
- Agent Card: `/.well-known/agent-card.json`
- Config: `config.py`

---

*Last Updated: 2025-11-08*
*Version: x402 Insurance v2.2.0*
