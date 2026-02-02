"""
Unit tests for database client
"""
import pytest
import tempfile
import shutil
from pathlib import Path
from core.database import JSONFileBackend


class TestJSONFileBackend:
    """Test JSON file storage backend"""

    def setup_method(self):
        # Create temporary directory
        self.temp_dir = Path(tempfile.mkdtemp())
        self.backend = JSONFileBackend(self.temp_dir)

    def teardown_method(self):
        # Clean up
        shutil.rmtree(self.temp_dir)

    def test_create_and_get_policy(self):
        """Test creating and retrieving a policy"""
        policy_data = {
            "agent_address": "0xTest",
            "coverage_amount": 100,
            "status": "active"
        }

        # Create policy
        success = self.backend.create_policy("policy-123", policy_data)
        assert success is True

        # Retrieve policy
        policy = self.backend.get_policy("policy-123")
        assert policy is not None
        assert policy["agent_address"] == "0xTest"
        assert policy["coverage_amount"] == 100

    def test_update_policy(self):
        """Test updating a policy"""
        policy_data = {
            "agent_address": "0xTest",
            "status": "active"
        }

        self.backend.create_policy("policy-123", policy_data)

        # Update
        success = self.backend.update_policy("policy-123", {"status": "claimed"})
        assert success is True

        # Verify
        policy = self.backend.get_policy("policy-123")
        assert policy["status"] == "claimed"

    def test_get_nonexistent_policy(self):
        """Test retrieving non-existent policy"""
        policy = self.backend.get_policy("nonexistent")
        assert policy is None
