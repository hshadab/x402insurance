"""
Async claim processing via Huey task queue.
"""
import logging
from huey import crontab
from tasks.huey_config import huey

logger = logging.getLogger("x402insurance.tasks")


@huey.task(retries=2, retry_delay=10)
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
