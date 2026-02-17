#!/bin/bash
set -e

# MWP Modal Recording App - Deployment Script
# Ensures consistent updates to the same app deployment

echo "=== MWP Modal Recording App Deploy ==="
echo ""

# Configuration
APP_NAME="mwp-recording-app"
APP_FILE="modal_app/recording_app.py"
EXPECTED_URL="https://YOUR_MODAL_USERNAME--mwp-recording-app-web.modal.run"

echo "App Name: $APP_NAME"
echo "App File: $APP_FILE"
echo "Expected URL: $EXPECTED_URL"
echo ""

# Verify app file exists
if [ ! -f "$APP_FILE" ]; then
    echo "✗ Error: App file not found: $APP_FILE"
    exit 1
fi

# Check if Modal CLI is installed
if ! command -v modal &> /dev/null; then
    echo "✗ Error: Modal CLI not installed"
    echo "  Install with: pip install modal"
    exit 1
fi

echo "[1/3] Checking current deployments..."
CURRENT_DEPLOYMENTS=$(modal app list 2>/dev/null || echo "")

if echo "$CURRENT_DEPLOYMENTS" | grep -q "$APP_NAME"; then
    echo "  ✓ App '$APP_NAME' exists, will update existing deployment"
else
    echo "  ⚠ App '$APP_NAME' not found, will create new app"
fi

echo ""
echo "[2/3] Deploying to Modal..."
modal deploy "$APP_FILE"

echo ""
echo "[3/3] Verifying deployment..."

# Wait a moment for deployment to be ready
sleep 3

# Check if the deployment is accessible
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$EXPECTED_URL" || echo "000")

if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "405" ]; then
    echo "  ✓ Deployment successful and accessible"
else
    echo "  ⚠ Deployment returned HTTP $HTTP_CODE (may still be starting)"
fi

echo ""
echo "=== Deploy Complete ==="
echo ""
echo "📱 App URL: $EXPECTED_URL"
echo "📊 Dashboard: https://modal.com/apps/$(modal token current 2>/dev/null)/deployed/$APP_NAME"
echo ""
echo "The deployment will update the existing app. Bookmarked URL remains the same."
