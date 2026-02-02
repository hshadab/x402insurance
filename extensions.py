"""
Module-level holders for shared service instances.
Avoids circular imports between app.py, blueprints, and tasks.
"""
from prometheus_client import Counter, Histogram, Gauge


# Service instances (populated by create_app)
proof_client = None
blockchain = None
database = None
payment_verifier = None
eip712_verifier = None
reserve_monitor = None
limiter = None

# Config constants (populated by create_app)
BACKEND_ADDRESS = None
DATA_DIR = None
POLICIES_FILE = None
CLAIMS_FILE = None

# Prometheus metrics
policies_created_total = Counter("policies_created_total", "Total policies created")
claims_paid_total = Counter("claims_paid_total", "Total claims processed", ["status"])
claims_failed_total = Counter("claims_failed_total", "Total claims that failed")
claims_processing_total = Counter("claims_processing_total", "Total claims submitted for processing")
refunds_total = Counter("refunds_total", "Total refunds issued")
refunds_failed_total = Counter("refunds_failed_total", "Total refunds that failed")

claim_processing_duration_seconds = Histogram(
    "claim_processing_duration_seconds",
    "Time to process a claim end-to-end",
    buckets=[1, 5, 10, 20, 30, 60, 120, 300],
)
refund_duration_seconds = Histogram(
    "refund_duration_seconds",
    "Time to issue a refund on-chain",
    buckets=[1, 2, 5, 10, 30, 60, 120],
)

reserve_ratio = Gauge("reserve_ratio", "Current reserve ratio (USDC balance / total coverage)")

# Reference to the loaded config object
config = None
