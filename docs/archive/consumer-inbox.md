# Consumer Inbox Pattern

## Overview

The consumer inbox pattern ensures exactly-once message processing on the consumer side, even with at-least-once delivery guarantees from message brokers. This is the complementary pattern to the transactional outbox.

## Problem Statement

Message brokers typically provide **at-least-once delivery**:
- Messages may be delivered multiple times
- Consumer crashes before ack → message redelivered
- Network issues → message redelivered
- Kafka rebalancing → message redelivered

**Without inbox:** Your business logic may execute multiple times, causing:
- Duplicate charges to customers
- Double inventory deductions
- Inconsistent state

**With inbox:** Duplicates are automatically detected and skipped.

## How It Works

```
Traditional Flow (Not Idempotent):
1. Receive message from broker
2. Process business logic
3. Ack message
❌ If #2 crashes, message redelivered and processed again

Inbox Flow (Exactly-Once):
1. Receive message from broker
2. Check inbox: "Have I seen this message_id before?"
   - If YES: Skip processing, ack message ✅
   - If NO: Continue to #3
3. Begin database transaction:
   a. Insert message_id into inbox table
   b. Execute business logic
   c. Commit transaction
4. Ack message
✅ Duplicate messages automatically skipped
```

## Usage

### Basic Setup

```python
from sagaz.outbox import ConsumerInbox
from sagaz.outbox.storage import PostgreSQLOutboxStorage

# Initialize storage
storage = PostgreSQLOutboxStorage("postgresql://localhost/db")
await storage.initialize()

# Create inbox for this consumer service
inbox = ConsumerInbox(
    storage=storage,
    consumer_name="order-service"  # Unique per microservice
)
```

### Processing Messages

```python
# Define your business logic
async def process_order(payload: dict):
    order_id = payload['order_id']
    amount = payload['amount']
    
    # Your business logic here
    order = await create_order_in_db(order_id, amount)
    await send_confirmation_email(order_id)
    
    return {"order_id": order.id, "status": "created"}

# In your Kafka consumer loop
async for message in consumer:
    # Extract event ID from message headers
    event_id = message.headers.get('message_id') or message.key
    
    # Process idempotently
    result = await inbox.process_idempotent(
        event_id=event_id,              # Unique event ID
        source_topic=message.topic,      # For tracking
        event_type="OrderCreated",       # For metrics
        payload=message.value,           # Event payload
        handler=process_order            # Your business logic
    )
    
    if result is None:
        logger.info(f"Duplicate message {event_id}, skipped")
    else:
        logger.info(f"Processed message {event_id}: {result}")
    
    # Ack message
    await consumer.commit()
```

## Database Schema

The inbox uses a simple table for deduplication:

```sql
CREATE TABLE consumer_inbox (
    event_id            UUID PRIMARY KEY,           -- Deduplication key
    consumer_name       VARCHAR(255) NOT NULL,      -- Service name
    source_topic        VARCHAR(255) NOT NULL,      -- Message source
    event_type          VARCHAR(255) NOT NULL,      -- For metrics
    payload             JSONB NOT NULL,             -- Event data
    consumed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processing_duration_ms INTEGER                  -- Performance tracking
);

-- Index for cleanup queries
CREATE INDEX idx_consumer_inbox_cleanup
    ON consumer_inbox (consumer_name, consumed_at);
```

## Configuration

### Consumer Name

Each microservice should have a unique consumer name:

```python
# ✅ CORRECT - Unique per service
order_service_inbox = ConsumerInbox(storage, "order-service")
inventory_service_inbox = ConsumerInbox(storage, "inventory-service")
notification_service_inbox = ConsumerInbox(storage, "notification-service")

# ❌ WRONG - Same name across services
inbox = ConsumerInbox(storage, "my-service")  # All services share!
```

### Event ID Selection

The event ID must be:
1. **Unique** - Different for each event
2. **Stable** - Same value on redelivery
3. **Available** - Present in every message

```python
# ✅ CORRECT - Stable, unique ID from producer
event_id = message.headers['message_id']  # From outbox event_id
event_id = message.key.decode()           # Kafka message key
event_id = payload['event_id']            # From payload

# ❌ WRONG - Not stable across redeliveries
event_id = str(uuid.uuid4())              # New on each delivery!
event_id = message.offset                 # Changes on rebalance
```

## Monitoring

### Prometheus Metrics

```python
# Total events processed (first time)
consumer_inbox_processed_total{consumer_name, event_type}

# Total duplicates skipped
consumer_inbox_duplicates_total{consumer_name, event_type}

# Processing duration histogram
consumer_inbox_processing_duration_seconds{consumer_name, event_type}
```

### Grafana Queries

```promql
# Duplicate rate
rate(consumer_inbox_duplicates_total[5m]) /
(rate(consumer_inbox_processed_total[5m]) + 
 rate(consumer_inbox_duplicates_total[5m]))

# Average processing time
avg(rate(consumer_inbox_processing_duration_seconds_sum[5m]) /
    rate(consumer_inbox_processing_duration_seconds_count[5m]))

# Events by consumer
sum by (consumer_name) (
  rate(consumer_inbox_processed_total[5m])
)
```

## Maintenance

### Cleanup Old Entries

The inbox table grows over time. Clean it up periodically:

```python
# Run as a scheduled job (e.g., daily cron)
async def cleanup_old_inbox_entries():
    deleted = await inbox.cleanup_old_entries(older_than_days=7)
    logger.info(f"Cleaned up {deleted} old inbox entries")

# Or in Kubernetes CronJob
# See k8s/inbox-cleanup-cronjob.yaml
```

Cleanup is safe because:
- Duplicate deliveries unlikely after 7 days
- Only removes successfully processed events
- Can adjust retention based on your needs

### Monitoring Inbox Growth

```sql
-- Check inbox size
SELECT consumer_name, COUNT(*) as event_count
FROM consumer_inbox
GROUP BY consumer_name
ORDER BY event_count DESC;

-- Check oldest entries
SELECT consumer_name, MIN(consumed_at) as oldest_entry
FROM consumer_inbox
GROUP BY consumer_name;
```

## Best Practices

### 1. Include Inbox Check in Transaction

```python
# ✅ CORRECT - Inbox insert in same transaction as business logic
async with db.transaction():
    # Inbox insert happens here (inside transaction)
    result = await inbox.process_idempotent(
        event_id, topic, type, payload, handler
    )

# ❌ WRONG - Separate transactions
is_duplicate = await check_inbox(event_id)  # Transaction 1
if not is_duplicate:
    await process(payload)  # Transaction 2 - Race condition!
```

### 2. Use Stable Event IDs

```python
# ✅ CORRECT - Use producer's event_id
event_id = message.headers['message_id']

# ✅ CORRECT - Use message key
event_id = message.key

# ❌ WRONG - Generate new ID
event_id = str(uuid.uuid4())  # Different on redelivery!
```

### 3. Handle Handler Errors

```python
# Handler exceptions propagate automatically
async def risky_handler(payload):
    if payload['amount'] < 0:
        raise ValueError("Negative amount")
    return await process_payment(payload)

try:
    result = await inbox.process_idempotent(
        event_id, topic, type, payload, risky_handler
    )
except ValueError as e:
    logger.error(f"Invalid payload: {e}")
    # Don't ack message - let it retry with backoff
```

### 4. Multiple Consumers, Same Service

If you have multiple consumer instances:

```python
# ✅ CORRECT - Same consumer_name across instances
# All instances of order-service use "order-service"
inbox = ConsumerInbox(storage, "order-service")

# This ensures deduplication works across all instances:
# - Instance 1 processes event → inserts to inbox
# - Instance 2 receives duplicate → inbox check prevents reprocessing
```

## Integration Examples

### Kafka Consumer

```python
from aiokafka import AIOKafkaConsumer
from sagaz.outbox import ConsumerInbox

consumer = AIOKafkaConsumer(
    'orders',
    bootstrap_servers='localhost:9092',
    group_id='order-service'
)

inbox = ConsumerInbox(storage, "order-service")

async def consume_messages():
    await consumer.start()
    try:
        async for msg in consumer:
            event_id = msg.headers.get('message_id')
            
            result = await inbox.process_idempotent(
                event_id=event_id,
                source_topic=msg.topic,
                event_type="OrderCreated",
                payload=json.loads(msg.value),
                handler=process_order
            )
            
            await consumer.commit()
    finally:
        await consumer.stop()
```

### RabbitMQ Consumer

```python
from aio_pika import connect_robust
from sagaz.outbox import ConsumerInbox

inbox = ConsumerInbox(storage, "order-service")

async def on_message(message):
    async with message.process():
        event_id = message.message_id
        payload = json.loads(message.body)
        
        result = await inbox.process_idempotent(
            event_id=event_id,
            source_topic=message.routing_key,
            event_type="OrderCreated",
            payload=payload,
            handler=process_order
        )

connection = await connect_robust("amqp://localhost/")
channel = await connection.channel()
queue = await channel.declare_queue("orders")
await queue.consume(on_message)
```

## Error Handling

### Duplicate Detection

```python
# First delivery
result = await inbox.process_idempotent(...)
# result = {"order_id": "123"}  (processed)

# Second delivery (duplicate)
result = await inbox.process_idempotent(...)
# result = None  (skipped)
```

### Handler Failures

```python
async def failing_handler(payload):
    raise ValueError("Something went wrong")

# Exception propagates to your code
try:
    await inbox.process_idempotent(..., handler=failing_handler)
except ValueError:
    # Handle error (retry, DLQ, alert, etc.)
    pass
```

### Database Failures

```python
# Database connection lost during processing
try:
    await inbox.process_idempotent(...)
except DatabaseError:
    # Transaction rolled back (including inbox insert)
    # Message not acked → will be redelivered
    # Next delivery will retry from scratch
    pass
```

## Troubleshooting

### High Duplicate Rate

```bash
# Check metrics
curl http://localhost:8000/metrics | grep inbox_duplicates

# Investigate cause:
# 1. Consumer crashes before ack?
# 2. Processing timeout too low?
# 3. Network issues?

# Check consumer logs
kubectl logs -f deployment/order-service | grep "Duplicate message"
```

### Inbox Table Growing Too Fast

```sql
-- Check growth rate
SELECT 
    consumer_name,
    COUNT(*) as total_events,
    COUNT(*) FILTER (WHERE consumed_at > NOW() - INTERVAL '1 day') as last_day,
    COUNT(*) FILTER (WHERE consumed_at > NOW() - INTERVAL '1 hour') as last_hour
FROM consumer_inbox
GROUP BY consumer_name;
```

```python
# Adjust cleanup frequency
# Run cleanup more often or with shorter retention
await inbox.cleanup_old_entries(older_than_days=3)  # Instead of 7
```

### Processing Stuck

```sql
-- Check for events stuck in processing
SELECT event_id, consumer_name, consumed_at, processing_duration_ms
FROM consumer_inbox
WHERE processing_duration_ms IS NULL
  AND consumed_at < NOW() - INTERVAL '5 minutes';
```

## Performance Considerations

### Inbox Check Performance

The inbox check is very fast (<1ms) because:
- Uses primary key lookup (UUID)
- Unique constraint for immediate duplicate detection
- Minimal overhead

### Cleanup Performance

```sql
-- Cleanup with batching to avoid long locks
DELETE FROM consumer_inbox
WHERE consumer_name = 'order-service'
  AND consumed_at < NOW() - INTERVAL '7 days'
LIMIT 10000;  -- Batch delete
```

## Summary

**Key Points:**
- ✅ Exactly-once processing guarantee
- ✅ Automatic duplicate detection
- ✅ Database-backed idempotency
- ✅ Works across consumer instances
- ✅ Minimal performance overhead

**When to Use:**
- ✅ Critical business operations (payments, inventory)
- ✅ Non-idempotent operations
- ✅ Multi-instance consumers

**Best Practices:**
- ✅ Use stable event IDs from producer
- ✅ Clean up old entries regularly
- ✅ Monitor duplicate rates
- ✅ One consumer_name per microservice

**Next Steps:**
- Implement in staging environment
- Monitor duplicate detection rates
- Set up cleanup cron job
- Add alerting for high duplicate rates
