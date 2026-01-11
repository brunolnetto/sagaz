#!/bin/bash
#
# Test webhook status tracking with FastAPI integration
# Shows how saga execution status is tracked via correlation IDs
#

BASE_URL="http://localhost:8000"

echo "======================================================================"
echo "WEBHOOK STATUS TRACKING TEST"
echo "======================================================================"
echo ""
echo "This script demonstrates webhook status lifecycle:"
echo "  1. accepted → Event received"
echo "  2. queued → In processing queue"
echo "  3. processing → Firing event to trigger sagas"
echo "  4. triggered → Sagas running in background"
echo "  5. completed/failed → All sagas finished"
echo ""

# Test 1: Successful order
echo "----------------------------------------------------------------------"
echo "TEST 1: Successful Order (amount < $1000)"
echo "----------------------------------------------------------------------"

RESPONSE=$(curl -s -X POST $BASE_URL/webhooks/order_created \
  -H "Content-Type: application/json" \
  -d '{"order_id": "TEST-001", "amount": 99.99, "user_id": "user-123"}')

CORR_ID=$(echo $RESPONSE | python3 -c "import sys, json; print(json.load(sys.stdin)['correlation_id'])")
echo "✓ Webhook fired: $CORR_ID"
echo "  Response: $RESPONSE"
echo ""

# Check status immediately (should be queued/processing/triggered)
echo "Checking status immediately..."
curl -s $BASE_URL/webhooks/order_created/status/$CORR_ID | python3 -m json.tool
echo ""

# Wait for saga to complete
echo "Waiting 1 second for saga to complete..."
sleep 1

# Check final status (should be completed)
echo "Checking final status..."
curl -s $BASE_URL/webhooks/order_created/status/$CORR_ID | python3 -m json.tool
echo ""

# Test 2: Failed order (payment declined)
echo "----------------------------------------------------------------------"
echo "TEST 2: Failed Order (amount > $1000 triggers payment decline)"
echo "----------------------------------------------------------------------"

RESPONSE=$(curl -s -X POST $BASE_URL/webhooks/order_created \
  -H "Content-Type: application/json" \
  -d '{"order_id": "TEST-002", "amount": 1500.00, "user_id": "user-456"}')

CORR_ID=$(echo $RESPONSE | python3 -c "import sys, json; print(json.load(sys.stdin)['correlation_id'])")
echo "✓ Webhook fired: $CORR_ID"
echo "  Response: $RESPONSE"
echo ""

# Check status immediately
echo "Checking status immediately..."
curl -s $BASE_URL/webhooks/order_created/status/$CORR_ID | python3 -m json.tool
echo ""

# Wait for saga to fail
echo "Waiting 1 second for saga to fail..."
sleep 1

# Check final status (should be failed with error details)
echo "Checking final status..."
curl -s $BASE_URL/webhooks/order_created/status/$CORR_ID | python3 -m json.tool
echo ""

# Test 3: Multiple sagas (if configured)
echo "----------------------------------------------------------------------"
echo "TEST 3: Check webhook that doesn't trigger any sagas"
echo "----------------------------------------------------------------------"

RESPONSE=$(curl -s -X POST $BASE_URL/webhooks/unknown_event \
  -H "Content-Type: application/json" \
  -d '{"data": "test"}')

CORR_ID=$(echo $RESPONSE | python3 -c "import sys, json; print(json.load(sys.stdin)['correlation_id'])")
echo "✓ Webhook fired: $CORR_ID"
echo ""

sleep 0.5

echo "Checking status (should show 0 sagas triggered)..."
curl -s $BASE_URL/webhooks/unknown_event/status/$CORR_ID | python3 -m json.tool
echo ""

echo "======================================================================"
echo "SUMMARY"
echo "======================================================================"
echo ""
echo "Key Points:"
echo "  • Each webhook gets a unique correlation_id for tracking"
echo "  • Status progresses: accepted → processing → triggered → completed/failed"
echo "  • Individual saga outcomes tracked in 'saga_statuses'"
echo "  • Failed sagas show error details in 'saga_errors'"
echo "  • Status endpoint can be polled to monitor progress"
echo ""
echo "For production:"
echo "  • Use WebSocket or Server-Sent Events for real-time updates"
echo "  • Store correlation_id → saga_id mappings in Redis/DB"
echo "  • Implement exponential backoff for status polling"
echo ""
