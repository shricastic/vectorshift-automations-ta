import os
import redis.asyncio as redis

# Get the Redis host from environment variables, default to 'localhost'
redis_host = os.environ.get('REDIS_HOST', 'localhost')

# Create an instance of the Redis client using the correct URL format
redis_client = redis.from_url(f"redis://{redis_host}:6379/0")

async def add_key_value_redis(key, value, expire=None):
    async with redis_client as client:
        await client.set(key, value)
        if expire:
            await client.expire(key, expire)

async def get_value_redis(key):
    async with redis_client as client:
        return await client.get(key)

async def delete_key_redis(key):
    async with redis_client as client:
        await client.delete(key)

