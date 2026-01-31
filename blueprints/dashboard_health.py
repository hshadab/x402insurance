"""
Lightweight health blueprint for the read-only dashboard.

Only reports dashboard-level health (server up, responding).
No blockchain, database, prover, or wallet checks.
"""
import os
import time
from flask import Blueprint, jsonify, request
from utils import iso_utc_now

dashboard_health_bp = Blueprint('dashboard_health', __name__)


@dashboard_health_bp.route('/ping')
def ping():
    return jsonify({"status": "Healthy", "time_of_last_update": int(time.time())}), 200


@dashboard_health_bp.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": iso_utc_now(),
        "version": os.getenv("SENTRY_RELEASE", "dev"),
        "environment": os.getenv("ENV", "unknown"),
        "mode": "dashboard-readonly",
        "checks": {
            "dashboard": {"status": "operational"},
        }
    }), 200


@dashboard_health_bp.route('/metrics')
def metrics():
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}
