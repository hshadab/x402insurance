"""
Verify blueprint — POST /verify
"""
import logging
from flask import Blueprint, request, jsonify, Response
import extensions as ext


verify_bp = Blueprint('verify', __name__)
logger = logging.getLogger("x402insurance")


@verify_bp.route('/verify', methods=['POST'])
@ext.limiter.limit("30/hour")
def verify() -> tuple[Response, int] | Response:
    data = request.json
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    proof = data.get('proof')
    public_inputs = data.get('public_inputs')
    claim_id = data.get('claim_id')

    proof_data = data.get('proof_data')
    instance_data = data.get('instance_data')

    if claim_id and (not proof or not public_inputs):
        claim = ext.database.get_claim(claim_id)
        if not claim:
            return jsonify({"error": "Claim not found"}), 404
        proof = proof or claim.get('proof')
        public_inputs = public_inputs or claim.get('public_inputs')
        proof_data = proof_data or claim.get('proof_data')
        instance_data = instance_data or claim.get('instance_data')

    if not proof or not public_inputs:
        return jsonify({"error": "Missing proof or public_inputs (or provide claim_id)"}), 400

    try:
        is_valid = ext.proof_client.verify_proof(proof, public_inputs, proof_data=proof_data, instance_data=instance_data)
        failure_detected = public_inputs[0] == 1 if len(public_inputs) > 0 else False
        payout_amount = public_inputs[3] if len(public_inputs) > 3 else 0
        http_status = public_inputs[1] if len(public_inputs) > 1 else None
        body_length = public_inputs[2] if len(public_inputs) > 2 else None

        return jsonify({
            "valid": is_valid, "public_inputs": public_inputs,
            "failure_detected": failure_detected, "payout_amount": payout_amount,
            "http_status": http_status, "body_length": body_length,
        })
    except Exception as e:
        logger.exception("Proof verification error: %s", e)
        return jsonify({"error": "Proof verification failed"}), 500
