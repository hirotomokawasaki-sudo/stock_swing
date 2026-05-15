#!/bin/bash
# Test Massive WebSocket connection manually
# Requires: wscat (npm install -g wscat)

echo "=========================================="
echo "Massive WebSocket Connection Test"
echo "=========================================="
echo ""
echo "This script will guide you through testing the WebSocket connection."
echo ""
echo "Prerequisites:"
echo "  1. Install wscat: npm install -g wscat"
echo "  2. Have the auth token ready"
echo ""
echo "Steps:"
echo "  1. Connect to WebSocket"
echo "  2. Authenticate"
echo "  3. Subscribe to symbols"
echo "  4. Watch for data"
echo ""
echo "Press Enter to start..."
read

echo ""
echo "Step 1: Connecting to WebSocket..."
echo "URL: wss://nasdaq-basic-business.massive.com/stocks"
echo ""
echo "Run this command:"
echo ""
echo "  wscat -c wss://nasdaq-basic-business.massive.com/stocks"
echo ""
echo "After connection, you'll see: 'Connected (press CTRL+C to quit)'"
echo ""
echo "Step 2: Authenticate"
echo "Paste this JSON and press Enter:"
echo ""
echo '  {"action":"auth", "params":"jWjKRcHk7x8_egXHGCGrbWnS67dPgWtp"}'
echo ""
echo "You should see: {\"status\":\"auth_success\"} or similar"
echo ""
echo "Step 3: Subscribe to symbols"
echo "Paste this JSON and press Enter:"
echo ""
echo '  {"action":"subscribe", "params":"AM.AAPL,AM.MSFT"}'
echo ""
echo "You should see: {\"status\":\"success\", ...}"
echo ""
echo "Step 4: Watch for data"
echo "You'll start receiving 1-minute aggregate bars like:"
echo ""
echo '  {"ev":"AM","sym":"AAPL","v":123456,"o":150.20,"c":150.35,...}'
echo ""
echo "Press CTRL+C to disconnect when done."
echo ""
echo "=========================================="
echo ""
echo "Ready to run wscat? (y/n)"
read answer

if [ "$answer" = "y" ]; then
    echo "Launching wscat..."
    wscat -c wss://nasdaq-basic-business.massive.com/stocks
else
    echo "Run the command manually:"
    echo ""
    echo "  wscat -c wss://nasdaq-basic-business.massive.com/stocks"
    echo ""
fi
