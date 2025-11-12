# Production Setup Guide

This guide walks you through deploying x402 Insurance to production.

## Prerequisites

- Python 3.11 or 3.12
- Access to Base Mainnet RPC (Alchemy recommended)
- USDC on Base Mainnet for reserves
- ETH on Base Mainnet for gas fees
- (Optional) PostgreSQL database
- (Optional) Redis for distributed rate limiting

## Step 1: Environment Configuration

### Create Production .env File

```bash
# DO NOT commit this file - it contains secrets
cp .env.example .env.production
```

### Configure .env.production

Edit `.env.production` with your production values:

```bash
# App Configuration
ENV=production
DEBUG=false
LOG_LEVEL=INFO
PORT=8000
HOST=0.0.0.0

# Database (REQUIRED for production - use PostgreSQL)
DATABASE_URL=postgresql://username:password@host:port/database

# Blockchain (REQUIRED)
BASE_RPC_URL=https://base-mainnet.g.alchemy.com/v2/YOUR_ALCHEMY_KEY
USDC_CONTRACT_ADDRESS=0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
BACKEND_WALLET_PRIVATE_KEY=0xYOUR_PRIVATE_KEY_HERE
BACKEND_WALLET_ADDRESS=0xYOUR_WALLET_ADDRESS_HERE

# Blockchain Limits
MAX_GAS_PRICE_GWEI=50
MAX_RETRIES=3

# zkEngine
ZKENGINE_BINARY_PATH=./zkengine/zkengine-binary

# Insurance Parameters
PREMIUM_PERCENTAGE=0.01
MAX_COVERAGE_USDC=0.1
POLICY_DURATION_HOURS=24

# Rate Limiting (REQUIRED for production)
RATE_LIMIT_ENABLED=true
RATE_LIMIT_STORAGE_URL=redis://localhost:6379/0

# Payment Verification (REQUIRED for production)
PAYMENT_VERIFICATION_MODE=full
PAYMENT_MAX_AGE_SECONDS=300

# Reserve Monitoring
MIN_RESERVE_RATIO=2.0

# Security (REQUIRED - whitelist only trusted origins)
CORS_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
```

### Important Security Notes

1. **Never commit .env.production** - it contains your private key
2. **Use strong database passwords**
3. **Whitelist CORS origins** - don't use `*` in production
4. **Use full payment verification mode** - `PAYMENT_VERIFICATION_MODE=full`
5. **Set higher reserve ratio** - `MIN_RESERVE_RATIO=2.0` for safety margin

## Step 2: Install Dependencies

### Install Python Dependencies

```bash
# Activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Upgrade pip
pip install --upgrade pip

# Install all dependencies
pip install -r requirements.txt
```

### Verify Installation

```bash
python3 -c "import flask, web3, psycopg2, eth_account; print('All dependencies installed successfully')"
```

## Step 3: Set Up PostgreSQL Database

### Option A: Local PostgreSQL

```bash
# Install PostgreSQL (Ubuntu/Debian)
sudo apt update
sudo apt install postgresql postgresql-contrib

# Start PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Create database and user
sudo -u postgres psql <<EOF
CREATE DATABASE x402insurance;
CREATE USER x402user WITH ENCRYPTED PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE x402insurance TO x402user;
\q
EOF

# Update DATABASE_URL in .env.production
# DATABASE_URL=postgresql://x402user:your_secure_password@localhost:5432/x402insurance
```

### Option B: Managed PostgreSQL (Recommended)

Use a managed service for production:

- **Heroku Postgres**: Free tier available, easy setup
- **AWS RDS**: Scalable, automated backups
- **Google Cloud SQL**: Good performance
- **Render PostgreSQL**: Simple integration

Example for Render:
1. Create PostgreSQL database in Render dashboard
2. Copy the "Internal Database URL"
3. Set as `DATABASE_URL` in environment

### Verify Database Connection

```bash
# Test database connectivity
python3 -c "
from database import DatabaseClient
db = DatabaseClient(database_url='$DATABASE_URL')
print('Database connection successful')
"
```

## Step 4: Set Up Redis (Optional but Recommended)

### Option A: Local Redis

```bash
# Install Redis (Ubuntu/Debian)
sudo apt update
sudo apt install redis-server

# Start Redis
sudo systemctl start redis
sudo systemctl enable redis

# Test connection
redis-cli ping  # Should return PONG

# Update .env.production
# RATE_LIMIT_STORAGE_URL=redis://localhost:6379/0
```

### Option B: Managed Redis

- **Upstash**: Free tier, serverless
- **Redis Cloud**: Easy setup
- **AWS ElastiCache**: Enterprise-grade

### Verify Redis Connection

```bash
python3 -c "
import redis
r = redis.from_url('$RATE_LIMIT_STORAGE_URL')
r.ping()
print('Redis connection successful')
"
```

## Step 5: Fund Your Wallet

### Check Current Balances

```bash
python3 << 'EOF'
from blockchain import BlockchainClient
from dotenv import load_dotenv
import os

load_dotenv('.env.production')

blockchain = BlockchainClient(
    rpc_url=os.getenv('BASE_RPC_URL'),
    usdc_address=os.getenv('USDC_CONTRACT_ADDRESS'),
    private_key=os.getenv('BACKEND_WALLET_PRIVATE_KEY')
)

eth_balance = blockchain.get_eth_balance()
usdc_balance = blockchain.get_balance()

print(f"ETH Balance: {blockchain.w3.from_wei(eth_balance, 'ether')} ETH")
print(f"USDC Balance: {usdc_balance / 1_000_000} USDC")
print(f"\nWallet Address: {blockchain.account.address}")
EOF
```

### Minimum Required Balances

- **ETH**: At least 0.01 ETH for gas fees (~50-100 transactions)
- **USDC**: Depends on expected coverage volume
  - For testing: 10 USDC
  - For production: 100-1000 USDC based on traffic

### Reserve Recommendations

```
Reserve Ratio = USDC Balance / Total Active Coverage

Recommended ratios:
- Minimum: 1.5x (configured via MIN_RESERVE_RATIO)
- Safe: 2.0x
- Conservative: 3.0x

Example: If you have 100 USDC in active policies, maintain 200-300 USDC reserves
```

## Step 6: Run Tests

### Run Unit Tests

```bash
# Run all tests with coverage
pytest tests/ -v --cov=. --cov-report=term --cov-report=html

# View coverage report
# Open htmlcov/index.html in browser
```

### Run Integration Tests

```bash
# Test with production config (but testnet)
ENV=production BASE_RPC_URL=https://sepolia.base.org python3 test_e2e_flow.py
```

### Security Tests

```bash
# Check for hardcoded secrets
./scripts/check_secrets.sh  # If you have this script

# Or manually:
grep -r "0x[0-9a-fA-F]\{64\}" --include="*.py" . | grep -i "private"
# Should return empty (no hardcoded keys)
```

## Step 7: Test Production Configuration

### Start Server in Test Mode

```bash
# Load production .env but don't expose to internet yet
ENV=production python3 server.py
```

### Verify Endpoints

```bash
# Health check
curl http://localhost:8000/health

# Should return:
# {
#   "status": "healthy",
#   "zkengine": "mock" or "operational",
#   "blockchain": "connected",
#   "wallet": true
# }

# Check reserves
curl http://localhost:8000/api/reserves

# Should return reserve health status

# Check API info
curl http://localhost:8000/api
```

## Step 8: Deploy to Production

### Option A: Deploy to Render (Recommended)

1. **Push to GitHub** (already done)

2. **Create New Web Service** on Render:
   - Go to https://dashboard.render.com
   - Click "New +" → "Web Service"
   - Connect GitHub repository: `hshadab/x402insurance`

3. **Configure Service**:
   - Name: `x402-insurance`
   - Environment: `Python 3`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn server:app`

4. **Set Environment Variables** in Render dashboard:
   - Click "Environment" tab
   - Add all variables from `.env.production`
   - Mark `BACKEND_WALLET_PRIVATE_KEY` as secret

5. **Add PostgreSQL**:
   - In Render dashboard: "New +" → "PostgreSQL"
   - Copy "Internal Database URL"
   - Set as `DATABASE_URL` environment variable

6. **Add Redis** (optional):
   - In Render dashboard: "New +" → "Redis"
   - Copy "Internal Redis URL"
   - Set as `RATE_LIMIT_STORAGE_URL`

7. **Deploy**:
   - Click "Create Web Service"
   - Render will build and deploy automatically
   - Monitor logs for any errors

### Option B: Deploy to VPS (Ubuntu)

```bash
# SSH into your server
ssh user@your-server-ip

# Install system dependencies
sudo apt update
sudo apt install python3.11 python3-pip python3-venv nginx supervisor postgresql redis-server

# Clone repository
git clone https://github.com/hshadab/x402insurance.git
cd x402insurance

# Set up virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with production values

# Set up database
sudo -u postgres createdb x402insurance
sudo -u postgres createuser x402user

# Test run
python3 server.py

# Set up Supervisor for process management
sudo nano /etc/supervisor/conf.d/x402insurance.conf
```

**Supervisor config** (`/etc/supervisor/conf.d/x402insurance.conf`):

```ini
[program:x402insurance]
directory=/home/user/x402insurance
command=/home/user/x402insurance/venv/bin/gunicorn server:app -w 4 -b 0.0.0.0:8000
user=user
autostart=true
autorestart=true
stderr_logfile=/var/log/x402insurance/err.log
stdout_logfile=/var/log/x402insurance/out.log
environment=ENV="production"
```

**Nginx config** (`/etc/nginx/sites-available/x402insurance`):

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/x402insurance /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Start service
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start x402insurance

# Set up SSL with Let's Encrypt
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```

## Step 9: Post-Deployment Verification

### Verify Production Deployment

```bash
# Check health
curl https://yourdomain.com/health

# Check reserves
curl https://yourdomain.com/api/reserves

# Test insurance flow (requires actual USDC payment)
# See test_e2e_flow.py for example
```

### Monitor Logs

```bash
# Render: View in dashboard under "Logs" tab

# VPS:
tail -f /var/log/x402insurance/out.log
tail -f /var/log/x402insurance/err.log
```

### Set Up Monitoring

1. **Health Check Monitoring**:
   - Use UptimeRobot or Pingdom
   - Monitor `GET /health` every 5 minutes
   - Alert if status != "healthy"

2. **Reserve Monitoring**:
   - Monitor `GET /api/reserves` every hour
   - Alert if `status` == "warning" or "critical"

3. **Error Tracking** (optional):
   - Uncomment Sentry in requirements.txt
   - Add to server.py:
   ```python
   import sentry_sdk
   sentry_sdk.init(dsn="YOUR_SENTRY_DSN")
   ```

## Step 10: Ongoing Maintenance

### Daily Tasks

```bash
# Check reserve health
curl https://yourdomain.com/api/reserves

# Check recent claims
curl https://yourdomain.com/api/dashboard | jq '.recent_claims'
```

### Weekly Tasks

- Review logs for errors
- Check database growth
- Verify CI/CD pipeline is passing
- Review reserve levels

### Monthly Tasks

- Update dependencies: `pip install -r requirements.txt --upgrade`
- Review and archive old policies
- Security audit
- Performance optimization

## Troubleshooting

### Common Issues

1. **Database Connection Failed**
   ```bash
   # Check DATABASE_URL format
   echo $DATABASE_URL
   # Should be: postgresql://user:pass@host:port/dbname
   ```

2. **Payment Verification Failing**
   ```bash
   # Check if using correct mode
   echo $PAYMENT_VERIFICATION_MODE
   # Should be "full" for production
   ```

3. **Low Reserves Warning**
   ```bash
   # Check current reserves
   curl http://localhost:8000/api/reserves
   # Fund wallet with more USDC if needed
   ```

4. **Rate Limit Errors**
   ```bash
   # Check Redis connection
   redis-cli ping
   # Or disable temporarily: RATE_LIMIT_ENABLED=false
   ```

## Security Checklist

- [ ] `.env` files not committed to git
- [ ] `PAYMENT_VERIFICATION_MODE=full` in production
- [ ] `CORS_ORIGINS` whitelist configured (not `*`)
- [ ] Database uses strong password
- [ ] Private key stored securely (environment variable only)
- [ ] HTTPS enabled (SSL certificate)
- [ ] Rate limiting enabled
- [ ] CI/CD pipeline running
- [ ] Monitoring and alerts configured
- [ ] Backup strategy in place

## Support

If you encounter issues:

1. Check logs: `tail -f /var/log/x402insurance/err.log`
2. Review configuration: `python3 -c "from config import get_config; print(vars(get_config()))"`
3. Test components individually (database, blockchain, redis)
4. Check GitHub Issues: https://github.com/hshadab/x402insurance/issues

---

**Ready to deploy!** Follow these steps carefully and you'll have a production-ready x402 Insurance service running.
