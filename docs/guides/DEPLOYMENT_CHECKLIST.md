# Deployment Checklist

Use this checklist to ensure a smooth deployment to Render.

## Pre-Deployment

- [ ] **Test locally**
  ```bash
  source venv/bin/activate
  python server.py
  # Test at http://localhost:8000
  ```

- [ ] **Verify wallet has funds**
  - [ ] ETH for gas: ~0.005 ETH minimum
  - [ ] USDC for refunds: Based on expected coverage
  - [ ] Check balance at https://basescan.org

- [ ] **Get Alchemy API Key**
  - [ ] Sign up at https://alchemy.com
  - [ ] Create Base Mainnet app
  - [ ] Copy API key for BASE_RPC_URL

- [ ] **Prepare environment variables**
  - [ ] BACKEND_WALLET_PRIVATE_KEY (from wallet)
  - [ ] BACKEND_WALLET_ADDRESS (from wallet)
  - [ ] BASE_RPC_URL (from Alchemy)

## Git Repository Setup

- [ ] **Initialize git (if not done)**
  ```bash
  git init
  ```

- [ ] **Verify .gitignore is working**
  ```bash
  git status
  # .env should NOT appear in untracked files
  ```

- [ ] **Create repository on GitHub/GitLab**
  - Go to GitHub.com → New Repository
  - Name: x402insurance (or your choice)
  - Set to Private (recommended for production)

- [ ] **Push code**
  ```bash
  git add .
  git commit -m "Initial commit - x402 Insurance Service"
  git remote add origin https://github.com/YOUR_USERNAME/x402insurance.git
  git push -u origin main
  ```

## Render Setup

- [ ] **Create Render account**
  - Sign up at https://render.com
  - Verify email

- [ ] **Connect Git provider**
  - Dashboard → Account Settings → Git Providers
  - Connect GitHub/GitLab

- [ ] **Create new Web Service**
  - Dashboard → New + → Web Service
  - Select your repository
  - Render will detect render.yaml automatically

- [ ] **Configure environment variables in Render**
  - Go to Environment tab
  - Add these as **secret** environment variables:
    - `BACKEND_WALLET_PRIVATE_KEY` = (your private key)
    - `BACKEND_WALLET_ADDRESS` = (your wallet address)
    - `BASE_RPC_URL` = https://base-mainnet.g.alchemy.com/v2/YOUR_KEY

- [ ] **Review render.yaml settings**
  - Region: Choose closest to your users
  - Plan: Free tier for testing, Starter ($7) for production
  - Branch: Ensure it matches your git branch (main/master)

- [ ] **Deploy**
  - Click "Create Web Service"
  - Wait 10-15 minutes for first build

## Post-Deployment Verification

- [ ] **Check build logs**
  - Verify Python dependencies installed
  - Verify Rust installed
  - Verify zkEngine compiled successfully
  - No error messages in logs

- [ ] **Test health endpoint**
  ```bash
  curl https://YOUR_APP_NAME.onrender.com/health
  # Should return: {"status": "healthy", ...}
  ```

- [ ] **Test dashboard UI**
  - Visit https://YOUR_APP_NAME.onrender.com/
  - Dashboard should load
  - Blockchain stats should show your wallet

- [ ] **Test API info**
  ```bash
  curl https://YOUR_APP_NAME.onrender.com/api
  # Should return API documentation
  ```

## Functional Testing

- [ ] **Create test policy (local)**
  ```bash
  python test_micropayment.py
  ```

- [ ] **Verify refund on blockchain**
  - Check transaction on https://basescan.org
  - Confirm USDC transfer occurred

- [ ] **Monitor wallet balance**
  - Check ETH balance (should decrease slightly for gas)
  - Check USDC balance (should decrease by refund amount)

## Production Readiness

- [ ] **Set up monitoring**
  - Enable email alerts in Render
  - Monitor error rates
  - Monitor response times

- [ ] **Configure custom domain (optional)**
  - Render Dashboard → Settings → Custom Domain
  - Add your domain
  - Update DNS settings

- [ ] **SSL Certificate**
  - Render automatically provisions SSL
  - Verify https:// works

- [ ] **Performance tuning**
  - [ ] Adjust gunicorn workers if needed
  - [ ] Consider upgrading plan for more resources
  - [ ] Enable persistent disk for data/

- [ ] **Security review**
  - [ ] Verify .env not in git
  - [ ] Verify private key stored securely
  - [ ] Limit wallet funds to necessary amounts
  - [ ] Set up wallet monitoring/alerts

## Ongoing Maintenance

- [ ] **Set up regular monitoring**
  - Check Render logs daily
  - Monitor wallet balance weekly
  - Review claims/policies weekly

- [ ] **Plan for scaling**
  - Consider PostgreSQL when >1000 policies
  - Consider Redis caching for high traffic
  - Plan for wallet refills

- [ ] **Security maintenance**
  - Rotate private keys every 3-6 months
  - Keep dependencies updated
  - Monitor for security vulnerabilities

## Troubleshooting

If deployment fails, check:

1. **Build fails at Rust installation**
   - Retry deployment (temporary network issue)
   - Upgrade to paid plan (more resources)

2. **Build fails at zkEngine compilation**
   - Check Render build logs for specific error
   - Increase timeout in render.yaml
   - Verify zkEngine repo is accessible

3. **Service starts but health check fails**
   - Check environment variables are set
   - Verify private key format (should start with 0x)
   - Check logs for Python errors

4. **Refunds fail**
   - Verify wallet has ETH for gas
   - Verify wallet has USDC for refunds
   - Check Base Mainnet RPC is working

## Support Resources

- **Render Docs:** https://render.com/docs
- **Render Community:** https://community.render.com
- **Base Docs:** https://docs.base.org
- **x402 Docs:** https://github.com/coinbase/x402

---

**Ready?** Start with "Pre-Deployment" and work your way down!
