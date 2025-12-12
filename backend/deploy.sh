#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project)}"
REGION="us-central1" # KEEP THIS US-CENTRAL1 to match your DB
SERVICE_NAME="receipt-scanner"
SA_NAME="receipt-scanner-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
FIREBASE_SITE="auraparse"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   AuraParse - Deployment Script        ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${GREEN}Project ID:${NC} $PROJECT_ID"
echo -e "${GREEN}Region:${NC} $REGION"
echo -e "${GREEN}Service:${NC} $SERVICE_NAME"
echo -e "${GREEN}Site Name:${NC} $FIREBASE_SITE"
echo ""

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check prerequisites
echo -e "${BLUE}[1/9] Checking prerequisites...${NC}"
if ! command_exists gcloud; then
    echo -e "${RED}ERROR: gcloud CLI not found.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ gcloud CLI found${NC}"

# Verify project
if [ -z "$PROJECT_ID" ]; then
    echo -e "${RED}ERROR: No project ID set.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Project ID set${NC}"

# Enable required APIs
echo -e "${BLUE}[2/9] Enabling required APIs...${NC}"
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    secretmanager.googleapis.com \
    iam.googleapis.com \
    firebasehosting.googleapis.com \
    --project=$PROJECT_ID \
    --quiet 2>/dev/null || true
echo -e "${GREEN}✓ APIs enabled${NC}"

# Create service account (idempotent)
echo -e "${BLUE}[3/9] Creating service account...${NC}"
if gcloud iam service-accounts describe $SA_EMAIL --project=$PROJECT_ID >/dev/null 2>&1; then
    echo -e "${YELLOW}Service account already exists${NC}"
else
    gcloud iam service-accounts create $SA_NAME \
        --display-name="Receipt Scanner Service Account" \
        --project=$PROJECT_ID
    echo -e "${GREEN}✓ Service account created${NC}"
fi

# Grant IAM roles
echo -e "${BLUE}[4/9] Granting IAM roles...${NC}"
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/secretmanager.secretAccessor" \
    --condition=None --quiet 2>/dev/null || true

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/run.invoker" \
    --condition=None --quiet 2>/dev/null || true
echo -e "${GREEN}✓ IAM roles granted${NC}"

# Secrets Management
echo -e "${BLUE}[5/9] Setting up secrets...${NC}"

handle_secret() {
    local NAME=$1
    local PROMPT=$2
    if gcloud secrets describe $NAME --project=$PROJECT_ID >/dev/null 2>&1; then
        echo -e "${YELLOW}Secret '$NAME' exists. Skipping.${NC}"
    else
        if [ -z "$3" ]; then
            read -sp "$PROMPT" SECRET_VAL
            echo
        else
            SECRET_VAL=$3
        fi
        
        if [ ! -z "$SECRET_VAL" ]; then
            echo -n "$SECRET_VAL" | gcloud secrets create $NAME --data-file=- --project=$PROJECT_ID
            echo -e "${GREEN}✓ $NAME created${NC}"
        else
            echo -e "${YELLOW}⚠ Skipped $NAME${NC}"
        fi
    fi
}

handle_secret "gemini-api-key" "Enter Gemini API Key: "
handle_secret "stripe-secret-key" "Enter Stripe Secret Key: "
handle_secret "stripe-webhook-secret" "Enter Stripe Webhook Secret: "

if ! gcloud secrets describe api-keys --project=$PROJECT_ID >/dev/null 2>&1; then
    echo -n "sk_live_$(openssl rand -hex 16)" | gcloud secrets create api-keys --data-file=- --project=$PROJECT_ID
    echo -e "${GREEN}✓ api-keys created${NC}"
fi
if ! gcloud secrets describe admin-secret --project=$PROJECT_ID >/dev/null 2>&1; then
    echo -n "$(openssl rand -hex 32)" | gcloud secrets create admin-secret --data-file=- --project=$PROJECT_ID
    echo -e "${GREEN}✓ admin-secret created${NC}"
fi
if ! gcloud secrets describe cron-secret --project=$PROJECT_ID >/dev/null 2>&1; then
    echo -n "$(openssl rand -hex 32)" | gcloud secrets create cron-secret --data-file=- --project=$PROJECT_ID
    echo -e "${GREEN}✓ cron-secret created${NC}"
fi

for SECRET in gemini-api-key api-keys stripe-secret-key stripe-webhook-secret admin-secret cron-secret; do
    gcloud secrets add-iam-policy-binding $SECRET --member="serviceAccount:$SA_EMAIL" --role="roles/secretmanager.secretAccessor" --project=$PROJECT_ID --quiet 2>/dev/null || true
done

# Firestore
echo -e "${BLUE}[6/9] Checking Firestore...${NC}"
if gcloud firestore databases describe --project=$PROJECT_ID >/dev/null 2>&1; then
    echo -e "${YELLOW}Firestore enabled${NC}"
else
    # Attempt creation in us-central1 (Compatible with Cloud Run location)
    echo -e "${GREEN}Creating Firestore...${NC}"
    gcloud firestore databases create --location=us-central1 --project=$PROJECT_ID --quiet || echo -e "${YELLOW}Firestore might already exist (Check console)${NC}"
fi

# Build and Deploy
echo -e "${BLUE}[7/9] Deploying to Cloud Run (Performance Optimized)...${NC}"

cat > Procfile <<EOF
web: uvicorn main:app --host 0.0.0.0 --port \$PORT
EOF

# NOTE: Changed max-instances to 50 to respect new account limits.
# 50 instances * 8 concurrency = 400 concurrent requests (Massive capacity).
gcloud run deploy $SERVICE_NAME \
    --source . \
    --platform managed \
    --region $REGION \
    --service-account $SA_EMAIL \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 4 \
    --timeout 120s \
    --max-instances 50 \
    --min-instances 0 \
    --concurrency 20 \
    --execution-environment gen2 \
    --cpu-boost \
    --set-secrets=GEMINI_API_KEY=gemini-api-key:latest,API_KEYS=api-keys:latest,STRIPE_SECRET_KEY=stripe-secret-key:latest,STRIPE_WEBHOOK_SECRET=stripe-webhook-secret:latest,ADMIN_SECRET=admin-secret:latest,CRON_SECRET=cron-secret:latest \
    --project=$PROJECT_ID \
    --quiet

echo -e "${GREEN}✓ Backend deployed${NC}"

# Get URL
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --platform managed --region $REGION --project=$PROJECT_ID --format 'value(status.url)')

# Frontend Deployment
echo -e "${BLUE}[8/9] Deploying Frontend ($FIREBASE_SITE)...${NC}"
cd ..
if [ -d "public" ]; then
    if command_exists firebase; then
        
        SITE_EXISTS=$(firebase hosting:sites:list --project $PROJECT_ID 2>/dev/null | grep -w "$FIREBASE_SITE" || echo "")
        if [ -z "$SITE_EXISTS" ]; then
            echo -e "${BLUE}Creating site $FIREBASE_SITE...${NC}"
            firebase hosting:sites:create $FIREBASE_SITE --project $PROJECT_ID || echo -e "${YELLOW}Site might already exist.${NC}"
        fi

        cat > .firebaserc << EOF
{
  "projects": {
    "default": "$PROJECT_ID"
  },
  "targets": {
    "$PROJECT_ID": {
      "hosting": {
        "app": ["$FIREBASE_SITE"]
      }
    }
  }
}
EOF

        cat > firebase.json << EOF
{
  "hosting": {
    "target": "app",
    "public": "public",
    "ignore": ["firebase.json", "**/.*", "**/node_modules/**"],
    "rewrites": [
      { "source": "/api/**", "run": { "serviceId": "$SERVICE_NAME", "region": "$REGION" } },
      { "source": "/docs", "run": { "serviceId": "$SERVICE_NAME", "region": "$REGION" } },
      { "source": "/openapi.json", "run": { "serviceId": "$SERVICE_NAME", "region": "$REGION" } },
      { "source": "**", "destination": "/index.html" }
    ]
  }
}
EOF
        
        FRONTEND_URL="https://$FIREBASE_SITE.web.app"
        echo -e "${BLUE}Updating index.html API_URL to $FRONTEND_URL...${NC}"
        
        if [ -f "public/index.html" ]; then
            sed -i.bak "s|const API_URL = 'https://[^']*'|const API_URL = '$FRONTEND_URL'|g" public/index.html 2>/dev/null || \
            sed -i '' "s|const API_URL = 'https://[^']*'|const API_URL = '$FRONTEND_URL'|g" public/index.html
            rm -f public/index.html.bak
        fi

        firebase deploy --only hosting:app --project $PROJECT_ID
        
        echo -e "${GREEN}✓ Frontend deployed to $FRONTEND_URL${NC}"
    else
        echo -e "${RED}Firebase CLI missing.${NC}"
    fi
else
    echo -e "${YELLOW}No public folder found.${NC}"
fi
cd backend

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   AURAPARSE DEPLOYMENT COMPLETE 🚀     ${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "Website:      https://$FIREBASE_SITE.web.app"
echo -e "Docs:         https://$FIREBASE_SITE.web.app/docs"
echo -e "Backend:      $SERVICE_URL"
echo ""