"""
Huey task queue configuration.

For graceful shutdown, run the consumer with:
    huey_consumer tasks.huey_config.huey --shutdown-timeout=30
"""
import os
import signal
import logging
from huey import RedisHuey

logger = logging.getLogger("x402insurance.huey")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
HUEY_IMMEDIATE = os.getenv("HUEY_IMMEDIATE", "false").lower() in ("true", "1", "yes")

huey = RedisHuey(
    "x402insurance",
    url=REDIS_URL,
    immediate=HUEY_IMMEDIATE,
    utc=True,
)

# Graceful shutdown flag
_shutting_down = False


def _handle_shutdown(signum, frame):
    global _shutting_down
    if not _shutting_down:
        _shutting_down = True
        logger.info("Received signal %s, initiating graceful shutdown...", signum)


def is_shutting_down() -> bool:
    return _shutting_down


# Register signal handlers (safe in main thread only)
try:
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)
except (OSError, ValueError):
    # Not in main thread or signals not supported
    pass
