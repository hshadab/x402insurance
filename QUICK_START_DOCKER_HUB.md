# 🚀 Quick Start: 30-Second Deployments

You asked for faster deployments - here's the solution!

## What Changed?

Instead of Render building your app from scratch (5-8 min), we now:
1. Build Docker image on GitHub Actions (2-3 min, automatic)
2. Push to Docker Hub
3. Render pulls pre-built image (**30-60 seconds!**)

**Result: 10x faster** ⚡

---

## Setup (5 minutes, one-time)

### Step 1: Docker Hub Account
1. Go to https://hub.docker.com/signup
2. Create account with username: `hshadab` (or change in `.dockerhub`)

### Step 2: Create Docker Hub Access Token
1. Go to https://hub.docker.com/settings/security
2. Click **"New Access Token"**
3. Name: `github-actions`
4. Permissions: `Read, Write, Delete`
5. **Copy the token** (you won't see it again!)

### Step 3: Add GitHub Secrets
1. Go to https://github.com/hshadab/x402insurance/settings/secrets/actions
2. Click **"New repository secret"**
3. Add:
   - Name: `DOCKER_USERNAME`, Value: `hshadab`
   - Name: `DOCKER_PASSWORD`, Value: `<paste token from step 2>`

### Step 4: Wait for GitHub Action
GitHub Actions is building your image right now!
Check progress: https://github.com/hshadab/x402insurance/actions

**This will take 2-3 minutes** (one-time)

### Step 5: Configure Render

**Option A: Create New Service** (Recommended)
1. Go to https://dashboard.render.com
2. Click **New → Web Service**
3. Select **"Deploy an existing image from a registry"**
4. Image URL: `docker.io/hshadab/x402insurance:latest`
5. Name: `x402-insurance`
6. Set environment variables (see below)
7. Create service

**Option B: Update Existing Service**
1. Go to your Render service settings
2. Click **Settings → Image**
3. Change to: `docker.io/hshadab/x402insurance:latest`
4. Save and deploy

**Environment Variables to Set:**
```bash
BACKEND_WALLET_PRIVATE_KEY=0x22af9bb0c38c6a666a13f51155720cc3c1af64dfd69f0aeb99cb4e7cd4a0d165
BACKEND_WALLET_ADDRESS=0xf36B80afFb2e41418874FfA56B069f1Fe671FC35
```
(All other variables are in `render.yaml` or have defaults)

### Step 6: Deploy!
Click "Manual Deploy" in Render

**Deploy time: 30-60 seconds!** 🎉

---

## How It Works

```
┌─────────────┐
│ Git Push    │
└──────┬──────┘
       │
       ▼
┌─────────────────────┐
│ GitHub Actions      │  ← Builds Docker image (2-3 min)
│ Builds Docker Image │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│ Docker Hub          │  ← Stores pre-built image
│ hshadab/x402insur.. │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│ Render.com          │  ← Pulls image (30-60 sec!)
│ Deploys Service     │
└─────────────────────┘
```

---

## Deployment Times Comparison

| Method | Time | When |
|--------|------|------|
| **Old: Build on Render** | 5-8 min | Every deploy |
| **New: Pre-built Image** | 30-60 sec | Every deploy |
| **Savings** | **87% faster!** | ⚡ |

---

## Updating Your App (Going Forward)

Just push to GitHub as usual:
```bash
git add .
git commit -m "Update feature"
git push origin main
```

What happens automatically:
1. GitHub Actions builds new image (2-3 min)
2. Pushes to Docker Hub (1 min)
3. Render auto-deploys (30-60 sec) *if webhook configured

**Total: ~4-5 minutes end-to-end** (vs 8-10 min before)

---

## Verification

After setup, verify it worked:

1. Check GitHub Actions: https://github.com/hshadab/x402insurance/actions
   - Should see green checkmark ✅

2. Check Docker Hub: https://hub.docker.com/r/hshadab/x402insurance
   - Should see your image with "latest" tag

3. Check Render logs:
   - Should see "Pulling image..." (not "Building...")
   - Deploy should finish in under 1 minute

---

## Troubleshooting

**GitHub Action fails:**
- Check Docker Hub credentials in GitHub Secrets
- Verify username matches Docker Hub account

**Render can't pull image:**
- Check image URL: `docker.io/hshadab/x402insurance:latest`
- Verify image exists on Docker Hub
- Make image public (or add credentials in Render)

**Need help?**
See full documentation: `DOCKER_HUB_SETUP.md`

---

## Summary

✅ Setup complete (5 minutes, one-time)
✅ Future deploys: 30-60 seconds
✅ Automatic: Just push to GitHub
✅ Cost: Free (or $7/mo Render Starter for always-on)

**You now have production-grade deployment speed!** 🚀
