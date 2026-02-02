"""
Unit tests for critical bug fixes

Tests:
1. File locking prevents race conditions
2. SQL injection prevention in update methods
3. Nonce persistence via database backend
4. Atomic claim_policy operation
5. Bare-except regression: all except clauses are typed
"""
import pytest
import json
import tempfile
import time
import ast
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Test imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.database import JSONFileBackend, DatabaseClient


class TestFileLocking:
    """Test file locking race condition fix"""

    def test_atomic_write_with_locking(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = JSONFileBackend(Path(tmpdir))
            test_file = Path(tmpdir) / "test.json"

            test_data = {"key": "value"}
            backend._save_json(test_file, test_data)

            assert test_file.exists()
            with open(test_file) as f:
                loaded = json.load(f)
                assert loaded == test_data

    def test_concurrent_writes_dont_corrupt(self):
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
                        time.sleep(0.001)
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=write_data, args=(i,)) for i in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0, f"Concurrent writes failed: {errors}"
            assert test_file.exists()
            with open(test_file) as f:
                data = json.load(f)
                assert isinstance(data, dict)


class TestSQLInjectionPrevention:
    """Test SQL injection prevention in PostgreSQL backend"""

    def test_policy_update_whitelist(self):
        from core.database import PostgreSQLBackend

        valid_updates = {'status': 'active', 'renewal_count': 1}
        invalid_columns = set(valid_updates.keys()) - PostgreSQLBackend.ALLOWED_POLICY_UPDATE_COLUMNS
        assert len(invalid_columns) == 0, "Valid columns rejected"

        malicious_updates = {
            'status': 'active',
            'id = id; DROP TABLE policies; --': 'malicious'
        }
        invalid_columns = set(malicious_updates.keys()) - PostgreSQLBackend.ALLOWED_POLICY_UPDATE_COLUMNS
        assert len(invalid_columns) > 0, "SQL injection attempt not detected"

    def test_claim_update_whitelist(self):
        from core.database import PostgreSQLBackend

        valid_updates = {'status': 'paid', 'payout_amount': 10000}
        invalid_columns = set(valid_updates.keys()) - PostgreSQLBackend.ALLOWED_CLAIM_UPDATE_COLUMNS
        assert len(invalid_columns) == 0, "Valid columns rejected"

        malicious_updates = {
            'status': 'paid',
            'claim_id = claim_id; DELETE FROM claims; --': 'malicious'
        }
        invalid_columns = set(malicious_updates.keys()) - PostgreSQLBackend.ALLOWED_CLAIM_UPDATE_COLUMNS
        assert len(invalid_columns) > 0, "SQL injection attempt not detected"


class TestNoncePersistenceViaDatabase:
    """Test nonce persistence through database backend"""

    def test_nonce_stored_and_retrieved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = DatabaseClient(data_dir=Path(tmpdir))
            db.mark_nonce_used("0xpayer1", "nonce123", int(time.time()))
            assert db.is_nonce_used("0xpayer1", "nonce123")
            assert not db.is_nonce_used("0xpayer1", "nonce999")

    def test_nonce_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db1 = DatabaseClient(data_dir=Path(tmpdir))
            db1.mark_nonce_used("0xpayer1", "nonce456", int(time.time()))
            assert db1.is_nonce_used("0xpayer1", "nonce456")

            # Simulate restart
            db2 = DatabaseClient(data_dir=Path(tmpdir))
            assert db2.is_nonce_used("0xpayer1", "nonce456"), \
                "Nonce not persisted across restart — replay attack possible!"

    def test_old_nonces_cleaned(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = DatabaseClient(data_dir=Path(tmpdir))
            current_time = int(time.time())
            db.mark_nonce_used("0xold", "nonce1", current_time - 7200)
            db.mark_nonce_used("0xrecent", "nonce2", current_time - 300)

            cleaned = db.cleanup_nonces(max_age_seconds=3600)
            assert cleaned == 1
            assert not db.is_nonce_used("0xold", "nonce1")
            assert db.is_nonce_used("0xrecent", "nonce2")


class TestClaimPolicyAtomic:
    """Test atomic claim_policy operation"""

    def test_claim_active_policy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = DatabaseClient(data_dir=Path(tmpdir))
            expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
            db.create_policy("p1", {
                "policy_id": "p1", "agent_address": "0xTest",
                "merchant_url": "https://example.com", "coverage_amount": 0.01,
                "coverage_amount_units": 10000, "premium": 0.0001, "premium_units": 100,
                "status": "active", "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": expires,
            })

            result = db.claim_policy("p1")
            assert result is not None
            assert result['status'] == 'claimed'

            # Second attempt should fail
            result2 = db.claim_policy("p1")
            assert result2 is None

    def test_claim_nonexistent_policy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = DatabaseClient(data_dir=Path(tmpdir))
            assert db.claim_policy("nonexistent") is None

    def test_claim_expired_policy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = DatabaseClient(data_dir=Path(tmpdir))
            expired = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            db.create_policy("p2", {
                "policy_id": "p2", "agent_address": "0xTest",
                "merchant_url": "https://example.com", "coverage_amount": 0.01,
                "coverage_amount_units": 10000, "premium": 0.0001, "premium_units": 100,
                "status": "active", "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": expired,
            })
            assert db.claim_policy("p2") is None


class TestBareExceptRegression:
    """Verify no bare 'except:' clauses exist in the codebase."""

    SOURCE_FILES = [
        "app.py", "database.py", "blockchain.py", "proof_client.py",
        "utils.py", "extensions.py",
        "auth/payment_verifier.py",
        "blueprints/policies.py", "blueprints/claims.py",
        "blueprints/discovery.py", "blueprints/verify.py",
        "blueprints/health.py",
        "tasks/claim_processor.py", "tasks/reserve_monitor.py",
    ]

    def test_no_bare_except_clauses(self):
        root = Path(__file__).parent.parent.parent
        bare_excepts = []

        for rel_path in self.SOURCE_FILES:
            full_path = root / rel_path
            if not full_path.exists():
                continue
            source = full_path.read_text()
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and node.type is None:
                    bare_excepts.append(f"{rel_path}:{node.lineno}")

        assert bare_excepts == [], f"Found bare 'except:' clauses at: {bare_excepts}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
