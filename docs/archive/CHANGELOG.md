# Changelog

All notable changes to the x402 Insurance project will be documented in this file.

## [2.0.0] - 2025-01-08

### Added - Critical & High Priority Production Improvements

#### Security & Payment Verification
- **Proper x402 Payment Verification** (`auth/payment_verifier.py`)
  - EIP-712 signature verification for payment authentication
  - Replay attack prevention with nonce tracking
  - Timestamp validation to prevent stale payments
  - Configurable verification modes: `simple` (testing) and `full` (production)
  - Proper payer address verification

#### Database & Scalability
- **Database Abstraction Layer** (`database.py`)
  - Support for both JSON files (development) and PostgreSQL (production)
  - Automatic backend selection via `DATABASE_URL` environment variable
  - ACID-compliant transactions with PostgreSQL
  - Indexed queries for fast policy/claim lookups
  - Atomic file operations for JSON backend

#### Blockchain Enhancements
- **Enhanced Blockchain Client** (`blockchain.py`)
  - Retry logic with exponential backoff for failed transactions
  - Gas price limits to prevent excessive costs (configurable `MAX_GAS_PRICE_GWEI`)
  - Balance checking before refund attempts (USDC and ETH)
  - Better error handling with specific exception types
  - Transaction timeout handling
  - Detailed logging for debugging

#### Rate Limiting & CORS
- **Flask-Limiter Integration**
  - Configurable rate limits per endpoint
  - `/insure`: 10 requests/hour to prevent spam policy creation
  - `/claim`: 5 requests/hour to prevent claim abuse
  - Support for Redis-backed distributed rate limiting
  - Can be disabled for testing via `RATE_LIMIT_ENABLED=false`

- **CORS Configuration**
  - Configurable allowed origins via `CORS_ORIGINS`
  - Secure defaults for production

#### Reserve Monitoring
- **Reserve Health Monitoring** (`tasks/reserve_monitor.py`)
  - Real-time reserve-to-liability ratio tracking
  - Configurable minimum reserve ratio (default: 1.5x)
  - Alert system for low reserves (critical/warning states)
  - New endpoint: `GET /api/reserves` for reserve health status
  - Periodic cleanup to avoid alert spam

#### Configuration Management
- **Environment-based Configuration** (`config.py`)
  - Separate configs for development, production, and testing
  - Automatic configuration selection via `ENV` variable
  - Validation of required settings in production mode
  - Centralized configuration with sensible defaults

#### Testing & CI/CD
- **Unit Test Suite** (`tests/unit/`)
  - Payment verifier tests
  - Database backend tests
  - Blockchain client tests (mock mode)
  - Designed for pytest with coverage reporting

- **CI/CD Pipeline** (`.github/workflows/ci.yml`)
  - Automated testing on push/PR
  - Python 3.11 and 3.12 matrix testing
  - Code quality checks (black, ruff)
  - Security scanning for hardcoded secrets
  - Coverage reporting with Codecov
  - .env file detection to prevent secret leaks

### Changed

#### Server Improvements
- **Updated Flask Server** (`server.py`)
  - Integrated all new modules (payment verification, database, reserve monitoring)
  - Rate limiting on sensitive endpoints
  - Better error handling with specific error messages
  - Improved logging with structured formats
  - Database-backed policy/claim storage (with fallback to JSON)
  - Reserve health warnings in responses

#### Dependencies
- **Updated `requirements.txt`**
  - Added `flask-limiter` for rate limiting
  - Added `flask-cors` for CORS support
  - Added `psycopg2-binary` for PostgreSQL support
  - Added `eth-account` for enhanced crypto operations
  - Added testing dependencies (pytest, pytest-cov)
  - Added code quality tools (black, ruff)

#### Environment Configuration
- **Enhanced `.env.example`**
  - All new configuration options documented
  - Database URL configuration
  - Rate limiting settings
  - Payment verification mode selection
  - Gas price and retry limits
  - Reserve monitoring thresholds
  - CORS origins configuration

### Security Improvements
- Proper EIP-712 signature verification prevents payment spoofing
- Nonce-based replay attack prevention
- Timestamp validation for payment freshness
- Gas price limits prevent excessive transaction costs
- Private key never logged or exposed in errors
- .env file properly gitignored
- CI/CD checks for hardcoded secrets

### Performance Improvements
- Database indexes for fast policy lookups by wallet
- Atomic file operations prevent race conditions
- Connection pooling for PostgreSQL
- Efficient nonce cache cleanup
- Retry logic minimizes failed transactions

### Breaking Changes
- Payment verification now requires valid signatures in production mode (`PAYMENT_VERIFICATION_MODE=full`)
- Database schema changed (automatic migration via database abstraction layer)
- Configuration now loaded from `config.py` instead of environment variables directly
- Some endpoints may return different error formats

### Migration Guide

#### For Development
1. Update `.env` from `.env.example` with new variables
2. Install new dependencies: `pip install -r requirements.txt`
3. Run tests: `pytest tests/`
4. Start server: `python server.py` (will use JSON files by default)

#### For Production
1. Set `ENV=production` in environment
2. Configure `DATABASE_URL` for PostgreSQL
3. Set `PAYMENT_VERIFICATION_MODE=full`
4. Configure `RATE_LIMIT_STORAGE_URL` (Redis recommended)
5. Set proper `CORS_ORIGINS` (comma-separated whitelist)
6. Ensure `BACKEND_WALLET_PRIVATE_KEY` is securely managed
7. Monitor `/api/reserves` endpoint for reserve health

## [1.0.0] - 2025-11-06

### Initial Release
- Basic x402 insurance service
- ZKP-verified fraud detection
- JSON file storage
- Simple payment verification
- Agent discovery endpoints
- Dashboard UI
