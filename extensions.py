"""
Module-level holders for shared service instances.
Avoids circular imports between app.py, blueprints, and tasks.
"""
from prometheus_client import Counter


class _NoOpLimiter:
    """No-op rate limiter used before create_app initializes the real one."""
    def limit(self, *args, **kwargs):
        def decorator(f):
            return f
        return decorator


# Service instances (populated by create_app)
proof_client = None
blockchain = None
database = None
payment_verifier = None
eip712_verifier = None
reserve_monitor = None
limiter = _NoOpLimiter()

# Config constants (populated by create_app)
PREMIUM_PERCENTAGE = None
MAX_COVERAGE = None
POLICY_DURATION = None
USDC_ADDRESS = None
BACKEND_ADDRESS = None
DATA_DIR = None
POLICIES_FILE = None
CLAIMS_FILE = None

# Prometheus metrics
policies_created_total = Counter("policies_created_total", "Total policies created")
claims_paid_total = Counter("claims_paid_total", "Total claims processed", ["status"])

# Reference to the loaded config object
config = None
