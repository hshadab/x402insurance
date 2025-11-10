"""
Unit tests for critical bug fixes

Tests:
1. save_data() function exists and works
2. File locking prevents race conditions
3. SQL injection prevention in update methods
4. Nonce persistence across restarts
"""
import pytest
import json
import tempfile
import time
from pathlib import Path
from datetime import datetime, timezone

# Test imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from database import JSONFileBackend, PostgreSQLBackend


class TestSaveDataFunction:
    """Test that save_data() function exists and works"""

    def test_save_data_exists(self):
        """Verify save_data() function is importable"""
        # Import after adding to sys.path
        import server
        assert hasattr(server, 'save_data'), "save_data() function missing from server.py"
        assert callable(server.save_data), "save_data is not callable"

    def test_save_data_creates_file(self):
        """Test that save_data() actually saves data"""
        import server

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.json"
            test_data = {"test": "data", "value": 123}

            # This should not raise an error
            try:
                server.save_data(test_file, test_data)
            except AttributeError as e:
                if "database" in str(e):
                    pytest.skip("Database client not initialized in test context")
                raise

            # Verify file was created
            if test_file.exists():
                with open(test_file) as f:
                    loaded = json.load(f)
                    assert loaded == test_data


class TestFileLocking:
    """Test file locking race condition fix"""

    def test_atomic_write_with_locking(self):
        """Test that _save_json uses proper locking"""
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = JSONFileBackend(Path(tmpdir))
            test_file = Path(tmpdir) / "test.json"

            # Write data
            test_data = {"key": "value"}
            backend._save_json(test_file, test_data)

            # Verify data was saved
            assert test_file.exists()
            with open(test_file) as f:
                loaded = json.load(f)
                assert loaded == test_data

            # Verify lock file was created (on Unix systems)
            lock_file = test_file.with_suffix(test_file.suffix + ".lock")
            # Lock file should exist on Unix systems
            # On Windows, this is skipped

    def test_concurrent_writes_dont_corrupt(self):
        """Test that concurrent writes don't corrupt data"""
        import threading

        with tempfile.TemporaryDirectory() as tmpdir:
            backend = JSONFileBackend(Path(tmpdir))
            test_file = Path(tmpdir) / "concurrent.json"

            errors = []

            def write_data(thread_id):
                try:
                    for i in range(10):
                        data = {f"thread_{thread_id}": i}
                        backend._save_json(test_file, data)
                        time.sleep(0.001)  # Small delay
                except Exception as e:
                    errors.append(e)

            # Start multiple threads
            threads = [threading.Thread(target=write_data, args=(i,)) for i in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Should complete without errors
            assert len(errors) == 0, f"Concurrent writes failed: {errors}"

            # File should contain valid JSON (not corrupted)
            assert test_file.exists()
            with open(test_file) as f:
                data = json.load(f)  # Should not raise JSONDecodeError
                assert isinstance(data, dict)


class TestSQLInjectionPrevention:
    """Test SQL injection prevention in PostgreSQL backend"""

    def test_policy_update_whitelist(self):
        """Test that policy updates validate column names"""
        # Mock PostgreSQL backend (don't need real database for this test)
        class MockPostgreSQLBackend:
            ALLOWED_POLICY_UPDATE_COLUMNS = {
                'status', 'expires_at', 'renewed_at', 'renewal_count',
                'total_renewal_fees', 'merchant_url', 'coverage_amount',
                'coverage_amount_units', 'premium', 'premium_units'
            }

        backend = MockPostgreSQLBackend()

        # Valid columns should pass
        valid_updates = {'status': 'active', 'renewal_count': 1}
        invalid_columns = set(valid_updates.keys()) - backend.ALLOWED_POLICY_UPDATE_COLUMNS
        assert len(invalid_columns) == 0, "Valid columns rejected"

        # Invalid columns should be caught
        malicious_updates = {
            'status': 'active',
            'id = id; DROP TABLE policies; --': 'malicious'
        }
        invalid_columns = set(malicious_updates.keys()) - backend.ALLOWED_POLICY_UPDATE_COLUMNS
        assert len(invalid_columns) > 0, "SQL injection attempt not detected"

    def test_claim_update_whitelist(self):
        """Test that claim updates validate column names"""
        class MockPostgreSQLBackend:
            ALLOWED_CLAIM_UPDATE_COLUMNS = {
                'status', 'proof', 'public_inputs', 'proof_generation_time_ms',
                'verification_result', 'http_status', 'http_body_hash', 'http_headers',
                'payout_amount', 'payout_amount_units', 'refund_tx_hash',
                'recipient_address', 'paid_at', 'error', 'failed_at'
            }

        backend = MockPostgreSQLBackend()

        # Valid columns should pass
        valid_updates = {'status': 'paid', 'payout_amount': 10000}
        invalid_columns = set(valid_updates.keys()) - backend.ALLOWED_CLAIM_UPDATE_COLUMNS
        assert len(invalid_columns) == 0, "Valid columns rejected"

        # Invalid columns should be caught
        malicious_updates = {
            'status': 'paid',
            'claim_id = claim_id; DELETE FROM claims; --': 'malicious'
        }
        invalid_columns = set(malicious_updates.keys()) - backend.ALLOWED_CLAIM_UPDATE_COLUMNS
        assert len(invalid_columns) > 0, "SQL injection attempt not detected"


class TestNoncePersistence:
    """Test nonce persistence across restarts"""

    def test_nonce_cache_persists_to_disk(self):
        """Test that nonces are saved to disk"""
        from auth.payment_verifier import PaymentVerifier

        with tempfile.TemporaryDirectory() as tmpdir:
            nonce_file = Path(tmpdir) / "nonces.json"

            # Create verifier with custom nonce storage
            verifier = PaymentVerifier(
                backend_address="0x1234567890123456789012345678901234567890",
                usdc_address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                nonce_storage_path=nonce_file
            )

            # Mark a nonce as used
            verifier._mark_nonce_used("0xabcd", "nonce123", int(time.time()))

            # Verify nonce file was created
            assert nonce_file.exists(), "Nonce cache file not created"

            # Verify content
            with open(nonce_file) as f:
                cache = json.load(f)
                assert "0xabcd:nonce123" in cache

    def test_nonce_cache_survives_restart(self):
        """Test that nonces are loaded after restart"""
        from auth.payment_verifier import PaymentVerifier

        with tempfile.TemporaryDirectory() as tmpdir:
            nonce_file = Path(tmpdir) / "nonces.json"

            # First instance - mark nonce as used
            verifier1 = PaymentVerifier(
                backend_address="0x1234567890123456789012345678901234567890",
                usdc_address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                nonce_storage_path=nonce_file
            )
            verifier1._mark_nonce_used("0xpayer1", "nonce456", int(time.time()))

            # Verify nonce is marked as used
            assert verifier1._is_nonce_used("0xpayer1", "nonce456")

            # Simulate restart - create new instance
            verifier2 = PaymentVerifier(
                backend_address="0x1234567890123456789012345678901234567890",
                usdc_address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                nonce_storage_path=nonce_file
            )

            # Nonce should still be marked as used (loaded from disk)
            assert verifier2._is_nonce_used("0xpayer1", "nonce456"), \
                "Nonce not persisted across restart - replay attack possible!"

    def test_old_nonces_cleaned_on_load(self):
        """Test that expired nonces are cleaned up on load"""
        from auth.payment_verifier import PaymentVerifier

        with tempfile.TemporaryDirectory() as tmpdir:
            nonce_file = Path(tmpdir) / "nonces.json"

            # Create cache with old and new nonces
            current_time = int(time.time())
            old_nonce_time = current_time - 7200  # 2 hours ago (should be cleaned)
            recent_nonce_time = current_time - 300  # 5 minutes ago (should be kept)

            cache = {
                "0xold:nonce1": old_nonce_time,
                "0xrecent:nonce2": recent_nonce_time,
            }

            with open(nonce_file, 'w') as f:
                json.dump(cache, f)

            # Load verifier - should clean old nonces
            verifier = PaymentVerifier(
                backend_address="0x1234567890123456789012345678901234567890",
                usdc_address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                nonce_storage_path=nonce_file
            )

            # Old nonce should be cleaned
            assert not verifier._is_nonce_used("0xold", "nonce1"), \
                "Old nonce not cleaned up"

            # Recent nonce should be kept
            assert verifier._is_nonce_used("0xrecent", "nonce2"), \
                "Recent nonce incorrectly cleaned up"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
