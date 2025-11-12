#!/bin/bash
# Build and push Docker image to Docker Hub for fast Render deployment
# This avoids rebuilding on every Render deployment (10x faster)

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}===========================================${NC}"
echo -e "${BLUE}  x402 Insurance - Docker Build & Push${NC}"
echo -e "${BLUE}===========================================${NC}\n"

# Load config
if [ -f .dockerhub ]; then
    source .dockerhub
else
    echo -e "${YELLOW}⚠️  No .dockerhub config found${NC}"
    echo -e "${YELLOW}Using default: hshadab/x402insurance${NC}\n"
    DOCKER_USERNAME="hshadab"
    IMAGE_NAME="x402insurance"
fi

# Get version from git or default
VERSION=$(git describe --tags --always 2>/dev/null || echo "latest")
FULL_IMAGE="${DOCKER_USERNAME}/${IMAGE_NAME}"

echo -e "${BLUE}Configuration:${NC}"
echo -e "  Docker Hub User: ${GREEN}${DOCKER_USERNAME}${NC}"
echo -e "  Image Name:      ${GREEN}${IMAGE_NAME}${NC}"
echo -e "  Version:         ${GREEN}${VERSION}${NC}"
echo -e "  Full Image:      ${GREEN}${FULL_IMAGE}:${VERSION}${NC}\n"

# Check if logged into Docker Hub
echo -e "${BLUE}Step 1: Checking Docker Hub authentication...${NC}"
if ! docker info | grep -q "Username: ${DOCKER_USERNAME}" 2>/dev/null; then
    echo -e "${YELLOW}⚠️  Not logged into Docker Hub${NC}"
    echo -e "${YELLOW}Please run: docker login${NC}"
    echo -e "${YELLOW}Then re-run this script${NC}\n"

    read -p "Login now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        docker login
    else
        echo -e "${RED}❌ Aborted. Please login first.${NC}"
        exit 1
    fi
fi
echo -e "${GREEN}✓ Authenticated${NC}\n"

# Build the image
echo -e "${BLUE}Step 2: Building Docker image...${NC}"
echo -e "Using Dockerfile: ${GREEN}Dockerfile.render${NC}\n"

docker build \
    -f Dockerfile.render \
    -t "${FULL_IMAGE}:${VERSION}" \
    -t "${FULL_IMAGE}:latest" \
    --platform linux/amd64 \
    .

if [ $? -eq 0 ]; then
    echo -e "\n${GREEN}✓ Build successful${NC}\n"
else
    echo -e "\n${RED}❌ Build failed${NC}"
    exit 1
fi

# Show image size
IMAGE_SIZE=$(docker images "${FULL_IMAGE}:latest" --format "{{.Size}}")
echo -e "${BLUE}Image size: ${GREEN}${IMAGE_SIZE}${NC}\n"

# Push to Docker Hub
echo -e "${BLUE}Step 3: Pushing to Docker Hub...${NC}"
echo -e "This may take 2-3 minutes (uploading layers)...\n"

docker push "${FULL_IMAGE}:${VERSION}"
docker push "${FULL_IMAGE}:latest"

if [ $? -eq 0 ]; then
    echo -e "\n${GREEN}✓ Push successful${NC}\n"
else
    echo -e "\n${RED}❌ Push failed${NC}"
    exit 1
fi

# Success summary
echo -e "${GREEN}===========================================${NC}"
echo -e "${GREEN}  ✓ Docker Image Published${NC}"
echo -e "${GREEN}===========================================${NC}\n"

echo -e "${BLUE}Your image is now available at:${NC}"
echo -e "  ${GREEN}docker.io/${FULL_IMAGE}:latest${NC}"
echo -e "  ${GREEN}docker.io/${FULL_IMAGE}:${VERSION}${NC}\n"

echo -e "${BLUE}Next Steps:${NC}"
echo -e "  1. Go to Render Dashboard: ${YELLOW}https://dashboard.render.com${NC}"
echo -e "  2. Click: ${YELLOW}New → Web Service → Deploy an existing image${NC}"
echo -e "  3. Enter image URL: ${GREEN}docker.io/${FULL_IMAGE}:latest${NC}"
echo -e "  4. Set environment variables (see .env.example)"
echo -e "  5. Deploy! ${GREEN}(~30-60 seconds)${NC}\n"

echo -e "${BLUE}Or update existing service:${NC}"
echo -e "  Settings → Image URL → ${GREEN}docker.io/${FULL_IMAGE}:latest${NC}"
echo -e "  Then trigger a manual deploy\n"

echo -e "${YELLOW}💡 Tip: Run this script whenever you make code changes${NC}"
echo -e "${YELLOW}   Render will auto-deploy the new image${NC}\n"
