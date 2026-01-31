"""
Tests for reserve health monitoring.
"""
import pytest
from unittest.mock import MagicMock
from tasks.reserve_monitor import ReserveMonitor


class TestReserveMonitor:
    def setup_method(self):
        self.mock_blockchain = MagicMock()
        self.mock_database = MagicMock()
        self.monitor = ReserveMonitor(
            blockchain_client=self.mock_blockchain,
            database_client=self.mock_database,
            min_reserve_ratio=1.5
        )

    def test_healthy_reserves(self):
        self.mock_blockchain.get_balance.return_value = 1_000_000  # 1 USDC
        self.mock_database.get_all_policies.return_value = {
            "p1": {"status": "active", "coverage_amount_units": 100_000}
        }
        health = self.monitor.check_reserve_health()
        assert health["status"] == "healthy"

    def test_warning_reserves(self):

        self.mock_blockchain.get_balance.return_value = 120_000
        self.mock_database.get_all_policies.return_value = {
            "p1": {"status": "active", "coverage_amount_units": 100_000}
        }
        health = self.monitor.check_reserve_health()
        assert health["status"] == "warning"

    def test_critical_reserves(self):

        self.mock_blockchain.get_balance.return_value = 50_000
        self.mock_database.get_all_policies.return_value = {
            "p1": {"status": "active", "coverage_amount_units": 100_000}
        }
        health = self.monitor.check_reserve_health()
        assert health["status"] == "critical"

    def test_no_active_policies(self):

        self.mock_blockchain.get_balance.return_value = 1_000_000
        self.mock_database.get_all_policies.return_value = {}
        health = self.monitor.check_reserve_health()
        assert health["status"] == "healthy"
