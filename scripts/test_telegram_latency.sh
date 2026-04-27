#!/bin/bash
# Telegram latency test script

echo "=== Telegram Latency Test ==="
echo "Send a message from Telegram NOW and press Enter when done"
read

START_TIME=$(date +%s)
echo "Message sent at: $(date)"
echo "Waiting for response..."
echo ""
echo "When you receive my response, record the timestamp and calculate:"
echo "  Latency = Response Time - $START_TIME seconds"
echo ""
echo "Typical latencies:"
echo "  - Webhook mode: <5 seconds"
echo "  - Short polling: 5-30 seconds"
echo "  - Long polling: 30-120 seconds"
