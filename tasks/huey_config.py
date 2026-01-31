"""
Huey task queue configuration.
"""
import os
from huey import RedisHuey

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
HUEY_IMMEDIATE = os.getenv("HUEY_IMMEDIATE", "false").lower() in ("true", "1", "yes")

huey = RedisHuey(
    "x402insurance",
    url=REDIS_URL,
    immediate=HUEY_IMMEDIATE,
)
