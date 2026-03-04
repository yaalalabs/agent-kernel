# Redis Multimodal Example

This example demonstrates how to use Agent Kernel's `RedisStorageDriver` to store and retrieve multimodal attachments (images, PDFs, etc.) in Redis — preventing session cache bloat.

## Files

| File | Purpose |
|---|---|
| `app.py` | REST API server — the clean example you can run and learn from |
| `redis_test.py` | Automated pytest — runs nightly in CI |
| `config.yaml` | Agent Kernel configuration enabling Redis as multimodal storage |



## Prerequisites

1. **Docker** — the automated test starts a Redis container automatically.
2. **OpenAI API key** set as `OPENAI_API_KEY`.

For running `app.py` manually, you also need a running Redis instance.

## Running the Example

```bash
# Start a local Redis (Docker)
docker run -d -p 6379:6379 redis:alpine

# Install dependencies
./build.sh local

# Run the server
export OPENAI_API_KEY="your-key"
uv run app.py
```

The server starts at `http://localhost:8000`. Send images via the `/api/v1/chat` endpoint.

## Running the Automated Test

The test automatically starts and stops its own Redis Docker container — no manual setup needed.

```bash
export OPENAI_API_KEY="your-key"
uv run pytest -s
```

The test will:
1. Pull and start a `redis:alpine` container on port `6399`
2. Start the API server pointing at that Redis
3. Send an image and verify the agent describes it correctly
4. Send a follow-up with **no image** — verifying Redis retrieval works
5. Stop the server and Docker container automatically

## Config options (`config.yaml`)

```yaml
multimodal:
  enabled: true
  storage_type: redis
  redis:
    url: "redis://localhost:6379"   # overridden in tests via AK_MULTIMODAL__REDIS__URL
    prefix: "ak:attachments:"       # all Redis keys are prefixed with this
```

The `url` can be overridden at runtime via the environment variable:
```bash
export AK_MULTIMODAL__REDIS__URL="redis://your-redis-host:6379"
# or for SSL (e.g. AWS ElastiCache):
export AK_MULTIMODAL__REDIS__URL="rediss://your-elasticache-host:6379"
```
