#!/bin/bash
set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project)}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="receipt-scanner"
FIREBASE_SITE="auraparse"

echo -e "${RED}========================================${NC}"
echo -e "${RED}   EMERGENCY ROLLBACK PROTOCOL          ${NC}"
echo -e "${RED}========================================${NC}"
echo ""
echo -e "${YELLOW}Project:${NC} $PROJECT_ID"
echo -e "${YELLOW}Service:${NC} $SERVICE_NAME"
echo ""

# 1. CLOUD RUN ROLLBACK (Backend)
echo -e "${BLUE}[1/2] Backend Rollback (Cloud Run)${NC}"
echo "Fetching last 10 revisions..."
echo ""

# List revisions formatted nicely
gcloud run revisions list \
    --service $SERVICE_NAME \
    --region $REGION \
    --project $PROJECT_ID \
    --limit 10 \
    --format="table(name, author, createTime, state)"

echo ""
echo -e "${YELLOW}Copy the REVISION NAME you want to restore (e.g., receipt-scanner-00042-xez)${NC}"
read -p "Enter Revision Name to restore (or Press Ctrl+C to cancel): " TARGET_REVISION

if [ -z "$TARGET_REVISION" ]; then
    echo -e "${RED}No revision entered. Aborting.${NC}"
    exit 1
fi

echo ""
echo -e "Rolling back traffic to: ${GREEN}$TARGET_REVISION${NC}..."

# Execute Rollback
gcloud run services update-traffic $SERVICE_NAME \
    --to-revisions=$TARGET_REVISION=100 \
    --region $REGION \
    --project $PROJECT_ID \
    --quiet

echo -e "${GREEN}✓ Backend successfully rolled back to $TARGET_REVISION${NC}"
echo ""

# 2. FIREBASE HOSTING ROLLBACK (Frontend)
echo -e "${BLUE}[2/2] Frontend Rollback (Firebase)${NC}"
echo -e "Firebase Hosting rollbacks are safest via the Console to confirm the visual preview."
echo ""
echo -e "1. Go to this URL:"
echo -e "   ${YELLOW}https://console.firebase.google.com/project/$PROJECT_ID/hosting/sites/$FIREBASE_SITE${NC}"
echo -e "2. Find the previous 'Release' in the history list."
echo -e "3. Click the three dots (⋮) and select ${RED}'Rollback'${NC}."
echo ""

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   ROLLBACK OPERATIONS COMPLETE         ${NC}"
echo -e "${GREEN}========================================${NC}"