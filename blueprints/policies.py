"""
Policies blueprint — POST /insure, GET /policies, POST /renew
"""
import json
import uuid
import hashlib
import logging
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify, g, current_app
from utils import to_micro, iso_utc_now, parse_utc
import extensions as ext
from functools import wraps

policies_bp = Blueprint('policies', __name__)
logger = logging.getLogger("x402insurance")


@policies_bp.route('/insure', methods=['POST'])
@ext.limiter.limit(lambda: current_app.config["RATE_LIMIT_INSURE"])
def insure():
    # Apply rate limit if real limiter
    cfg = ext.config
    data = request.json or {}
    merchant_url = data.get('merchant_url')
    coverage_amount = data.get('coverage_amount')

    if not merchant_url or not coverage_amount:
        return jsonify({"error": "Missing merchant_url or coverage_amount"}), 400
    if coverage_amount <= 0:
        return jsonify({"error": "Coverage amount must be positive"}), 400
    if coverage_amount > ext.MAX_COVERAGE:
        return jsonify({"error": f"Coverage exceeds maximum of {ext.MAX_COVERAGE} USDC"}), 400

    premium = float(Decimal(str(coverage_amount)) * Decimal(str(ext.PREMIUM_PERCENTAGE)))
    premium_units = to_micro(premium)

    payment_header = getattr(g, 'payment_header', None)
    payer_header = getattr(g, 'payer_header', None)

    if not payment_header:
        required = {
            "x402Version": 2,
            "accepts": [{
                "scheme": "exact", "network": cfg.CAIP2_NETWORK,
                "amount": str(premium_units), "asset": ext.USDC_ADDRESS,
                "payTo": ext.BACKEND_ADDRESS, "maxTimeoutSeconds": 60, "extra": {},
                "description": "Insurance premium (1% of requested coverage)"
            }],
            "resource": {"url": "/insure", "method": "POST"}
        }
        headers = {
            "PAYMENT-REQUIRED": json.dumps(required["accepts"][0]),
            "X-Payment-Required": json.dumps(required["accepts"][0]),
        }
        return jsonify(required), 402, headers

    payment_details = ext.payment_verifier.verify_payment(
        payment_header=payment_header, payer_address=payer_header,
        required_amount=premium_units, max_age_seconds=cfg.PAYMENT_MAX_AGE_SECONDS
    )

    if not payment_details.is_valid:
        logger.warning("Payment verification failed for premium=%s units", premium_units)
        required = {
            "error": "Payment verification failed",
            "x402Version": 2,
            "accepts": [{
                "scheme": "exact", "network": cfg.CAIP2_NETWORK,
                "amount": str(premium_units), "asset": ext.USDC_ADDRESS,
                "payTo": ext.BACKEND_ADDRESS, "maxTimeoutSeconds": 60, "extra": {}
            }],
            "resource": {"url": "/insure", "method": "POST"}
        }
        headers = {
            "PAYMENT-REQUIRED": json.dumps(required["accepts"][0]),
            "X-Payment-Required": json.dumps(required["accepts"][0]),
        }
        return jsonify(required), 402, headers

    # Use facilitator-provided payer address (not spoofable X-Payer header)
    agent_address = payment_details.payer

    # Settle payment on-chain via facilitator
    settlement_tx = None
    settlement_status = "pending"
    payment_requirements = {
        "scheme": "exact", "network": cfg.CAIP2_NETWORK,
        "maxAmountRequired": str(premium_units), "asset": ext.USDC_ADDRESS,
        "payTo": ext.BACKEND_ADDRESS, "maxTimeoutSeconds": 60, "extra": {},
    }
    settle_result = ext.payment_verifier.settle_payment(
        payment_header=payment_header,
        payment_requirements=payment_requirements,
    )
    if settle_result and settle_result.get("success") is not False:
        settlement_tx = settle_result.get("transaction")
        settlement_status = "settled"
        logger.info("Premium settled on-chain: tx=%s", settlement_tx)
    else:
        logger.warning("Settlement failed after verification for premium=%s; marking pending", premium_units)

    policy_id = str(uuid.uuid4())
    merchant_url_hash = hashlib.sha256(merchant_url.encode()).hexdigest()

    policy = {
        "policy_id": policy_id, "agent_address": agent_address,
        "merchant_url": merchant_url, "merchant_url_hash": merchant_url_hash,
        "coverage_amount": coverage_amount, "coverage_amount_units": to_micro(coverage_amount),
        "premium": premium, "premium_units": premium_units,
        "status": "active", "created_at": iso_utc_now(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=ext.POLICY_DURATION)).isoformat(),
        "settlement_tx": settlement_tx,
        "settlement_status": settlement_status,
    }

    success = ext.database.create_policy(policy_id, policy)
    if not success:
        logger.error("Failed to save policy: %s", policy_id)
        return jsonify({"error": "Failed to create policy"}), 500

    return jsonify({
        "policy_id": policy_id, "agent_address": policy["agent_address"],
        "coverage_amount": coverage_amount, "premium": premium,
        "status": "active", "expires_at": policy["expires_at"],
        "settlement_tx": settlement_tx,
        "settlement_status": settlement_status,
    }), 201


@policies_bp.route('/policies', methods=['GET'])
def get_policies():
    wallet_address = request.args.get('wallet')
    if not wallet_address:
        return jsonify({"error": "wallet parameter required"}), 400

    wallet_address = wallet_address.lower()
    agent_policies = []
    current_time = datetime.now(timezone.utc)

    all_policies = ext.database.get_policies_by_wallet(wallet_address)
    for policy in all_policies:
        policy_id = policy.get("policy_id", "")
        expires_at = parse_utc(policy["expires_at"]) if policy.get("expires_at") else datetime.now(timezone.utc)
        if policy.get("status") == "active" and expires_at > current_time:
            agent_policies.append({
                "policy_id": policy_id,
                "merchant_url": policy.get("merchant_url"),
                "merchant_url_hash": policy.get("merchant_url_hash"),
                "coverage_amount": policy.get("coverage_amount"),
                "premium": policy.get("premium"),
                "status": policy.get("status"),
                "created_at": policy.get("created_at"),
                "expires_at": policy.get("expires_at")
            })

    return jsonify({
        "wallet_address": wallet_address,
        "active_policies": agent_policies,
        "total_coverage": sum(p["coverage_amount"] for p in agent_policies),
        "claim_endpoint": "/claim", "renew_endpoint": "/renew",
        "note": "Use policy_id from any active policy to file a claim if merchant fails"
    }), 200


@policies_bp.route('/renew', methods=['POST'])
@ext.limiter.limit(lambda: current_app.config["RATE_LIMIT_RENEW"])
def renew_policy():
    cfg = ext.config
    data = request.json
    policy_id = data.get('policy_id')
    extend_hours = data.get('extend_hours', 24)

    if not policy_id:
        return jsonify({"error": "Missing policy_id"}), 400
    if extend_hours < 1 or extend_hours > 168:
        return jsonify({"error": "extend_hours must be between 1 and 168 (7 days)"}), 400

    policy = ext.database.get_policy(policy_id)

    if not policy:
        return jsonify({"error": "Policy not found"}), 404
    if policy['status'] != 'active':
        return jsonify({"error": f"Can only renew active policies (current status: {policy['status']})"}), 400

    expires_at = parse_utc(policy["expires_at"])
    if expires_at < datetime.now(timezone.utc):
        return jsonify({"error": "Cannot renew expired policy. Please purchase a new policy."}), 400

    hours_per_day = 24
    days_extended = extend_hours / hours_per_day
    renewal_fee = policy['coverage_amount'] * ext.PREMIUM_PERCENTAGE * days_extended
    renewal_fee_units = to_micro(renewal_fee)

    payment_header = (
        request.headers.get('PAYMENT-SIGNATURE') or request.headers.get('X-Payment')
    )
    payer_header = request.headers.get('X-Payer')

    if not payment_header or not payer_header:
        required = {
            "x402Version": 2,
            "accepts": [{
                "scheme": "exact", "network": cfg.CAIP2_NETWORK,
                "amount": str(renewal_fee_units), "asset": ext.USDC_ADDRESS,
                "payTo": ext.BACKEND_ADDRESS,
                "description": f"Policy renewal fee for {extend_hours} hours extension",
                "maxTimeoutSeconds": 60, "extra": {}
            }],
            "resource": {"url": "/renew", "method": "POST"},
            "policy_id": policy_id, "extend_hours": extend_hours,
            "renewal_fee": renewal_fee, "renewal_fee_display": f"{renewal_fee} USDC",
            "current_expires_at": policy['expires_at'],
            "new_expires_at": (expires_at + timedelta(hours=extend_hours)).isoformat()
        }
        headers = {
            "PAYMENT-REQUIRED": json.dumps(required["accepts"][0]),
            "X-Payment-Required": json.dumps(required["accepts"][0]),
        }
        return jsonify(required), 402, headers

    payment_details = ext.payment_verifier.verify_payment(
        payment_header=payment_header, payer_address=payer_header,
        required_amount=renewal_fee_units, max_age_seconds=cfg.PAYMENT_MAX_AGE_SECONDS
    )

    if not payment_details.is_valid:
        logger.warning("Payment verification failed for renewal: policy=%s, fee=%s units", policy_id, renewal_fee_units)
        return jsonify({
            "error": "Payment verification failed",
            "expected_amount": str(renewal_fee_units),
            "asset": {"address": ext.USDC_ADDRESS, "decimals": 6, "symbol": "USDC"},
            "pay_to": ext.BACKEND_ADDRESS
        }), 402

    if payment_details.payer.lower() != policy['agent_address'].lower():
        return jsonify({"error": "Only policy owner can renew policy"}), 403

    # Settle renewal payment on-chain via facilitator
    renewal_settlement_tx = None
    renewal_settlement_status = "pending"
    payment_requirements = {
        "scheme": "exact", "network": cfg.CAIP2_NETWORK,
        "maxAmountRequired": str(renewal_fee_units), "asset": ext.USDC_ADDRESS,
        "payTo": ext.BACKEND_ADDRESS, "maxTimeoutSeconds": 60, "extra": {},
    }
    settle_result = ext.payment_verifier.settle_payment(
        payment_header=payment_header,
        payment_requirements=payment_requirements,
    )
    if settle_result and settle_result.get("success") is not False:
        renewal_settlement_tx = settle_result.get("transaction")
        renewal_settlement_status = "settled"
        logger.info("Renewal settled on-chain: tx=%s", renewal_settlement_tx)
    else:
        logger.warning("Renewal settlement failed; marking pending for policy=%s", policy_id)

    old_expires_at = expires_at
    new_expires_at = old_expires_at + timedelta(hours=extend_hours)

    ext.database.update_policy(policy_id, {
        'expires_at': new_expires_at.isoformat(),
        'renewed_at': iso_utc_now(),
        'renewal_count': policy.get('renewal_count', 0) + 1,
        'total_renewal_fees': policy.get('total_renewal_fees', 0.0) + renewal_fee,
    })

    renewal_count = policy.get('renewal_count', 0) + 1
    total_renewal_fees = policy.get('total_renewal_fees', 0.0) + renewal_fee

    logger.info("Policy renewed: %s, extended by %d hours", policy_id, extend_hours)

    return jsonify({
        "policy_id": policy_id,
        "old_expires_at": old_expires_at.isoformat(),
        "new_expires_at": new_expires_at.isoformat(),
        "extension_hours": extend_hours,
        "renewal_fee": renewal_fee,
        "renewal_fee_display": f"{renewal_fee} USDC",
        "renewal_count": renewal_count,
        "total_paid": policy['premium'] + total_renewal_fees,
        "status": "active",
        "message": f"Policy successfully extended by {extend_hours} hours"
    }), 200
