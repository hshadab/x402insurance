"""
Claims blueprint — POST /claim, GET /claims/<claim_id>, GET /proofs/<claim_id>
"""
import json
import uuid
import hashlib
import logging
import httpx
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g, current_app
from utils import to_micro, iso_utc_now, parse_utc, validate_merchant_url
import extensions as ext

claims_bp = Blueprint('claims', __name__)
logger = logging.getLogger("x402insurance")


def process_claim_async(claim_id: str):
    """Background worker function to process claim asynchronously."""
    from services.claim_service import process_claim
    try:
        process_claim(claim_id)
    except Exception as e:
        logger.error("Error processing claim async: %s, error: %s", claim_id, str(e), exc_info=True)
        try:
            ext.database.update_claim(claim_id, {
                'status': 'failed',
                'error': str(e),
                'failed_at': iso_utc_now(),
            })
        except Exception as save_error:
            logger.error("Failed to save error status: %s", str(save_error))


@claims_bp.route('/claim', methods=['POST'])
@ext.limiter.limit(lambda: current_app.config["RATE_LIMIT_CLAIM"])
def claim():
    cfg = ext.config
    data = request.json
    policy_id = data.get('policy_id')
    http_response = data.get('http_response')

    if not policy_id or not http_response:
        return jsonify({"error": "Missing policy_id or http_response"}), 400

    # Input validation
    http_status = http_response.get("status")
    if not isinstance(http_status, int) or http_status < 100 or http_status > 599:
        return jsonify({"error": "http_response.status must be an integer between 100 and 599"}), 400

    body = http_response.get("body", "")
    if isinstance(body, str) and len(body) > 500 * 1024:
        return jsonify({"error": "http_response.body exceeds 500KB limit"}), 400

    headers = http_response.get("headers")
    if headers is not None and not isinstance(headers, dict):
        return jsonify({"error": "http_response.headers must be a dict"}), 400

    # merchant_url is required for server-side verification
    merchant_url = data.get('merchant_url')
    if not merchant_url:
        return jsonify({"error": "Missing merchant_url (required for server-side verification)"}), 400
    try:
        validate_merchant_url(merchant_url)
    except ValueError as e:
        return jsonify({"error": f"Invalid merchant_url: {e}"}), 400

    # Server-side re-fetch for fraud detection
    server_verified = False
    server_http_status = None
    try:
        server_resp = httpx.get(merchant_url, timeout=10.0, follow_redirects=True)
        server_http_status = server_resp.status_code
        agent_claims_failure = http_status >= 500
        server_sees_success = 200 <= server_http_status < 300

        if agent_claims_failure and server_sees_success:
            return jsonify({
                "error": "Server-side verification failed: merchant responded successfully "
                         "but agent reported failure",
                "error_code": "fraud_suspected",
                "server_http_status": server_http_status,
                "agent_http_status": http_status,
            }), 403

        if server_http_status >= 500:
            server_verified = True
        else:
            # Server did not see a 5xx — verification inconclusive
            server_verified = False
    except (httpx.RequestError, httpx.TimeoutException) as fetch_err:
        logger.warning("Server-side re-fetch failed for %s: %s", merchant_url, fetch_err)
        server_verified = False

    # Idempotency check
    idempotency_key = request.headers.get('Idempotency-Key')
    if idempotency_key:
        existing_claim = ext.database.get_claim_by_idempotency_key(idempotency_key)
        if existing_claim:
            cid = existing_claim.get("claim_id")
            return jsonify({
                "claim_id": cid,
                "policy_id": existing_claim["policy_id"],
                "proof": existing_claim.get("proof"),
                "public_inputs": existing_claim.get("public_inputs"),
                "payout_amount": existing_claim.get("payout_amount"),
                "refund_tx_hash": existing_claim.get("refund_tx_hash"),
                "status": existing_claim["status"],
                "proof_url": f"/proofs/{cid}",
                "idempotent": True,
                "note": "This claim was already processed (idempotent response)"
            }), 200

    # Authenticate payment BEFORE locking the policy to avoid needless lock/unlock
    agent_address = None
    if cfg.REQUIRE_CLAIM_AUTHENTICATION:
        payment_header = getattr(g, 'payment_header', None)
        payer_header = getattr(g, 'payer_header', None)
        claim_fee_units = 100  # anti-spam fee

        if not payment_header:
            required = {
                "x402Version": 2,
                "accepts": [{
                    "scheme": "exact", "network": cfg.CAIP2_NETWORK,
                    "amount": str(claim_fee_units), "asset": current_app.config["USDC_CONTRACT_ADDRESS"],
                    "payTo": ext.BACKEND_ADDRESS, "maxTimeoutSeconds": 60, "extra": {},
                    "description": "Claim submission fee (anti-spam)"
                }],
                "resource": {"url": "/claim", "method": "POST"}
            }
            headers_out = {
                "PAYMENT-REQUIRED": json.dumps(required["accepts"][0]),
                "X-Payment-Required": json.dumps(required["accepts"][0]),
            }
            return jsonify(required), 402, headers_out

        payment_details = ext.payment_verifier.verify_payment(
            payment_header=payment_header, payer_address=payer_header,
            required_amount=claim_fee_units, max_age_seconds=cfg.PAYMENT_MAX_AGE_SECONDS
        )
        if not payment_details.is_valid:
            logger.warning("Claim payment verification failed for policy_id=%s", policy_id)
            return jsonify({"error": "Payment verification failed"}), 402

        agent_address = payment_details.payer

        # Verify ownership before locking the policy
        raw_policy = ext.database.get_policy(policy_id)
        if not raw_policy:
            return jsonify({"error": "Policy not found"}), 404
        if agent_address.lower() != raw_policy["agent_address"].lower():
            return jsonify({
                "error": "Unauthorized: You can only claim your own policies",
                "policy_owner": raw_policy["agent_address"],
                "claim_submitter": agent_address
            }), 403

    # Atomic claim — lock the policy now that auth is verified
    policy = ext.database.claim_policy(policy_id)
    if policy is None:
        raw_policy = ext.database.get_policy(policy_id)
        if not raw_policy:
            return jsonify({"error": "Policy not found"}), 404
        if raw_policy.get("status") != "active":
            return jsonify({"error": f"Policy is not active: {raw_policy['status']}"}), 409
        if parse_utc(raw_policy.get("expires_at", "")) < datetime.now(timezone.utc):
            return jsonify({"error": "Policy expired"}), 400
        return jsonify({"error": "Policy cannot be claimed"}), 409

    # Async mode
    async_mode = request.args.get('async', 'false').lower() in ('true', '1', 'yes')

    if async_mode:
        claim_id = str(uuid.uuid4())
        http_body_hash = hashlib.sha256(http_response["body"].encode()).hexdigest()

        claim_record = {
            "claim_id": claim_id, "policy_id": policy_id,
            "status": "processing", "http_response": http_response,
            "http_status": http_response["status"],
            "http_body_hash": http_body_hash,
            "http_headers": http_response.get("headers", {}),
            "agent_address": policy["agent_address"],
            "coverage_amount": policy.get("coverage_amount"),
            "coverage_amount_units": policy.get("coverage_amount_units") or to_micro(policy.get("coverage_amount")),
            "created_at": iso_utc_now(),
            "idempotency_key": idempotency_key,
            "proof": None,
            "public_inputs": None,
            "server_verified": server_verified,
            "server_http_status": server_http_status,
            "merchant_url": merchant_url,
        }

        ext.database.create_claim(claim_id, claim_record)

        # Use huey task if available, otherwise fall back to threading
        try:
            from tasks.claim_processor import process_claim_task
            process_claim_task(claim_id)
        except ImportError:
            import threading
            from flask import current_app
            app = current_app._get_current_object()
            def _run(app_ref, cid):
                with app_ref.app_context():
                    process_claim_async(cid)
            thread = threading.Thread(target=_run, args=(app, claim_id), daemon=True)
            thread.start()

        logger.info("Claim submitted for async processing: %s", claim_id)

        return jsonify({
            "claim_id": claim_id, "policy_id": policy_id,
            "status": "processing", "estimated_completion_seconds": 20,
            "poll_url": f"/claims/{claim_id}",
            "message": "Claim is being processed in the background. Poll /claims/{claim_id} for status.",
            "async_mode": True
        }), 202

    # Synchronous mode
    payout_amount = policy.get("coverage_amount")
    payout_amount_units = policy.get("coverage_amount_units") or to_micro(payout_amount)
    try:
        proof_hex, public_inputs, gen_time_ms = ext.proof_client.generate_proof(
            http_status=http_response["status"],
            http_body=http_response["body"],
            http_headers=http_response.get("headers", {}),
            coverage_amount_units=payout_amount_units,
        )
    except Exception as e:
        ext.database.update_policy(policy_id, {'status': 'active'})
        return jsonify({"error": f"Proof generation failed: {str(e)}"}), 500

    try:
        is_valid = ext.proof_client.verify_proof(proof_hex, public_inputs)
    except Exception as e:
        ext.database.update_policy(policy_id, {'status': 'active'})
        return jsonify({"error": f"Proof verification failed: {str(e)}"}), 500

    if not is_valid:
        ext.database.update_policy(policy_id, {'status': 'active'})
        return jsonify({"error": "Generated proof is invalid (internal error)"}), 500

    is_failure = public_inputs[0]
    if is_failure != 1:
        ext.database.update_policy(policy_id, {'status': 'active'})
        return jsonify({"error": "No failure detected in HTTP response"}), 400

    claim_id = str(uuid.uuid4())

    # Phase 3: Issue refund BEFORE persisting claim
    try:
        refund_tx_hash = ext.blockchain.issue_refund(
            to_address=policy["agent_address"], amount=payout_amount_units
        )
    except Exception as e:
        # Refund failed — persist claim with refund_failed status so it can be retried
        http_body_hash = hashlib.sha256(http_response["body"].encode()).hexdigest()
        claim_record = {
            "claim_id": claim_id, "policy_id": policy_id,
            "proof": proof_hex, "public_inputs": public_inputs,
            "proof_generation_time_ms": gen_time_ms,
            "verification_result": True,
            "http_status": http_response["status"],
            "http_body_hash": http_body_hash,
            "http_headers": http_response.get("headers", {}),
            "payout_amount": payout_amount, "payout_amount_units": payout_amount_units,
            "refund_tx_hash": None,
            "recipient_address": policy["agent_address"],
            "status": "refund_failed", "created_at": iso_utc_now(),
            "paid_at": None,
            "idempotency_key": idempotency_key,
            "error": str(e),
            "server_verified": server_verified,
            "server_http_status": server_http_status,
            "merchant_url": merchant_url,
        }
        ext.database.create_claim(claim_id, claim_record)
        return jsonify({"error": f"Refund failed: {str(e)}", "claim_id": claim_id, "status": "refund_failed"}), 500

    # Refund succeeded — now persist
    http_body_hash = hashlib.sha256(http_response["body"].encode()).hexdigest()

    claim_record = {
        "claim_id": claim_id, "policy_id": policy_id,
        "proof": proof_hex, "public_inputs": public_inputs,
        "proof_generation_time_ms": gen_time_ms,
        "verification_result": True,
        "http_status": http_response["status"],
        "http_body_hash": http_body_hash,
        "http_headers": http_response.get("headers", {}),
        "payout_amount": payout_amount, "payout_amount_units": payout_amount_units,
        "refund_tx_hash": refund_tx_hash,
        "recipient_address": policy["agent_address"],
        "status": "paid", "created_at": iso_utc_now(), "paid_at": iso_utc_now(),
        "idempotency_key": idempotency_key,
        "server_verified": server_verified,
        "server_http_status": server_http_status,
        "merchant_url": merchant_url,
    }

    ext.database.create_claim(claim_id, claim_record)

    return jsonify({
        "claim_id": claim_id, "policy_id": policy_id,
        "proof": proof_hex, "public_inputs": public_inputs,
        "payout_amount": payout_amount,
        "refund_tx_hash": refund_tx_hash,
        "status": "paid", "proof_url": f"/proofs/{claim_id}"
    }), 201


@claims_bp.route('/claims/<claim_id>', methods=['GET'])
def get_claim_status(claim_id):
    claim = ext.database.get_claim(claim_id)
    if not claim:
        return jsonify({"error": "Claim not found"}), 404

    return jsonify({
        "claim_id": claim.get("claim_id", claim_id), "policy_id": claim["policy_id"],
        "status": claim.get("status", "unknown"),
        "payout_amount": claim.get("payout_amount"),
        "refund_tx_hash": claim.get("refund_tx_hash"),
        "proof_url": f"/proofs/{claim_id}",
        "created_at": claim.get("created_at"),
        "paid_at": claim.get("paid_at"),
        "proof_generation_time_ms": claim.get("proof_generation_time_ms")
    }), 200


@claims_bp.route('/proofs/<claim_id>', methods=['GET'])
def get_proof(claim_id):
    claim = ext.database.get_claim(claim_id)
    if not claim:
        return jsonify({"error": "Claim not found"}), 404
    return jsonify(claim)
