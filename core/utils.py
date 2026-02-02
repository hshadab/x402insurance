"""
Shared utility functions for x402 Insurance Service.
"""
import ipaddress
import logging
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
from urllib.parse import urlparse

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


def validate_merchant_url(url: str) -> str:
    """Validate that a merchant URL is a safe external HTTP(S) URL.

    Raises ValueError if the URL is invalid, uses a non-HTTP scheme,
    or points to a private/loopback/link-local address (SSRF prevention).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid URL scheme: {parsed.scheme!r} (must be http or https)")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")

    # Block obvious private hostnames
    _blocked = {"localhost", "127.0.0.1", "0.0.0.0", "[::1]", "metadata.google.internal"}
    if hostname.lower() in _blocked:
        raise ValueError(f"Blocked hostname: {hostname}")

    # Block private/reserved IP ranges
    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            raise ValueError(f"Blocked private/reserved IP: {hostname}")
    except ValueError:
        # Not an IP literal — that's fine, it's a domain name.
        # Block AWS metadata endpoint patterns
        if hostname.endswith(".internal") or hostname.startswith("169.254."):
            raise ValueError(f"Blocked internal hostname: {hostname}")

    return url


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
