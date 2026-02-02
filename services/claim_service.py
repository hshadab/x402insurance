"""
Claim processing logic shared between synchronous and async paths.
"""
import time
import logging
from core.utils import to_micro, iso_utc_now
import extensions as ext

logger = logging.getLogger("x402insurance.claim_service")


def process_claim(claim_id: str) -> None:
    """
    Process a claim: generate proof, verify it, issue refund, persist result.

    This is the single source of truth for claim processing logic,
    used by both the synchronous /claim endpoint and the async Huey task.

    Raises on unexpected errors; updates claim status in the database
    for all known failure modes.
    """
    start_time = time.monotonic()
    ext.claims_processing_total.inc()

    claim = ext.database.get_claim(claim_id)
    if not claim:
        logger.error("Claim not found: %s", claim_id)
        return

    policy = ext.database.get_policy(claim['policy_id'])
    if not policy:
        logger.error("Policy not found for claim: %s", claim_id)
        ext.database.update_claim(claim_id, {
            'status': 'failed',
            'error': 'Policy not found',
            'failed_at': iso_utc_now(),
        })
        return

    http_response = claim.get('http_response', {})
    coverage_units = claim.get('coverage_amount_units') or to_micro(claim.get('coverage_amount'))

    # Phase 1: Generate SNARK proof
    logger.info("Generating proof for claim: %s", claim_id)
    try:
        proof_hex, public_inputs, gen_time_ms = ext.proof_client.generate_proof(
            http_status=http_response["status"],
            http_body=http_response["body"],
            http_headers=http_response.get("headers", {}),
            coverage_amount_units=coverage_units,
        )
    except Exception as e:
        logger.error("Proof generation failed for claim %s: %s", claim_id, e)
        ext.claims_failed_total.inc()
        ext.database.update_claim(claim_id, {
            'status': 'failed',
            'error': f'Proof generation failed: {e}',
            'failed_at': iso_utc_now(),
        })
        return

    # Phase 2: Verify proof
    is_valid = ext.proof_client.verify_proof(proof_hex, public_inputs)
    if not is_valid:
        logger.error("Proof verification failed for claim: %s", claim_id)
        ext.database.update_claim(claim_id, {
            'status': 'failed',
            'error': 'Generated proof is invalid',
            'failed_at': iso_utc_now(),
        })
        return

    is_failure = public_inputs[0]
    if is_failure != 1:
        logger.warning("No failure detected for claim: %s", claim_id)
        ext.database.update_claim(claim_id, {
            'status': 'failed',
            'error': 'No failure detected in HTTP response',
            'failed_at': iso_utc_now(),
        })
        return

    # Phase 3: Persist proof data BEFORE issuing refund (crash-safe ordering)
    ext.database.update_claim(claim_id, {
        'proof': proof_hex,
        'public_inputs': public_inputs,
        'proof_generation_time_ms': gen_time_ms,
        'verification_result': True,
        'payout_amount': claim.get('coverage_amount'),
        'payout_amount_units': claim['coverage_amount_units'],
        'recipient_address': claim['agent_address'],
        'status': 'approved',
    })

    # Phase 4: Issue refund
    logger.info("Issuing refund for claim: %s", claim_id)
    refund_start = time.monotonic()
    try:
        refund_tx_hash = ext.blockchain.issue_refund(
            to_address=claim['agent_address'],
            amount=claim['coverage_amount_units']
        )
        ext.refund_duration_seconds.observe(time.monotonic() - refund_start)
        ext.refunds_total.inc()
    except Exception as refund_err:
        ext.refund_duration_seconds.observe(time.monotonic() - refund_start)
        ext.refunds_failed_total.inc()
        logger.error("Refund failed for claim %s: %s", claim_id, refund_err)
        ext.database.update_claim(claim_id, {
            'status': 'refund_failed',
            'error': str(refund_err),
            'failed_at': iso_utc_now(),
        })
        _deliver_webhook(claim_id, "refund_failed", error=str(refund_err))
        return

    # Phase 5: Mark as paid
    ext.database.update_claim(claim_id, {
        'refund_tx_hash': refund_tx_hash,
        'status': 'paid',
        'paid_at': iso_utc_now(),
    })

    ext.database.update_policy(claim['policy_id'], {'status': 'claimed'})
    ext.claim_processing_duration_seconds.observe(time.monotonic() - start_time)
    logger.info("Claim processed successfully: %s, refund TX: %s", claim_id, refund_tx_hash)

    # Deliver webhook notification
    _deliver_webhook(claim_id, "paid", refund_tx_hash=refund_tx_hash)


def _deliver_webhook(claim_id: str, status: str, **extra) -> None:
    """POST claim status to the webhook_url if configured."""
    cfg = ext.config
    if not cfg or not getattr(cfg, 'WEBHOOK_ENABLED', False):
        return

    claim = ext.database.get_claim(claim_id)
    if not claim:
        return

    webhook_url = claim.get('webhook_url')
    if not webhook_url:
        return

    import httpx
    payload = {
        "claim_id": claim_id,
        "policy_id": claim.get('policy_id'),
        "status": status,
        **extra,
    }
    try:
        httpx.post(webhook_url, json=payload, timeout=cfg.WEBHOOK_TIMEOUT)
        logger.info("Webhook delivered for claim %s to %s", claim_id, webhook_url)
    except Exception as e:
        logger.warning("Webhook delivery failed for claim %s: %s", claim_id, e)
