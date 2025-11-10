"""
Database abstraction layer

Supports both JSON files (for simple deployments) and PostgreSQL (for production).
Set DATABASE_URL environment variable to use PostgreSQL.
"""
import os
import json
import logging
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime, timezone
from contextlib import contextmanager

logger = logging.getLogger("x402insurance.database")

# Try to import psycopg2 for PostgreSQL support
try:
    import psycopg2
    import psycopg2.extras
    from psycopg2.pool import SimpleConnectionPool
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False
    logger.info("psycopg2 not installed, using JSON file storage")


class DatabaseClient:
    """Abstract database client - auto-selects JSON or PostgreSQL"""

    def __init__(self, database_url: Optional[str] = None, data_dir: Path = Path("data")):
        self.database_url = database_url or os.getenv("DATABASE_URL")

        if self.database_url and HAS_POSTGRES:
            logger.info("Using PostgreSQL database")
            self.backend = PostgreSQLBackend(self.database_url)
        else:
            logger.info("Using JSON file storage")
            self.backend = JSONFileBackend(data_dir)

    # Policy operations
    def create_policy(self, policy_id: str, policy_data: Dict) -> bool:
        return self.backend.create_policy(policy_id, policy_data)

    def get_policy(self, policy_id: str) -> Optional[Dict]:
        return self.backend.get_policy(policy_id)

    def update_policy(self, policy_id: str, updates: Dict) -> bool:
        return self.backend.update_policy(policy_id, updates)

    def get_policies_by_wallet(self, wallet_address: str) -> List[Dict]:
        return self.backend.get_policies_by_wallet(wallet_address)

    def get_all_policies(self) -> Dict[str, Dict]:
        return self.backend.get_all_policies()

    # Claim operations
    def create_claim(self, claim_id: str, claim_data: Dict) -> bool:
        return self.backend.create_claim(claim_id, claim_data)

    def get_claim(self, claim_id: str) -> Optional[Dict]:
        return self.backend.get_claim(claim_id)

    def update_claim(self, claim_id: str, updates: Dict) -> bool:
        return self.backend.update_claim(claim_id, updates)

    def get_all_claims(self) -> Dict[str, Dict]:
        return self.backend.get_all_claims()

    # Cleanup
    def cleanup_expired_policies(self) -> int:
        return self.backend.cleanup_expired_policies()


class JSONFileBackend:
    """JSON file-based storage (original implementation with improvements)"""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(exist_ok=True)
        self.policies_file = self.data_dir / "policies.json"
        self.claims_file = self.data_dir / "claims.json"

    def _atomic_write(self, path: Path, content: str):
        """Atomic file write"""
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with open(tmp_path, "w") as tf:
            tf.write(content)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(tmp_path, path)

    def _load_json(self, file_path: Path) -> Dict:
        """Load JSON with file locking"""
        if not file_path.exists():
            return {}
        try:
            with open(file_path, 'r') as f:
                try:
                    import fcntl
                    fcntl.flock(f, fcntl.LOCK_SH)
                except Exception:
                    pass
                return json.load(f)
        except json.JSONDecodeError:
            logger.error("Corrupted JSON in %s; returning empty dict", file_path)
            return {}

    def _save_json(self, file_path: Path, data: Dict):
        """Save JSON atomically with proper file locking"""
        content = json.dumps(data, indent=2, default=str)

        # Try to use file locking (Unix/Linux only)
        try:
            import fcntl
            has_fcntl = True
        except ImportError:
            has_fcntl = False
            logger.debug("fcntl not available (Windows?), skipping file locking")

        if has_fcntl:
            # Acquire lock, write atomically, then release
            lock_file = file_path.with_suffix(file_path.suffix + ".lock")
            try:
                # Create lock file if it doesn't exist
                lock_file.touch(exist_ok=True)

                with open(lock_file, 'r+') as lock_fd:
                    # Acquire exclusive lock (blocks until available)
                    fcntl.flock(lock_fd, fcntl.LOCK_EX)
                    try:
                        # Perform atomic write while lock is held
                        self._atomic_write(file_path, content)
                    finally:
                        # Release lock
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except Exception as e:
                logger.exception("Failed to save %s with locking: %s", file_path, e)
                raise
        else:
            # No locking available (Windows), just do atomic write
            try:
                self._atomic_write(file_path, content)
            except Exception as e:
                logger.exception("Failed to save %s: %s", file_path, e)
                raise

    # Policy operations
    def create_policy(self, policy_id: str, policy_data: Dict) -> bool:
        try:
            policies = self._load_json(self.policies_file)
            policies[policy_id] = policy_data
            self._save_json(self.policies_file, policies)
            return True
        except Exception as e:
            logger.exception("Failed to create policy: %s", e)
            return False

    def get_policy(self, policy_id: str) -> Optional[Dict]:
        policies = self._load_json(self.policies_file)
        return policies.get(policy_id)

    def update_policy(self, policy_id: str, updates: Dict) -> bool:
        try:
            policies = self._load_json(self.policies_file)
            if policy_id not in policies:
                return False
            policies[policy_id].update(updates)
            self._save_json(self.policies_file, policies)
            return True
        except Exception as e:
            logger.exception("Failed to update policy: %s", e)
            return False

    def get_policies_by_wallet(self, wallet_address: str) -> List[Dict]:
        policies = self._load_json(self.policies_file)
        wallet_lower = wallet_address.lower()
        return [
            {**policy, 'policy_id': pid}
            for pid, policy in policies.items()
            if policy.get('agent_address', '').lower() == wallet_lower
        ]

    def get_all_policies(self) -> Dict[str, Dict]:
        return self._load_json(self.policies_file)

    # Claim operations
    def create_claim(self, claim_id: str, claim_data: Dict) -> bool:
        try:
            claims = self._load_json(self.claims_file)
            claims[claim_id] = claim_data
            self._save_json(self.claims_file, claims)
            return True
        except Exception as e:
            logger.exception("Failed to create claim: %s", e)
            return False

    def get_claim(self, claim_id: str) -> Optional[Dict]:
        claims = self._load_json(self.claims_file)
        return claims.get(claim_id)

    def update_claim(self, claim_id: str, updates: Dict) -> bool:
        try:
            claims = self._load_json(self.claims_file)
            if claim_id not in claims:
                return False
            claims[claim_id].update(updates)
            self._save_json(self.claims_file, claims)
            return True
        except Exception as e:
            logger.exception("Failed to update claim: %s", e)
            return False

    def get_all_claims(self) -> Dict[str, Dict]:
        return self._load_json(self.claims_file)

    def cleanup_expired_policies(self) -> int:
        """Remove expired policies"""
        try:
            policies = self._load_json(self.policies_file)
            current_time = datetime.now(timezone.utc)

            expired_count = 0
            active_policies = {}

            for pid, policy in policies.items():
                try:
                    expires_at_str = policy.get('expires_at', '')
                    expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=timezone.utc)

                    if expires_at > current_time and policy.get('status') == 'active':
                        active_policies[pid] = policy
                    else:
                        expired_count += 1
                except Exception:
                    # Keep policy if we can't parse expiration
                    active_policies[pid] = policy

            self._save_json(self.policies_file, active_policies)
            logger.info("Cleaned up %d expired policies", expired_count)
            return expired_count

        except Exception as e:
            logger.exception("Failed to cleanup expired policies: %s", e)
            return 0


class PostgreSQLBackend:
    """PostgreSQL-based storage for production"""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.pool = SimpleConnectionPool(1, 10, database_url)
        self._create_tables()

    @contextmanager
    def get_connection(self):
        """Get connection from pool"""
        conn = self.pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self.pool.putconn(conn)

    def _create_tables(self):
        """Create database tables if they don't exist"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Policies table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS policies (
                        policy_id VARCHAR(36) PRIMARY KEY,
                        agent_address VARCHAR(42) NOT NULL,
                        merchant_url TEXT NOT NULL,
                        merchant_url_hash VARCHAR(64),
                        coverage_amount DECIMAL(20, 6) NOT NULL,
                        coverage_amount_units BIGINT NOT NULL,
                        premium DECIMAL(20, 6) NOT NULL,
                        premium_units BIGINT NOT NULL,
                        status VARCHAR(20) NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                        expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                    )
                """)

                # Add indexes
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_policies_agent_status
                    ON policies(agent_address, status)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_policies_expires
                    ON policies(expires_at) WHERE status = 'active'
                """)

                # Claims table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS claims (
                        claim_id VARCHAR(36) PRIMARY KEY,
                        policy_id VARCHAR(36) REFERENCES policies(policy_id),
                        proof TEXT,
                        public_inputs JSONB,
                        proof_generation_time_ms INTEGER,
                        verification_result BOOLEAN,
                        http_status INTEGER,
                        http_body_hash VARCHAR(64),
                        http_headers JSONB,
                        payout_amount DECIMAL(20, 6),
                        payout_amount_units BIGINT,
                        refund_tx_hash VARCHAR(66),
                        recipient_address VARCHAR(42),
                        status VARCHAR(20) NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                        paid_at TIMESTAMP WITH TIME ZONE,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_claims_policy
                    ON claims(policy_id)
                """)

        logger.info("Database tables created/verified")

    # Policy operations
    def create_policy(self, policy_id: str, policy_data: Dict) -> bool:
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO policies (
                            policy_id, agent_address, merchant_url, merchant_url_hash,
                            coverage_amount, coverage_amount_units, premium, premium_units,
                            status, created_at, expires_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        policy_id,
                        policy_data['agent_address'],
                        policy_data['merchant_url'],
                        policy_data.get('merchant_url_hash'),
                        policy_data['coverage_amount'],
                        policy_data['coverage_amount_units'],
                        policy_data['premium'],
                        policy_data['premium_units'],
                        policy_data['status'],
                        policy_data['created_at'],
                        policy_data['expires_at']
                    ))
            return True
        except Exception as e:
            logger.exception("Failed to create policy: %s", e)
            return False

    def get_policy(self, policy_id: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM policies WHERE policy_id = %s", (policy_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    # Whitelist of allowed columns for policy updates (SQL injection prevention)
    ALLOWED_POLICY_UPDATE_COLUMNS = {
        'status', 'expires_at', 'renewed_at', 'renewal_count',
        'total_renewal_fees', 'merchant_url', 'coverage_amount',
        'coverage_amount_units', 'premium', 'premium_units'
    }

    def update_policy(self, policy_id: str, updates: Dict) -> bool:
        try:
            # Validate all column names against whitelist (SQL injection prevention)
            invalid_columns = set(updates.keys()) - self.ALLOWED_POLICY_UPDATE_COLUMNS
            if invalid_columns:
                logger.error(
                    "Attempted to update invalid columns: %s. Allowed: %s",
                    invalid_columns, self.ALLOWED_POLICY_UPDATE_COLUMNS
                )
                raise ValueError(f"Invalid column names: {invalid_columns}")

            # Build UPDATE query with validated column names
            set_clause = ", ".join([f"{k} = %s" for k in updates.keys()])
            values = list(updates.values()) + [policy_id]

            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE policies SET {set_clause}, updated_at = NOW() WHERE policy_id = %s",
                        values
                    )
            return True
        except ValueError:
            # Re-raise validation errors
            raise
        except Exception as e:
            logger.exception("Failed to update policy: %s", e)
            return False

    def get_policies_by_wallet(self, wallet_address: str) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM policies WHERE LOWER(agent_address) = LOWER(%s)",
                    (wallet_address,)
                )
                return [dict(row) for row in cur.fetchall()]

    def get_all_policies(self) -> Dict[str, Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM policies")
                return {row['policy_id']: dict(row) for row in cur.fetchall()}

    # Claim operations
    def create_claim(self, claim_id: str, claim_data: Dict) -> bool:
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO claims (
                            claim_id, policy_id, proof, public_inputs,
                            proof_generation_time_ms, verification_result,
                            http_status, http_body_hash, http_headers,
                            payout_amount, payout_amount_units,
                            refund_tx_hash, recipient_address,
                            status, created_at, paid_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        claim_id,
                        claim_data['policy_id'],
                        claim_data['proof'],
                        json.dumps(claim_data['public_inputs']),
                        claim_data.get('proof_generation_time_ms'),
                        claim_data.get('verification_result'),
                        claim_data.get('http_status'),
                        claim_data.get('http_body_hash'),
                        json.dumps(claim_data.get('http_headers', {})),
                        claim_data.get('payout_amount'),
                        claim_data.get('payout_amount_units'),
                        claim_data.get('refund_tx_hash'),
                        claim_data.get('recipient_address'),
                        claim_data['status'],
                        claim_data['created_at'],
                        claim_data.get('paid_at')
                    ))
            return True
        except Exception as e:
            logger.exception("Failed to create claim: %s", e)
            return False

    def get_claim(self, claim_id: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM claims WHERE claim_id = %s", (claim_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    # Whitelist of allowed columns for claim updates (SQL injection prevention)
    ALLOWED_CLAIM_UPDATE_COLUMNS = {
        'status', 'proof', 'public_inputs', 'proof_generation_time_ms',
        'verification_result', 'http_status', 'http_body_hash', 'http_headers',
        'payout_amount', 'payout_amount_units', 'refund_tx_hash',
        'recipient_address', 'paid_at', 'error', 'failed_at'
    }

    def update_claim(self, claim_id: str, updates: Dict) -> bool:
        try:
            # Validate all column names against whitelist (SQL injection prevention)
            invalid_columns = set(updates.keys()) - self.ALLOWED_CLAIM_UPDATE_COLUMNS
            if invalid_columns:
                logger.error(
                    "Attempted to update invalid columns: %s. Allowed: %s",
                    invalid_columns, self.ALLOWED_CLAIM_UPDATE_COLUMNS
                )
                raise ValueError(f"Invalid column names: {invalid_columns}")

            # Build UPDATE query with validated column names
            set_clause = ", ".join([f"{k} = %s" for k in updates.keys()])
            values = list(updates.values()) + [claim_id]

            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE claims SET {set_clause}, updated_at = NOW() WHERE claim_id = %s",
                        values
                    )
            return True
        except ValueError:
            # Re-raise validation errors
            raise
        except Exception as e:
            logger.exception("Failed to update claim: %s", e)
            return False

    def get_all_claims(self) -> Dict[str, Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM claims")
                return {row['claim_id']: dict(row) for row in cur.fetchall()}

    def cleanup_expired_policies(self) -> int:
        """Archive expired policies"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        DELETE FROM policies
                        WHERE expires_at < NOW() AND status = 'active'
                    """)
                    count = cur.rowcount
            logger.info("Cleaned up %d expired policies", count)
            return count
        except Exception as e:
            logger.exception("Failed to cleanup expired policies: %s", e)
            return 0
