"""
Async claim processing via Huey task queue.
"""
import logging
from huey import crontab
from tasks.huey_config import huey

logger = logging.getLogger("x402insurance.tasks")


import os

_claim_task_timeout = int(os.getenv("CLAIM_TASK_TIMEOUT", 300))


@huey.task(retries=2, retry_delay=10, default_timeout=_claim_task_timeout)
def process_claim_task(claim_id: str):
    """
    Process a claim asynchronously via Huey.
    Delegates to the claim processing logic in blueprints.claims.
    On final retry failure, marks claim as failed.
    """
    try:
        from blueprints.claims import process_claim_async
        process_claim_async(claim_id)
    except Exception as e:
        logger.error("Claim task failed for %s: %s", claim_id, e, exc_info=True)
        # Mark claim as failed on final retry
        try:
            import extensions as ext
            from core.utils import iso_utc_now
            claim = ext.database.get_claim(claim_id) if ext.database else None
            if claim and claim.get('status') == 'processing':
                ext.database.update_claim(claim_id, {
                    'status': 'failed',
                    'error': f'Task failed after retries: {str(e)}',
                    'failed_at': iso_utc_now(),
                })
        except Exception as save_err:
            logger.error("Failed to mark claim %s as failed: %s", claim_id, save_err)
        raise


@huey.periodic_task(crontab(minute='0'))
def cleanup_expired_policies():
    """Hourly cleanup of expired policies."""
    try:
        import extensions as ext
        if ext.database:
            count = ext.database.cleanup_expired_policies()
            if count > 0:
                logger.info("Cleaned up %d expired policies", count)
    except Exception as e:
        logger.error("Failed to cleanup expired policies: %s", e)


@huey.periodic_task(crontab(minute='*/5'))
def recover_stuck_claims():
    """Mark claims stuck in 'processing' for more than CLAIM_TASK_TIMEOUT as failed."""
    try:
        import extensions as ext
        from core.utils import iso_utc_now, parse_utc
        from datetime import datetime, timezone, timedelta
        if ext.database:
            timeout_seconds = int(os.getenv("CLAIM_TASK_TIMEOUT", 300))
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
            all_claims = ext.database.get_all_claims()
            recovered = 0
            for cid, claim in all_claims.items():
                if claim.get('status') != 'processing':
                    continue
                created_at = parse_utc(claim.get('created_at', ''))
                if created_at < cutoff:
                    ext.database.update_claim(cid, {
                        'status': 'failed',
                        'error': f'Claim processing timed out after {timeout_seconds}s',
                        'failed_at': iso_utc_now(),
                    })
                    # Unlock the policy
                    policy_id = claim.get('policy_id')
                    if policy_id:
                        ext.database.update_policy(policy_id, {'status': 'active'})
                    recovered += 1
            if recovered > 0:
                logger.info("Recovered %d stuck claims", recovered)
    except Exception as e:
        logger.error("Failed to recover stuck claims: %s", e)


@huey.periodic_task(crontab(minute='30'))
def cleanup_expired_nonces():
    """Periodic cleanup of expired nonces."""
    try:
        import extensions as ext
        if ext.database:
            count = ext.database.cleanup_nonces(max_age_seconds=3600)
            if count > 0:
                logger.info("Cleaned up %d expired nonces", count)
    except Exception as e:
        logger.error("Failed to cleanup expired nonces: %s", e)
