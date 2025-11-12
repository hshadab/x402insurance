# Docker Hub Pre-Built Image Setup
**Deploy to Render in 30-60 seconds instead of 5+ minutes!**

## Overview

Instead of Render building your Docker image from scratch every time (slow), we'll:
1. Build the image once locally or via GitHub Actions (3-5 min)
2. Push it to Docker Hub
3. Render pulls the pre-built image (30-60 seconds)

**Result: 10x faster deployments** ⚡

---

## Option 1: Automatic (GitHub Actions) ⭐ RECOMMENDED

### Step 1: Set up Docker Hub

1. **Create Docker Hub account** (if you don't have one)
   - Go to https://hub.docker.com/signup
   - Use username: `hshadab` (or your preferred username)

2. **Create Access Token**
   - Go to https://hub.docker.com/settings/security
   - Click "New Access Token"
   - Name: `github-actions`
   - Permissions: `Read, Write, Delete`
   - Copy the token (you won't see it again!)

### Step 2: Add GitHub Secrets

1. Go to your GitHub repo: https://github.com/hshadab/x402insurance
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Add two secrets:

   **Secret 1:**
   - Name: `DOCKER_USERNAME`
   - Value: `hshadab` (your Docker Hub username)

   **Secret 2:**
   - Name: `DOCKER_PASSWORD`
   - Value: `<paste your Docker Hub access token>`

### Step 3: Push to GitHub (trigger build)

The GitHub Action will automatically:
- Build the Docker image
- Push to Docker Hub as `hshadab/x402insurance:latest`
- Complete in ~2-3 minutes

Check progress: https://github.com/hshadab/x402insurance/actions

### Step 4: Configure Render to use the image

**Option A: Create new service (recommended)**
1. Go to https://dashboard.render.com
2. Click **New** → **Web Service**
3. Select **Deploy an existing image from a registry**
4. Enter image URL: `docker.io/hshadab/x402insurance:latest`
5. Name: `x402-insurance`
6. Region: `Oregon` (or closest to you)
7. Plan: `Starter` (free or $7/mo)

**Add environment variables:**
```bash
ENV=production
FLASK_ENV=production
PORT=8000
BASE_RPC_URL=https://mainnet.base.org
USDC_CONTRACT_ADDRESS=0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
CHAIN_ID=8453
ZKENGINE_BINARY_PATH=./zkengine/fraud_detector
PREMIUM_PERCENTAGE=0.01
MAX_COVERAGE_USDC=0.1
POLICY_DURATION_HOURS=24
PAYMENT_VERIFICATION_MODE=full

# SECRETS (set these):
BACKEND_WALLET_PRIVATE_KEY=<your-private-key>
BACKEND_WALLET_ADDRESS=<your-wallet-address>
```

8. Click **Create Web Service**
9. **Deploy time: 30-60 seconds!** ⚡

**Option B: Update existing service**
1. Go to your existing Render service
2. Click **Settings** → **Image**
3. Change from "Build from Git" to "Deploy an existing image"
4. Enter: `docker.io/hshadab/x402insurance:latest`
5. Save changes
6. Trigger manual deploy

### Step 5: Enable auto-deploy (optional)

Configure Render to auto-deploy when new images are pushed:

1. In Render service settings → **Deploy Hook**
2. Copy the webhook URL
3. Go to Docker Hub: https://hub.docker.com/repository/docker/hshadab/x402insurance/webhooks
4. Add webhook:
   - Name: `render-deploy`
   - URL: `<paste Render deploy hook URL>`

Now every push to GitHub will:
1. GitHub Actions builds image (~2-3 min)
2. Pushes to Docker Hub (~1 min)
3. Render auto-deploys (~30-60 sec)
4. **Total: ~4-5 min end-to-end** (vs 8-10 min before)

---

## Option 2: Manual (Build Locally)

### Step 1: Login to Docker Hub

```bash
docker login
# Enter your Docker Hub username and password
```

### Step 2: Build and push

Run the automated script:
```bash
./scripts/build-and-push.sh
```

Or manually:
```bash
# Build
docker build -f Dockerfile.render -t hshadab/x402insurance:latest --platform linux/amd64 .

# Push
docker push hshadab/x402insurance:latest
```

**Build time: 3-5 minutes** (one-time)

### Step 3: Configure Render

Same as Step 4 in Option 1 above.

---

## Comparison: Build Times

| Method | First Deploy | Subsequent Deploys | Notes |
|--------|--------------|-------------------|-------|
| **Git Build (old)** | 8-10 min | 5-7 min | Render builds from scratch |
| **Pre-built Image** | 30-60 sec | 30-60 sec | Just pulls image |
| **GitHub Actions** | 4-5 min | 4-5 min | Build + auto-deploy |

**Best of both worlds**: GitHub Actions (automatic) + Pre-built Image (fast Render deploys)

---

## Updating Your App

### With GitHub Actions (automatic):
```bash
# Make code changes
git add .
git commit -m "Update feature"
git push origin main

# GitHub Actions will:
# 1. Build new image (2-3 min)
# 2. Push to Docker Hub (1 min)
# 3. Render auto-deploys (30-60 sec)
# Total: ~4-5 minutes
```

### Manual:
```bash
# Make code changes
./scripts/build-and-push.sh   # Build and push new image

# Then in Render dashboard:
# Click "Manual Deploy" or wait for webhook
```

---

## Troubleshooting

### GitHub Action fails with "unauthorized"
- Check Docker Hub credentials in GitHub Secrets
- Verify username: `DOCKER_USERNAME` = `hshadab`
- Verify token: `DOCKER_PASSWORD` = your access token (not password!)

### Render fails to pull image
- Check image URL: `docker.io/hshadab/x402insurance:latest`
- Verify image is public on Docker Hub (or add Docker Hub credentials in Render)
- Check Docker Hub status: https://status.docker.com

### Image is too large
Current image: ~150-200MB (normal for Python + web3)
- If over 500MB, check what's being copied
- Verify `.dockerignore` excludes venv/, .git/, tests/

### Want to use private registry
Instead of Docker Hub, use:
- GitHub Container Registry (ghcr.io)
- AWS ECR
- Google Container Registry

Update `DOCKER_IMAGE` in `.github/workflows/docker-build.yml`

---

## Cost Breakdown

| Service | Plan | Cost | Purpose |
|---------|------|------|---------|
| Docker Hub | Free | $0 | Store images (1 private repo, unlimited public) |
| GitHub Actions | Free | $0 | Build images (2000 min/month free) |
| Render | Starter | $7/mo | Host the app |
| **Total** | | **$7/mo** | Full production setup |

**Free tier option:**
- Docker Hub: Free (public repos)
- GitHub Actions: Free (within limits)
- Render: Free tier (spins down after inactivity)
- **Total: $0/mo**

---

## Next Steps

1. ✅ Follow Option 1 (GitHub Actions) above
2. ✅ Push this commit to trigger first build
3. ✅ Configure Render to use Docker Hub image
4. ✅ Enable auto-deploy webhook
5. 🎉 Enjoy 30-60 second deployments!

---

## Files Reference

- `.github/workflows/docker-build.yml` - GitHub Actions workflow
- `scripts/build-and-push.sh` - Manual build script
- `Dockerfile.render` - Optimized production Dockerfile
- `.dockerhub` - Docker Hub configuration
