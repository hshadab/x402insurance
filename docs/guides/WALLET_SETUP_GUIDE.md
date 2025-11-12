# Wallet Setup Guide - Base Sepolia

Complete guide to setting up a fresh MetaMask wallet for the x402 Insurance Service.

---

## Quick Start (5 Steps)

1. **Create new MetaMask account** (see below)
2. **Add Base Sepolia network** (see below)
3. **Get test ETH** from faucet
4. **Run setup script:** `python setup_wallet.py`
5. **Restart server**

---

## Step 1: Create Fresh MetaMask Account

### Method A: New Account in Existing Wallet (Recommended)

Best for keeping everything in one place:

1. Open MetaMask extension
2. Click account icon (top right, circle with colors)
3. Click **"Add account"** or **"Create account"**
4. Name it: `Base Insurance Backend`
5. Click **"Create"**
6. ✅ Done! You have a fresh address with no history

**Your new address will look like:**
```
0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb
```

### Method B: Completely New Wallet (Maximum Isolation)

For total separation:

1. Open MetaMask
2. Click account icon → **Lock**
3. On login screen, click **"Forgot password?"**
4. Click **"Create a new wallet"**
5. **CRITICAL:** Write down the 12-word seed phrase securely
6. Never share this phrase with anyone
7. ✅ New wallet created

⚠️ **Warning:** You'll need to switch wallets to access old accounts.

### Method C: New Browser Profile (Best for Developers)

Keep both wallets accessible:

**Chrome/Brave:**
1. Click profile icon (top right)
2. Click **"Add"**
3. Click **"Continue without an account"**
4. Name it: `Base Dev`
5. Install MetaMask in new profile
6. Create new wallet

**Firefox:**
1. Type `about:profiles` in address bar
2. Click **"Create a New Profile"**
3. Follow wizard
4. Launch new profile
5. Install MetaMask
6. Create new wallet

---

## Step 2: Add Base Sepolia Network

### Automatic Method (Easiest)

1. Go to https://chainlist.org
2. Search: `Base Sepolia`
3. Click **"Add to MetaMask"**
4. Approve in MetaMask
5. ✅ Done!

### Manual Method

1. Open MetaMask
2. Click network dropdown (top left, shows "Ethereum Mainnet")
3. Click **"Add network"**
4. Click **"Add a network manually"**
5. Enter these **exact** values:

```
Network Name:      Base Sepolia
RPC URL:          https://sepolia.base.org
Chain ID:         84532
Currency Symbol:  ETH
Block Explorer:   https://sepolia.basescan.org
```

6. Click **"Save"**
7. Switch to Base Sepolia network
8. ✅ Done!

---

## Step 3: Get Your Wallet Credentials

### Get Wallet Address

1. Open MetaMask
2. Click your account name to **copy address**
3. Paste somewhere safe (you'll need it)

Should look like: `0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb`

### Get Private Key

⚠️ **NEVER SHARE YOUR PRIVATE KEY WITH ANYONE**

1. Open MetaMask
2. Click **three dots (⋮)** next to your account name
3. Click **"Account details"**
4. Click **"Show private key"**
5. Enter your MetaMask password
6. Click **"Confirm"**
7. Click **"Hold to reveal"** and hold the button
8. **Copy private key** (starts with 0x)
9. Close the window (don't leave it open)

Should look like: `0x1234567890abcdef...` (64 hex characters after 0x)

---

## Step 4: Get Test Funds

### Get Test ETH (for gas fees)

**Option 1 - Coinbase Faucet (Recommended):**

1. Go to https://portal.cdp.coinbase.com/products/faucet
2. Sign in with Coinbase account (or create free account)
3. Select **"Base Sepolia"** network
4. Paste your wallet address
5. Click **"Request"**
6. Wait ~30 seconds
7. Check MetaMask - you should have 0.1 ETH!

**Option 2 - Alchemy Faucet:**

1. Go to https://www.alchemy.com/faucets/base-sepolia
2. Sign up/sign in (free)
3. Enter your wallet address
4. Complete captcha
5. Click **"Send Me ETH"**
6. Receive 0.05 ETH

**Option 3 - QuickNode Faucet:**

1. Go to https://faucet.quicknode.com/base/sepolia
2. Connect wallet or paste address
3. Request ETH

### Get Test USDC (Optional - for testing refunds)

The insurance service will send USDC refunds. To test receiving:

1. Go to Base Sepolia DEX or faucet
2. Swap some test ETH for test USDC
3. Or use USDC faucet if available

**USDC Contract on Base Sepolia:**
```
0x036CbD53842c5426634e7929541eC2318f3dCF7e
```

---

## Step 5: Run Automated Setup

Now run the setup script:

```bash
cd /home/hshadab/x402insurance
source venv/bin/activate
python setup_wallet.py
```

The script will:
1. ✅ Ask for your wallet address
2. ✅ Securely ask for private key (hidden input)
3. ✅ Validate both credentials
4. ✅ Update .env file
5. ✅ Test connection to Base Sepolia
6. ✅ Show your balance

### Example Session:

```
======================================================================
x402 Insurance Service - Wallet Setup
======================================================================

This script will securely configure your Base Sepolia wallet.

⚠️  SECURITY WARNINGS:
   • NEVER share your private key with anyone
   • NEVER commit .env to git
   • Only use testnet funds for development

Step 1: Wallet Address
----------------------------------------------------------------------
Enter your Base Sepolia wallet address (0x...): 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb
✅ Valid address: 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb

Step 2: Private Key
----------------------------------------------------------------------
⚠️  Your private key will NOT be displayed on screen
Enter your private key (0x...): [hidden input]
✅ Valid private key received

Step 3: Confirmation
----------------------------------------------------------------------
Address: 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb
Private key: ************************************************************ (hidden)

Update .env file with these credentials? (yes/no): yes

Step 4: Updating Configuration
----------------------------------------------------------------------
✅ Updated .env file

Step 5: Testing Connection
----------------------------------------------------------------------
✅ Wallet connected successfully!
   Address: 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb
   Balance: 0.1 ETH on Base Sepolia

======================================================================
✅ Wallet setup complete!
======================================================================
```

---

## Step 6: Restart Server

Restart the server to use your new wallet:

```bash
# Kill old server
pkill -f "python server.py"

# Start with new wallet
source venv/bin/activate
python server.py
```

You should see:

```
✅ zkEngine binary found at ./zkengine/fraud_detector
✅ Blockchain initialized with wallet: 0x742d35Cc...
✅ x402 middleware enabled for /insure endpoint
```

**NOT:**
```
⚠️  No private key, using MOCK mode for refunds
```

---

## Verification

### Check Server Status

```bash
curl http://localhost:8000/health
```

Should return:
```json
{
  "status": "healthy",
  "zkengine": "operational",
  "blockchain": "connected"
}
```

### Check Wallet in .env

```bash
cat .env | grep BACKEND_WALLET
```

Should show:
```
BACKEND_WALLET_ADDRESS=0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb
BACKEND_WALLET_PRIVATE_KEY=0x1234... (your key)
```

### Test Blockchain Connection

```bash
python -c "
from blockchain import BlockchainClient
from dotenv import load_dotenv
import os

load_dotenv()

client = BlockchainClient(
    rpc_url='https://sepolia.base.org',
    usdc_address='0x036CbD53842c5426634e7929541eC2318f3dCF7e',
    private_key=os.getenv('BACKEND_WALLET_PRIVATE_KEY')
)

print(f'✅ Connected: {client.account.address}')
"
```

---

## Security Checklist

Before going live, verify:

- [ ] Using a fresh wallet address (no old transaction history)
- [ ] Private key is stored only in .env
- [ ] .env is in .gitignore
- [ ] Only using testnet (Base Sepolia)
- [ ] Have test ETH for gas
- [ ] Server shows "Blockchain initialized with wallet"
- [ ] Never shared private key with anyone
- [ ] Saved seed phrase in safe location (if new wallet)

---

## Troubleshooting

### "Insufficient funds for gas"

**Problem:** Wallet has no ETH for gas fees

**Solution:** Get test ETH from faucet (see Step 4)

### "Invalid private key"

**Problem:** Private key format is wrong

**Solution:**
- Must start with `0x`
- Must be 66 characters total (0x + 64 hex characters)
- Copy from MetaMask exactly (don't add/remove characters)

### "Cannot connect to RPC"

**Problem:** Base Sepolia RPC is down

**Solution:**
- Try alternative RPC: `https://base-sepolia-rpc.publicnode.com`
- Update in .env: `BASE_RPC_URL=https://base-sepolia-rpc.publicnode.com`

### "Address/key mismatch"

**Problem:** Private key doesn't match address

**Solution:**
- Re-export private key from correct account
- Make sure you're on the right account in MetaMask

---

## What's Next?

After wallet setup is complete:

1. ✅ **x402 payments** - Working with real middleware
2. ✅ **zkEngine proofs** - Working with real Nova/Arecibo
3. ✅ **USDC refunds** - Now working with real blockchain!

Your insurance service is now **fully functional** with:
- Real x402 payment verification
- Real zero-knowledge proofs
- Real USDC refunds on Base Sepolia

Ready to deploy! 🚀

---

## Quick Commands Reference

```bash
# Setup wallet
python setup_wallet.py

# Restart server
pkill -f "python server.py"
source venv/bin/activate && python server.py

# Check health
curl http://localhost:8000/health

# View wallet config
cat .env | grep BACKEND_WALLET

# Test connection
python -c "from blockchain import BlockchainClient; print('✅ Connected')"
```

---

## Support

If you need help:

1. Check server logs for errors
2. Verify wallet has test ETH
3. Confirm Base Sepolia network is added
4. Make sure .env has correct address and key
5. Try alternative RPC if connection fails

**Remember:** This is testnet only - never use mainnet for development!
