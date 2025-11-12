# Security Cleanup Summary - x402insurance

**Date:** 2025-11-07
**Status:** GitHub History Cleaned - New Wallet Required

## What Happened

Your wallet private key was accidentally committed to GitHub in `render.yaml` and was publicly visible since November 6, 2025. Automated sweeper bots found the key and drained all ETH deposits within seconds.

**Evidence of Compromise:**
- Private key exposed in `render.yaml` lines 57-59 (initial commit 89459b6)
- ETH deposit of 0.01416625 ETH stolen in 2-4 seconds after arrival
- Two theft transactions identified at blocks 37,878,807 and 37,878,808
- Total stolen: 0.01416541 ETH (99.99% of deposit)

## Actions Completed

### 1. GitHub Cleanup (x402insurance repository)
- ✅ Removed `render.yaml` from current working directory
- ✅ Created `render.yaml.example` as secure template
- ✅ Updated `.gitignore` with comprehensive secret file patterns
- ✅ Rewrote git history using `git filter-branch` to remove render.yaml from all commits
- ✅ Force pushed cleaned history to GitHub
- ✅ Cleaned up git refs and compacted repository

**Result:** The private key is NO LONGER visible on GitHub

### 2. Current Status
- **Compromised wallet:** 0xa4d01549F1460142FAF735e6B18600949C5764a9
- **Remaining USDC:** 0.99 USDC (needs to be rescued)
- **Remaining ETH:** ~0.00001 ETH (negligible)

## What You Need To Do Next

### URGENT: Create New Secure Wallet

**IMPORTANT:** Generate the new wallet on your PHONE (MetaMask mobile app), NOT on your PC. This ensures the compromised PC cannot intercept the new private key.

1. **Install MetaMask on your phone** (if not already installed)
   - iOS: App Store
   - Android: Google Play

2. **Create new wallet in MetaMask**
   - Open MetaMask app
   - Create new wallet or add new account
   - **WRITE DOWN** the recovery phrase on paper (NOT digitally)
   - Copy the wallet address (starts with 0x...)

3. **Send me the new wallet ADDRESS ONLY** (via this chat)
   - Example: 0x1234...5678
   - DO NOT send the private key or recovery phrase to me or anyone

4. **I will update the .env file** with:
   - Your new wallet address
   - Instructions on how to export the private key securely

5. **Fund the new wallet:**
   - Send 0.005-0.01 ETH for gas (from Kraken or another wallet)
   - Send USDC for refunds (start with small amount for testing)

6. **Rescue the 0.99 USDC from compromised wallet:**
   - We'll use a script to quickly transfer USDC to your new wallet
   - This requires some ETH in the compromised wallet for gas
   - WARNING: Any ETH sent to compromised wallet will be stolen instantly
   - We may need to use a "flashbot" technique to rescue the USDC

### Optional But Recommended: PC Security Audit

Since the wallet was compromised, consider checking your PC for malware:

```bash
# Linux/WSL - Check for rootkits
sudo apt install rkhunter chkrootkit
sudo rkhunter --check
sudo chkrootkit

# Check for suspicious processes
ps aux --sort=-%cpu | head -20
netstat -tupn | grep ESTABLISHED

# Check .env file access times
stat .env

# Check for modifications to critical files
ls -la ~/.bashrc ~/.bash_profile
```

**Windows - Run full malware scan:**
- Windows Defender Offline Scan
- Malwarebytes (free trial)

## Files Modified

### Created
- `render.yaml.example` - Secure template without secrets
- `SECURITY_CLEANUP_SUMMARY.md` - This file

### Modified
- `.gitignore` - Added comprehensive secret file patterns
  ```
  render.yaml
  *.pem, *.key, *.p12, *.pfx
  *_rsa, *_dsa, *_ecdsa, *_ed25519
  *.env.backup, *.env.production, *.env.staging
  credentials.json, secrets.json
  private_key*, wallet_key*
  ```

### Deleted
- `render.yaml` - Removed from working directory and git history

## Security Best Practices Going Forward

1. **NEVER commit secrets to git**
   - Use .env files (already in .gitignore)
   - Use environment variables in deployment platforms
   - Use render.yaml.example as template, not actual render.yaml

2. **Use Render dashboard for secrets**
   - Set `BACKEND_WALLET_PRIVATE_KEY` in Render Environment Variables
   - Set `BACKEND_WALLET_ADDRESS` in Render Environment Variables
   - Set `BASE_RPC_URL` in Render Environment Variables

3. **Generate wallets securely**
   - Use hardware wallets for production (Ledger, Trezor)
   - Use mobile wallets (MetaMask mobile) for development
   - NEVER generate wallets on potentially compromised PCs

4. **Monitor wallet activity**
   - Set up alerts for large transactions
   - Regularly check balances
   - Use separate wallets for testing vs production

## Technical Details

**Git History Cleanup:**
```bash
# Removed render.yaml from all commits
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch render.yaml' \
  --prune-empty --tag-name-filter cat -- --all

# Cleaned up refs
rm -rf .git/refs/original/
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# Force pushed to GitHub
git push --force origin main
```

**Commits Affected:** 12 commits rewritten
**Result:** render.yaml removed from entire git history

## Next Steps Checklist

- [ ] Create new wallet on MetaMask mobile app
- [ ] Share new wallet ADDRESS with Claude
- [ ] Update .env with new wallet credentials
- [ ] Fund new wallet with ETH for gas
- [ ] Test with small amounts first
- [ ] Rescue 0.99 USDC from compromised wallet (if feasible)
- [ ] Update Render environment variables
- [ ] Run PC security audit (optional but recommended)

## Questions?

If you have any questions about this cleanup or the next steps, just ask!
