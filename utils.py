"""
Shared utility functions for x402 Insurance Service.
"""
import logging
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone

logger = logging.getLogger("x402insurance")

# Monetary helpers (USDC 6 decimals)
MICRO = Decimal(10) ** 6


def to_micro(amount_usdc) -> int:
    """Convert USDC amount to micro-units (6 decimals)."""
    d = Decimal(str(amount_usdc))
    return int((d * MICRO).to_integral_exact(rounding=ROUND_DOWN))


def from_micro(amount_units: int) -> float:
    """Convert micro-units back to USDC float."""
    return float(Decimal(amount_units) / MICRO)


def iso_utc_now() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def parse_utc(dt_str: str) -> datetime:
    """Parse an ISO 8601 datetime string, assuming UTC if no timezone."""
    s = dt_str.replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, AttributeError):
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
