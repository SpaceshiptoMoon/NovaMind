# Redis Caching System

This document describes the Redis caching implementation for the intelligent backend system, including Knowledge Space caching and session management.

## Overview

The Redis caching system provides two main functionalities:
1. **Knowledge Space Caching** - Caching search results to avoid duplicate retrieval/generation
2. **Session Management** - Storing conversation history and state using Hash + List structure

## Configuration

Add the following to your `.env` file:

```ini
# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

# Cache Settings
SESSION_CACHE_ENABLED=true
SESSION_CACHE_EXPIRE_HOURS=24
VECTOR_SEARCH_ENABLED=false
```

## Knowledge Space Caching

### Key Features

1. **Query-based Exact Caching**
   - Caches results for exact query matches
   - Key format: `ks_cache:{space_id}:{user_id}:{query_hash}`

2. **Embedding-based Similar Caching**
   - Uses vector similarity to find similar queries
   - Requires Redis Stack with RediSearch
   - Similarity threshold configurable

3. **Embedding Caching**
   - Caches query embeddings to avoid recomputation
   - Key format: `embedding:{query_hash}`

## Session Management

### Data Structure

- **Session Info (Hash)**: `session:{session_id}`
  - `user_id`: User identifier
  - `created_at`: Creation timestamp
  - `last_active`: Last activity timestamp
  - `message_count`: Number of messages

- **Messages (List)**: `session:{session_id}:messages`
  - Ordered list of messages (newest first)
  - Each message is a JSON object with `role`, `content`, and `timestamp`

### Usage Example

```python
from src.shared.cache.redis_client import get_redis_client

redis_client = await get_redis_client()

# Create a new session
await redis_client.create_session(
    session_id="session_123",
    user_id="user123",
    expire_hours=24
)

# Add message to session
message = {
    "role": "user",
    "content": "你好，我想了解Python",
    "timestamp": "2024-01-01T12:00:00"
}
await redis_client.add_message_to_session(
    session_id="session_123",
    message=message
)

# Get all messages (from oldest to newest)
messages = await redis_client.get_session_messages("session_123")

# Get session info
session_info = await redis_client.get_session_info("session_123")

# Update session activity
await redis_client.update_session_activity("session_123")

# Delete a specific message
await redis_client.delete_message_from_session("session_123", 0)

# Delete entire session
await redis_client.delete_session("session_123")

# Get all sessions for a user
user_sessions = await redis_client.get_user_sessions("user123")
```

## Integration with Services

### QA Service

The QA service supports Redis caching for session management:

```python
# Add message with caching
message = await qa_service.add_message(
    request=QARequest(
        content="Hello",
        role="user",
        session_id="session_123"
    ),
    user_id=123,
    use_redis_cache=True
)

# Get messages with caching
messages = await qa_service.get_session_messages(
    session_id="session_123",
    user_id=123,
    use_redis_cache=True
)
```

## Redis Stack for Vector Search

To enable vector similarity search, you need Redis Stack with RediSearch:

1. **Install Redis Stack**
   ```bash
   # Ubuntu/Debian
   wget https://packages.redis.io/redis-stack/latest/redis-stack-server-linux-x64-v7.2.0.tar.gz
   tar -xvzf redis-stack-server-linux-x64-v7.2.0.tar.gz
   ./redis-stack-server/redis-stack-server

   # Docker
   docker run -p 6379:6379 redis/redis-stack-server:latest
   ```

2. **Enable Vector Search in Configuration**
   ```ini
   VECTOR_SEARCH_ENABLED=true
   ```

3. **Vector Search Operations**
   ```python
   # Create and search vector index
   similar_queries = await redis_client.find_similar_queries(
       query_vector,
       threshold=0.95,
       limit=5
   )
   ```

## Performance Considerations

1. **Cache TTL Settings**
   - Knowledge Space results: configurable
   - Session data: 24 hours (configurable)
   - Embeddings: 24 hours (configurable)

2. **Memory Usage**
   - Monitor Redis memory usage
   - Adjust TTL based on your needs
   - Consider using Redis persistence for important data

3. **Error Handling**
   - The system gracefully handles Redis connection failures
   - Falls back to direct service calls when Redis is unavailable
   - Logs cache operations for debugging

## Monitoring

Enable logging to monitor cache performance:

```python
import logging
logging.getLogger("src.shared.cache.redis_client").setLevel(logging.INFO)
```

Key metrics to monitor:
- Cache hit/miss ratios
- Redis connection latency
- Memory usage patterns
- Error rates
