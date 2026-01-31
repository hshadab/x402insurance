# Security Improvements

This document describes recent security enhancements made to the x402 Insurance API.

## Critical Security Fixes

### 1. Removed Exposed Credentials from .env

**Issue**: Production wallet private key and RPC API key were committed to the repository.

**Fix**:
- Removed actual credentials from `.env` file
- Replaced with placeholder values
- Added security warnings in `.env` file comments
- Updated `.gitignore` with explicit instructions for removing `.env` from git history

**Action Required**:
```bash
# If .env was previously committed, remove from git history:
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch .env' \
  --prune-empty --tag-name-filter cat -- --all

# Then force push (WARNING: coordinate with team first):
git push origin --force --all
```

**Best Practices**:
- NEVER commit `.env` files to version control
- Use environment variables in production deployments
- Rotate any exposed credentials immediately
- Use secrets management tools (AWS Secrets Manager, HashiCorp Vault, etc.)

### 2. Enhanced .env.example Template

**Improvements**:
- Added comprehensive security warnings at the top
- Documented all configuration options
- Included production vs development guidelines
- Added new security-related configuration options

**New Configuration Options**:
```bash
# Claim endpoint authentication (recommended for production)
REQUIRE_CLAIM_AUTHENTICATION=true

# Rate limits (configurable per endpoint)
RATE_LIMIT_DEFAULT=200 per day
RATE_LIMIT_INSURE=50 per hour
RATE_LIMIT_CLAIM=10 per hour
RATE_LIMIT_RENEW=5 per hour

# Timeouts (in seconds)
JOLT_TIMEOUT=60
BLOCKCHAIN_CONFIRMATION_TIMEOUT=120

# Chain configuration
CHAIN_ID=8453  # Base Mainnet (84532 for Sepolia testnet)

# CORS (restrict to your domain in production)
CORS_ORIGINS=https://yourdomain.com
```

## High Priority Security Enhancements

### 3. Claim Endpoint Authentication

**Issue**: `/claim` endpoint had no authentication, allowing anyone with a policy_id to submit claims.

**Fix**: Added optional x402 payment-based authentication for claim submission.

**Features**:
- Configurable via `REQUIRE_CLAIM_AUTHENTICATION` environment variable
- Requires nominal anti-spam fee (0.0001 USDC) when enabled
- Verifies that claim submitter owns the policy
- Prevents unauthorized claim submissions
- Returns proper HTTP 402 (Payment Required) when authentication is missing
- Returns HTTP 403 (Forbidden) if payer doesn't own the policy

**Configuration**:
```bash
# Development (authentication disabled for easier testing)
REQUIRE_CLAIM_AUTHENTICATION=false

# Production (authentication enabled - recommended)
REQUIRE_CLAIM_AUTHENTICATION=true
```

**Production Default**: Enabled by default in `ProductionConfig` class

**Usage**:
When authentication is enabled, claims must include the x402 V2 payment header:

```bash
POST /claim
Headers:
  PAYMENT-SIGNATURE: <base64-encoded-json-payment-payload>
Body:
  {
    "policy_id": "...",
    "http_response": {...}
  }
```

The `PAYMENT-SIGNATURE` header contains a base64-encoded JSON object with EIP-712
signed payment details. The server verifies this via the x402.org facilitator.

### 4. Configurable CORS Origins

**Issue**: CORS was set to allow all origins (`*`) by default.

**Fix**:
- Made CORS origins configurable via `CORS_ORIGINS` environment variable
- Production config defaults to empty string (requires explicit configuration)
- Development config allows `*` for easier testing

**Configuration**:
```bash
# Development - allow all origins
CORS_ORIGINS=*

# Production - restrict to specific domains
CORS_ORIGINS=https://yourdomain.com,https://app.yourdomain.com
```

### 5. Configurable Rate Limits

**Issue**: Rate limits were hardcoded in the application code.

**Fix**: Moved all rate limits to configuration files.

**Default Limits**:
- Default: 200 requests per day
- `/insure`: 50 per hour
- `/claim`: 10 per hour
- `/renew`: 5 per hour

**Customization**:
```bash
# Adjust rate limits based on your needs
RATE_LIMIT_DEFAULT=500 per day
RATE_LIMIT_INSURE=100 per hour
RATE_LIMIT_CLAIM=20 per hour
RATE_LIMIT_RENEW=10 per hour
```

### 6. Configurable Timeouts

**Issue**: Timeouts for Jolt Atlas and blockchain operations were hardcoded.

**Fix**: Made timeouts configurable via environment variables.

**Configuration**:
```bash
# Jolt Atlas proof generation timeout (default: 60s)
JOLT_TIMEOUT=60

# Blockchain transaction confirmation timeout (default: 120s)
BLOCKCHAIN_CONFIRMATION_TIMEOUT=120
```

**Affected Components**:
- `proof_client.py`: Uses `JOLT_TIMEOUT` for Jolt Atlas proof generation
- `blockchain.py`: Uses `BLOCKCHAIN_CONFIRMATION_TIMEOUT` for transaction confirmations

### 7. Configurable Chain ID

**Issue**: Chain ID was hardcoded to 8453 (Base Mainnet) in EIP-712 signature verification.

**Fix**: Made chain ID configurable to support different networks.

**Configuration**:
```bash
# Base Mainnet
CHAIN_ID=8453

# Base Sepolia (testnet)
CHAIN_ID=84532
```

**Automatic Defaults**:
- Development: 84532 (Base Sepolia)
- Production: 8453 (Base Mainnet)

## Security Best Practices

### Wallet Management

1. **Never commit private keys** - Use environment variables or secrets management
2. **Rotate compromised keys immediately** - If a key is exposed, create a new wallet and transfer funds
3. **Use hardware wallets** for production - Consider Ledger or Trezor for high-value operations
4. **Implement multi-signature** - For production deployments with significant funds

### API Security

1. **Enable claim authentication** - Set `REQUIRE_CLAIM_AUTHENTICATION=true` in production
2. **Restrict CORS** - Set `CORS_ORIGINS` to your actual domain(s)
3. **Use HTTPS** - Always use TLS/SSL in production
4. **Monitor rate limits** - Adjust based on actual usage patterns
5. **Enable full payment verification** - Set `PAYMENT_VERIFICATION_MODE=full` in production

### Deployment Security

1. **Environment Separation** - Use different wallets/keys for dev/staging/production
2. **Secrets Management** - Use AWS Secrets Manager, HashiCorp Vault, or similar
3. **Regular Audits** - Review logs and transaction history regularly
4. **Monitoring & Alerts** - Set up alerts for:
   - Low USDC/ETH balances
   - Failed transactions
   - Unusual API activity
   - Rate limit violations

### Configuration Checklist for Production

- [ ] Remove `.env` from git if previously committed
- [ ] Set `ENV=production`
- [ ] Set `DEBUG=false`
- [ ] Configure `BASE_RPC_URL` with production RPC
- [ ] Set wallet address and private key via environment variables (not .env file)
- [ ] Set `PAYMENT_VERIFICATION_MODE=full`
- [ ] Set `REQUIRE_CLAIM_AUTHENTICATION=true`
- [ ] Configure `CORS_ORIGINS` with your actual domain
- [ ] Set `CHAIN_ID=8453` for Base Mainnet
- [ ] Review and adjust rate limits based on expected traffic
- [ ] Set up monitoring and alerting
- [ ] Configure PostgreSQL (recommended over JSON files)
- [ ] Set up Redis for distributed rate limiting (if using multiple instances)

## Changelog

**2026-01-31 (v2.3.0)**:
- Updated to x402 V2 facilitator-based payment flow (`PAYMENT-SIGNATURE` header)
- Server-side fraud detection via merchant URL re-fetch
- Jolt Atlas 3-argument prover interface

**2025-11-12**:
- Removed exposed credentials from `.env`
- Added claim endpoint authentication
- Made CORS origins configurable
- Made rate limits configurable
- Made timeouts configurable
- Made chain ID configurable
- Enhanced `.env.example` with security warnings
- Updated `.gitignore` with git history removal instructions

## Reporting Security Issues

If you discover a security vulnerability, please:

1. **Do NOT** open a public GitHub issue
2. Email the maintainer directly
3. Include detailed steps to reproduce
4. Allow time for a fix before public disclosure

## Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Web3 Security Best Practices](https://consensys.github.io/smart-contract-best-practices/)
- [EIP-712 Specification](https://eips.ethereum.org/EIPS/eip-712)
- [x402 Protocol Specification](https://github.com/plebbit/x402)
