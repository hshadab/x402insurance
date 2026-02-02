"""
Reserve Monitoring and Alerts

Monitors USDC reserves to ensure sufficient funds to pay claims.
"""
import os
import logging
import httpx
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger("x402insurance.reserve_monitor")


class ReserveMonitor:
    """Monitor insurance reserves and alert on low balance"""

    def __init__(self, blockchain_client, database_client, min_reserve_ratio: float = 1.5):
        """
        Initialize reserve monitor

        Args:
            blockchain_client: Blockchain client instance
            database_client: Database client instance
            min_reserve_ratio: Minimum ratio of reserves to liabilities (default 1.5 = 150%)
        """
        self.blockchain = blockchain_client
        self.database = database_client
        self.min_reserve_ratio = min_reserve_ratio
        self.last_alert_time = None

    def check_reserve_health(self) -> Dict:
        """
        Check reserve health and return status

        Returns:
            Dict with reserve health metrics
        """
        try:
            # Get current USDC balance
            usdc_balance = self.blockchain.get_balance()
            usdc_balance_float = usdc_balance / 1_000_000  # Convert to USDC

            # Calculate total potential liability from active policies
            policies = self.database.get_all_policies()
            total_liability_units = sum(
                p.get('coverage_amount_units', 0)
                for p in policies.values()
                if p.get('status') == 'active'
            )
            total_liability = total_liability_units / 1_000_000

            # Calculate reserve ratio
            if total_liability > 0:
                reserve_ratio = usdc_balance / total_liability_units
            else:
                reserve_ratio = float('inf')

            # Determine status
            if reserve_ratio < 1.0:
                status = "critical"
                message = "Reserves below liabilities - cannot pay all claims!"
            elif reserve_ratio < self.min_reserve_ratio:
                status = "warning"
                message = f"Reserves below minimum ratio ({self.min_reserve_ratio}x)"
            else:
                status = "healthy"
                message = "Reserves sufficient"

            # Opportunistically recover stuck policies during health checks
            try:
                recovered = self.database.recover_stuck_policies(max_age_seconds=600)
                if recovered > 0:
                    logger.info("Recovered %d stuck policies during reserve check", recovered)
            except Exception as recover_err:
                logger.warning("Policy recovery failed: %s", recover_err)

            result = {
                "status": status,
                "message": message,
                "reserves_usdc": usdc_balance_float,
                "reserves_units": usdc_balance,
                "liability_usdc": total_liability,
                "liability_units": total_liability_units,
                "ratio": reserve_ratio if reserve_ratio != float('inf') else 999,
                "min_ratio": self.min_reserve_ratio,
                "active_policies": len([p for p in policies.values() if p.get('status') == 'active']),
                "checked_at": datetime.now(timezone.utc).isoformat()
            }

            # Log alerts
            if status in ["critical", "warning"]:
                self._log_alert(result)

            return result

        except Exception as e:
            logger.exception("Error checking reserve health: %s", e)
            return {
                "status": "error",
                "message": str(e),
                "reserves": 0,
                "liability": 0,
                "ratio": 0
            }

    def _log_alert(self, health: Dict):
        """Log reserve alerts and send webhook if configured"""
        current_time = datetime.now(timezone.utc)

        # Don't spam alerts - only alert once per hour
        if self.last_alert_time:
            time_since_last = (current_time - self.last_alert_time).total_seconds()
            if time_since_last < 3600:  # 1 hour
                return

        logger.warning(
            "RESERVE_ALERT: status=%s reserves=%.2f USDC liability=%.2f USDC ratio=%.2f",
            health['status'],
            health['reserves_usdc'],
            health['liability_usdc'],
            health['ratio']
        )

        self.last_alert_time = current_time

        # Send webhook alert if configured
        webhook_url = os.getenv("ALERT_WEBHOOK_URL", "")
        if webhook_url:
            try:
                payload = {
                    "text": "[%s] Reserve ratio: %.1f%% — %s" % (
                        health['status'].upper(),
                        health['ratio'] * 100,
                        health['message'],
                    )
                }
                httpx.post(webhook_url, json=payload, timeout=5.0)
            except Exception:
                logger.debug("Failed to send webhook alert", exc_info=True)

    def get_low_reserve_warning(self) -> Optional[str]:
        """
        Get warning message if reserves are low

        Returns:
            Warning message or None if reserves are healthy
        """
        health = self.check_reserve_health()

        if health['status'] == 'critical':
            return (
                f"CRITICAL: Reserves ({health['reserves_usdc']:.2f} USDC) below liabilities "
                f"({health['liability_usdc']:.2f} USDC). Cannot pay all claims!"
            )
        elif health['status'] == 'warning':
            return (
                f"WARNING: Reserve ratio ({health['ratio']:.2f}x) below minimum "
                f"({health['min_ratio']:.2f}x). Top up reserves soon."
            )

        return None
