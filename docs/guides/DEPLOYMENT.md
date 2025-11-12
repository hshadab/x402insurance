# Deployment Guide - Render

This guide explains how to deploy the x402 Insurance Service to Render.

## Prerequisites

1. A Render account (sign up at https://render.com)
2. Your code in a Git repository (GitHub, GitLab, or Bitbucket)
3. Base Mainnet wallet with:
   - Private key
   - Wallet address
   - Some ETH for gas fees (~0.005 ETH recommended)
   - USDC for refunds (amount depends on expected coverage)

## Deployment Steps

### 1. Push Code to Git Repository

```bash
# Initialize git repository (if not already done)
git init

# Add all files
git add .

# Commit
git commit -m "Initial commit - x402 Insurance Service"

# Add remote (replace with your repository URL)
git remote add origin https://github.com/YOUR_USERNAME/x402insurance.git

# Push
git push -u origin main
```

### 2. Create New Web Service on Render

1. Go to https://dashboard.render.com
2. Click "New +" → "Web Service"
3. Connect your Git repository
4. Render will automatically detect `render.yaml`

### 3. Configure Environment Variables

In the Render dashboard, go to "Environment" and add these SECRET variables:

**CRITICAL - Keep These Secret:**
```
BACKEND_WALLET_PRIVATE_KEY=0xYOUR_PRIVATE_KEY_HERE
BACKEND_WALLET_ADDRESS=0xYOUR_WALLET_ADDRESS_HERE
BASE_RPC_URL=https://base-mainnet.g.alchemy.com/v2/YOUR_ALCHEMY_KEY
```

**Optional:**
```
PREMIUM_PERCENTAGE=0.01
MAX_COVERAGE_USDC=0.1
POLICY_DURATION_HOURS=24
```

### 4. Deploy

1. Click "Create Web Service"
2. Render will:
   - Install Python dependencies
   - Install Rust/Cargo
   - Clone and compile zkEngine (~5-10 minutes)
   - Start the service with gunicorn

### 5. Verify Deployment

Once deployed, visit:
- `https://YOUR_APP_NAME.onrender.com/` - Dashboard UI
- `https://YOUR_APP_NAME.onrender.com/health` - Health check
- `https://YOUR_APP_NAME.onrender.com/api` - API info

## Build Process Breakdown

The build command in `render.yaml` does:

1. **Install Python dependencies** - Flask, web3.py, x402 SDK, etc.
2. **Install Rust** - Required to compile zkEngine
3. **Clone zkEngine** - From ICME-Lab/zkEngine_dev
4. **Compile zkEngine** - Builds fraud_detector binary (~5-10 min)
5. **Setup directories** - Creates data/ for JSON storage

## Cost Estimates

### Render Free Tier
- **Plan:** Starter (Free)
- **Limits:**
  - 750 hours/month
  - Sleeps after 15 min inactivity
  - 512 MB RAM
  - Shared CPU
- **Cost:** $0/month
- **Good for:** Testing, demos, low traffic

### Render Paid Tier (Recommended for Production)
- **Plan:** Starter ($7/month)
- **Features:**
  - Always on (no sleep)
  - 512 MB RAM
  - Shared CPU
  - Custom domains
- **Cost:** $7/month
- **Good for:** Production with moderate traffic

### Blockchain Costs (Base Mainnet)
- **Gas per refund:** ~0.000001 ETH (~$0.003 at 2500 ETH/USD)
- **Example:** 1000 refunds = 0.001 ETH (~$3)
- **USDC for refunds:** Depends on coverage (e.g., 100 refunds at 0.01 USDC = 1 USDC)

## Performance Notes

### Build Time
- **First deployment:** ~10-15 minutes (Rust install + zkEngine compilation)
- **Subsequent deploys:** ~8-12 minutes (Rust cached, zkEngine recompiled)

### Runtime Performance
- **zkp generation:** ~10-20 seconds per claim
- **USDC refund:** ~2-5 seconds (Base L2)
- **Total claim processing:** ~15-30 seconds

### Optimization Tips

1. **Use persistent disk** - Uncomment disk config in render.yaml to persist data/
2. **Increase workers** - For high traffic, increase gunicorn workers:
   ```yaml
   startCommand: gunicorn --bind 0.0.0.0:$PORT --workers 4 --timeout 120 server:app
   ```
3. **Add caching** - Consider Redis for session/cache storage
4. **Database upgrade** - For production, use PostgreSQL instead of JSON files

## Monitoring

### Logs
- View real-time logs in Render dashboard
- Filter by error level
- Download logs for analysis

### Metrics
- Request count
- Response time
- Memory usage
- CPU usage

### Alerts (Paid plans)
- Set up alerts for:
  - High error rates
  - Slow responses
  - Memory/CPU limits

## Troubleshooting

### Build Failures

**Error: "Rust installation failed"**
- Render may have temporary network issues
- Solution: Trigger manual redeploy

**Error: "zkEngine compilation failed"**
- Check Render build logs
- May need more build time (increase timeout)
- Solution: Upgrade to paid plan for more resources

### Runtime Errors

**Error: "No private key, using MOCK mode"**
- Missing BACKEND_WALLET_PRIVATE_KEY
- Solution: Set in Render environment variables

**Error: "x402 middleware will fail"**
- Missing BACKEND_WALLET_ADDRESS
- Solution: Set in Render environment variables

**Error: "Transaction failed: insufficient funds"**
- Not enough ETH for gas or USDC for refunds
- Solution: Fund wallet on Base Mainnet

### Health Check Failures

If health check fails:
1. Check logs for startup errors
2. Verify environment variables
3. Test `/health` endpoint manually
4. Increase health check timeout in render.yaml

## Security Best Practices

1. **Never commit secrets**
   - Use .env locally (gitignored)
   - Use Render environment variables in production

2. **Use separate wallets**
   - Development wallet (Base Sepolia testnet)
   - Production wallet (Base Mainnet)
   - Never use same private key

3. **Limit wallet funds**
   - Only keep necessary ETH for gas
   - Only keep necessary USDC for expected refunds
   - Refill as needed

4. **Monitor wallet balance**
   - Check dashboard regularly
   - Set up alerts for low balance

5. **Rotate keys periodically**
   - Change private key every 3-6 months
   - Update Render environment variables

## Scaling for Production

### Database Migration
Replace JSON file storage with PostgreSQL:
1. Uncomment database section in render.yaml
2. Update server.py to use SQLAlchemy
3. Create migration scripts

### Caching Layer
Add Redis for improved performance:
1. Add Redis addon in Render
2. Cache policy lookups
3. Cache proof verifications

### Load Balancing
For high traffic:
1. Upgrade to Standard/Pro plan
2. Increase gunicorn workers
3. Consider multiple instances

### CDN for Static Files
For dashboard UI:
1. Use Cloudflare or similar CDN
2. Serve static files separately
3. Reduce server load

## Support

- **Render Docs:** https://render.com/docs
- **Render Community:** https://community.render.com
- **zkEngine Issues:** https://github.com/ICME-Lab/zkEngine_dev/issues
- **x402 Docs:** https://github.com/coinbase/x402

## Next Steps

After successful deployment:
1. Test with micropayment insurance policy (0.001 USDC)
2. Submit test claim with fraud proof
3. Verify USDC refund on Base Mainnet
4. Monitor logs and metrics
5. Set up custom domain (optional)
6. Configure SSL (automatic on Render)

---

**Ready to deploy? Follow the steps above and your x402 Insurance Service will be live in ~15 minutes!**
