"""
Database abstraction layer

Supports both JSON files (for simple deployments) and PostgreSQL (for production).
Set DATABASE_URL environment variable to use PostgreSQL.
"""
import os
import json
import logging
import time
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

        if not self.database_url and os.getenv("ENV") == "production":
            logger.warning(
                "No DATABASE_URL configured in production — using JSON file storage. "
                "This is not recommended for production workloads."
            )

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

    def get_all_policies(self, limit: int = 0, offset: int = 0) -> Dict[str, Dict]:
        return self.backend.get_all_policies(limit=limit, offset=offset)

    def claim_policy(self, policy_id: str) -> Optional[Dict]:
        """Atomically mark a policy as claimed. Returns policy dict on success, None on failure."""
        return self.backend.claim_policy(policy_id)

    # Claim operations
    def create_claim(self, claim_id: str, claim_data: Dict) -> bool:
        return self.backend.create_claim(claim_id, claim_data)

    def get_claim(self, claim_id: str) -> Optional[Dict]:
        return self.backend.get_claim(claim_id)

    def update_claim(self, claim_id: str, updates: Dict) -> bool:
        return self.backend.update_claim(claim_id, updates)

    def get_all_claims(self, limit: int = 0, offset: int = 0) -> Dict[str, Dict]:
        return self.backend.get_all_claims(limit=limit, offset=offset)

    def get_claim_by_idempotency_key(self, key: str) -> Optional[Dict]:
        return self.backend.get_claim_by_idempotency_key(key)

    # Nonce operations
    def is_nonce_used(self, payer: str, nonce: str) -> bool:
        return self.backend.is_nonce_used(payer, nonce)

    def mark_nonce_used(self, payer: str, nonce: str, timestamp: int) -> None:
        self.backend.mark_nonce_used(payer, nonce, timestamp)

    def cleanup_nonces(self, max_age_seconds: int = 3600) -> int:
        return self.backend.cleanup_nonces(max_age_seconds)

    # Recovery
    def recover_stuck_policies(self, max_age_seconds: int = 600) -> int:
        """Reset policies stuck in 'claimed' status with no successful claim back to 'active'."""
        return self.backend.recover_stuck_policies(max_age_seconds)

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
        self.nonces_file = self.data_dir / "nonce_cache.json"

        # Try to import fcntl for file locking
        try:
            import fcntl
            self._fcntl = fcntl
        except ImportError:
            self._fcntl = None
            logger.debug("fcntl not available (Windows?), skipping file locking")

    def _acquire_lock(self, file_path: Path):
        """Acquire exclusive lock on file. Returns (lock_fd, lock_file) or (None, None)."""
        if not self._fcntl:
            return None, None
        lock_file = file_path.with_suffix(file_path.suffix + ".lock")
        lock_file.touch(exist_ok=True)
        lock_fd = open(lock_file, 'r+')
        self._fcntl.flock(lock_fd, self._fcntl.LOCK_EX)
        return lock_fd, lock_file

    def _release_lock(self, lock_fd):
        if lock_fd and self._fcntl:
            self._fcntl.flock(lock_fd, self._fcntl.LOCK_UN)
            lock_fd.close()

    def _atomic_write(self, path: Path, content: str):
        """Atomic file write"""
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with open(tmp_path, "w") as tf:
            tf.write(content)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(tmp_path, path)

    def _load_json_raw(self, file_path: Path) -> Dict:
        """Load JSON without acquiring any lock (caller must hold lock if needed)."""
        if not file_path.exists():
            return {}
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.error("Corrupted JSON in %s; returning empty dict", file_path)
            return {}

    def _load_json(self, file_path: Path) -> Dict:
        """Load JSON with a shared file lock (for standalone reads)."""
        if not file_path.exists():
            return {}
        try:
            with open(file_path, 'r') as f:
                if self._fcntl:
                    try:
                        self._fcntl.flock(f, self._fcntl.LOCK_SH)
                    except OSError:
                        pass
                return json.load(f)
        except json.JSONDecodeError:
            logger.error("Corrupted JSON in %s; returning empty dict", file_path)
            return {}

    def _save_json(self, file_path: Path, data: Dict):
        """Save JSON atomically with proper file locking"""
        content = json.dumps(data, indent=2, default=str)

        lock_fd = None
        try:
            lock_fd, _ = self._acquire_lock(file_path)
            self._atomic_write(file_path, content)
        except Exception as e:
            logger.exception("Failed to save %s: %s", file_path, e)
            raise
        finally:
            self._release_lock(lock_fd)

    # Policy operations
    def create_policy(self, policy_id: str, policy_data: Dict) -> bool:
        try:
            lock_fd = None
            try:
                lock_fd, _ = self._acquire_lock(self.policies_file)
                policies = self._load_json_raw(self.policies_file)
                policies[policy_id] = policy_data
                self._atomic_write(self.policies_file, json.dumps(policies, indent=2, default=str))
            finally:
                self._release_lock(lock_fd)
            return True
        except Exception as e:
            logger.exception("Failed to create policy: %s", e)
            return False

    def get_policy(self, policy_id: str) -> Optional[Dict]:
        policies = self._load_json(self.policies_file)
        return policies.get(policy_id)

    def update_policy(self, policy_id: str, updates: Dict) -> bool:
        try:
            lock_fd = None
            try:
                lock_fd, _ = self._acquire_lock(self.policies_file)
                policies = self._load_json_raw(self.policies_file)
                if policy_id not in policies:
                    return False
                policies[policy_id].update(updates)
                self._atomic_write(self.policies_file, json.dumps(policies, indent=2, default=str))
            finally:
                self._release_lock(lock_fd)
            return True
        except Exception as e:
            logger.exception("Failed to update policy: %s", e)
            return False

    def claim_policy(self, policy_id: str) -> Optional[Dict]:
        """Atomically mark policy as claimed if it's active and not expired."""
        lock_fd = None
        try:
            lock_fd, _ = self._acquire_lock(self.policies_file)
            policies = self._load_json_raw(self.policies_file)
            policy = policies.get(policy_id)
            if not policy:
                return None
            if policy.get('status') != 'active':
                return None
            # Check expiry
            try:
                expires_at_str = policy.get('expires_at', '')
                expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if expires_at < datetime.now(timezone.utc):
                    return None
            except (ValueError, TypeError):
                return None

            policy['status'] = 'claimed'
            policies[policy_id] = policy
            self._atomic_write(self.policies_file, json.dumps(policies, indent=2, default=str))
            return policy
        except Exception as e:
            logger.exception("Failed to claim policy: %s", e)
            return None
        finally:
            self._release_lock(lock_fd)

    def get_policies_by_wallet(self, wallet_address: str) -> List[Dict]:
        policies = self._load_json(self.policies_file)
        wallet_lower = wallet_address.lower()
        return [
            {**policy, 'policy_id': pid}
            for pid, policy in policies.items()
            if policy.get('agent_address', '').lower() == wallet_lower
        ]

    def get_all_policies(self, limit: int = 0, offset: int = 0) -> Dict[str, Dict]:
        policies = self._load_json(self.policies_file)
        if limit > 0:
            items = list(policies.items())
            items = items[offset:offset + limit]
            return dict(items)
        return policies

    # Claim operations
    def create_claim(self, claim_id: str, claim_data: Dict) -> bool:
        try:
            lock_fd = None
            try:
                lock_fd, _ = self._acquire_lock(self.claims_file)
                claims = self._load_json_raw(self.claims_file)
                claims[claim_id] = claim_data
                self._atomic_write(self.claims_file, json.dumps(claims, indent=2, default=str))
            finally:
                self._release_lock(lock_fd)
            return True
        except Exception as e:
            logger.exception("Failed to create claim: %s", e)
            return False

    def get_claim(self, claim_id: str) -> Optional[Dict]:
        claims = self._load_json(self.claims_file)
        return claims.get(claim_id)

    def update_claim(self, claim_id: str, updates: Dict) -> bool:
        try:
            lock_fd = None
            try:
                lock_fd, _ = self._acquire_lock(self.claims_file)
                claims = self._load_json_raw(self.claims_file)
                if claim_id not in claims:
                    return False
                claims[claim_id].update(updates)
                self._atomic_write(self.claims_file, json.dumps(claims, indent=2, default=str))
            finally:
                self._release_lock(lock_fd)
            return True
        except Exception as e:
            logger.exception("Failed to update claim: %s", e)
            return False

    def get_all_claims(self, limit: int = 0, offset: int = 0) -> Dict[str, Dict]:
        claims = self._load_json(self.claims_file)
        if limit > 0:
            items = list(claims.items())
            items = items[offset:offset + limit]
            return dict(items)
        return claims

    def get_claim_by_idempotency_key(self, key: str) -> Optional[Dict]:
        claims = self._load_json(self.claims_file)
        for cid, claim in claims.items():
            if claim.get('idempotency_key') == key:
                return {**claim, 'claim_id': claim.get('claim_id', cid)}
        return None

    # Nonce operations
    def is_nonce_used(self, payer: str, nonce: str) -> bool:
        key = f"{payer.lower()}:{nonce}"
        cache = self._load_json(self.nonces_file)
        return key in cache

    def mark_nonce_used(self, payer: str, nonce: str, timestamp: int) -> None:
        lock_fd = None
        try:
            lock_fd, _ = self._acquire_lock(self.nonces_file)
            cache = self._load_json_raw(self.nonces_file)
            key = f"{payer.lower()}:{nonce}"
            cache[key] = timestamp
            self._atomic_write(self.nonces_file, json.dumps(cache, indent=2, default=str))
        finally:
            self._release_lock(lock_fd)

    def cleanup_nonces(self, max_age_seconds: int = 3600) -> int:
        lock_fd = None
        try:
            lock_fd, _ = self._acquire_lock(self.nonces_file)
            cache = self._load_json_raw(self.nonces_file)
            cutoff = int(time.time()) - max_age_seconds
            old = [k for k, v in cache.items() if v < cutoff]
            for k in old:
                del cache[k]
            if old:
                self._atomic_write(self.nonces_file, json.dumps(cache, indent=2, default=str))
            return len(old)
        finally:
            self._release_lock(lock_fd)

    def recover_stuck_policies(self, max_age_seconds: int = 600) -> int:
        """Reset policies stuck in 'claimed' with no paid/approved claim back to 'active'."""
        lock_fd = None
        try:
            lock_fd, _ = self._acquire_lock(self.policies_file)
            policies = self._load_json_raw(self.policies_file)
            claims = self._load_json(self.claims_file)
            current_time = datetime.now(timezone.utc)
            recovered = 0

            # Build set of policy_ids that have an active claim (processing/approved/paid)
            active_claim_policies = set()
            for claim in claims.values():
                if claim.get('status') in ('processing', 'approved', 'paid'):
                    active_claim_policies.add(claim.get('policy_id'))

            for pid, policy in policies.items():
                if policy.get('status') != 'claimed':
                    continue
                if pid in active_claim_policies:
                    continue
                # Check if policy has been stuck for longer than max_age_seconds
                try:
                    expires_at = datetime.fromisoformat(policy.get('expires_at', '').replace('Z', '+00:00'))
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=timezone.utc)
                    if expires_at > current_time:
                        policy['status'] = 'active'
                        recovered += 1
                except (ValueError, TypeError):
                    pass

            if recovered > 0:
                self._atomic_write(self.policies_file, json.dumps(policies, indent=2, default=str))
            logger.info("Recovered %d stuck policies", recovered)
            return recovered
        except Exception as e:
            logger.exception("Failed to recover stuck policies: %s", e)
            return 0
        finally:
            self._release_lock(lock_fd)

    def cleanup_expired_policies(self) -> int:
        """Archive expired policies (soft-delete)"""
        lock_fd = None
        try:
            lock_fd, _ = self._acquire_lock(self.policies_file)
            policies = self._load_json_raw(self.policies_file)
            current_time = datetime.now(timezone.utc)

            expired_count = 0

            for pid, policy in policies.items():
                try:
                    if policy.get('status') != 'active':
                        continue
                    expires_at_str = policy.get('expires_at', '')
                    expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=timezone.utc)

                    if expires_at <= current_time:
                        policy['status'] = 'archived'
                        expired_count += 1
                except (ValueError, TypeError):
                    pass

            if expired_count > 0:
                self._atomic_write(self.policies_file, json.dumps(policies, indent=2, default=str))
            logger.info("Archived %d expired policies", expired_count)
            return expired_count

        except Exception as e:
            logger.exception("Failed to archive expired policies: %s", e)
            return 0
        finally:
            self._release_lock(lock_fd)


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
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        idempotency_key VARCHAR(255),
                        server_verified BOOLEAN,
                        server_http_status INTEGER,
                        merchant_url TEXT
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_claims_policy
                    ON claims(policy_id)
                """)
                cur.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_claims_idempotency_key
                    ON claims(idempotency_key) WHERE idempotency_key IS NOT NULL
                """)

                # Nonces table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS nonces (
                        nonce_key VARCHAR(255) PRIMARY KEY,
                        created_at INTEGER NOT NULL
                    )
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
            raise
        except Exception as e:
            logger.exception("Failed to update policy: %s", e)
            return False

    def claim_policy(self, policy_id: str) -> Optional[Dict]:
        """Atomically mark policy as claimed if active and not expired. Returns policy or None."""
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("""
                        UPDATE policies
                        SET status = 'claimed', updated_at = NOW()
                        WHERE policy_id = %s AND status = 'active' AND expires_at > NOW()
                        RETURNING *
                    """, (policy_id,))
                    row = cur.fetchone()
                    return dict(row) if row else None
        except Exception as e:
            logger.exception("Failed to claim policy: %s", e)
            return None

    def get_policies_by_wallet(self, wallet_address: str) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM policies WHERE LOWER(agent_address) = LOWER(%s)",
                    (wallet_address,)
                )
                return [dict(row) for row in cur.fetchall()]

    def get_all_policies(self, limit: int = 0, offset: int = 0) -> Dict[str, Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if limit > 0:
                    cur.execute("SELECT * FROM policies ORDER BY created_at DESC LIMIT %s OFFSET %s", (limit, offset))
                else:
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
                            status, created_at, paid_at,
                            idempotency_key, server_verified, server_http_status, merchant_url
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        claim_id,
                        claim_data['policy_id'],
                        claim_data.get('proof'),
                        json.dumps(claim_data.get('public_inputs')),
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
                        claim_data.get('paid_at'),
                        claim_data.get('idempotency_key'),
                        claim_data.get('server_verified'),
                        claim_data.get('server_http_status'),
                        claim_data.get('merchant_url'),
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
        'recipient_address', 'paid_at', 'error', 'failed_at',
        'server_verified', 'server_http_status', 'merchant_url', 'idempotency_key'
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
            raise
        except Exception as e:
            logger.exception("Failed to update claim: %s", e)
            return False

    def get_all_claims(self, limit: int = 0, offset: int = 0) -> Dict[str, Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if limit > 0:
                    cur.execute("SELECT * FROM claims ORDER BY created_at DESC LIMIT %s OFFSET %s", (limit, offset))
                else:
                    cur.execute("SELECT * FROM claims")
                return {row['claim_id']: dict(row) for row in cur.fetchall()}

    def get_claim_by_idempotency_key(self, key: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM claims WHERE idempotency_key = %s LIMIT 1", (key,))
                row = cur.fetchone()
                return dict(row) if row else None

    # Nonce operations
    def is_nonce_used(self, payer: str, nonce: str) -> bool:
        key = f"{payer.lower()}:{nonce}"
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM nonces WHERE nonce_key = %s", (key,))
                    return cur.fetchone() is not None
        except Exception as e:
            logger.exception("Failed to check nonce: %s", e)
            return False

    def mark_nonce_used(self, payer: str, nonce: str, timestamp: int) -> None:
        key = f"{payer.lower()}:{nonce}"
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO nonces (nonce_key, created_at) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (key, timestamp)
                    )
        except Exception as e:
            logger.exception("Failed to mark nonce: %s", e)

    def cleanup_nonces(self, max_age_seconds: int = 3600) -> int:
        cutoff = int(time.time()) - max_age_seconds
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM nonces WHERE created_at < %s", (cutoff,))
                    return cur.rowcount
        except Exception as e:
            logger.exception("Failed to cleanup nonces: %s", e)
            return 0

    def recover_stuck_policies(self, max_age_seconds: int = 600) -> int:
        """Reset policies stuck in 'claimed' with no paid/approved claim back to 'active'."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE policies p
                        SET status = 'active', updated_at = NOW()
                        WHERE p.status = 'claimed'
                          AND p.expires_at > NOW()
                          AND NOT EXISTS (
                              SELECT 1 FROM claims c
                              WHERE c.policy_id = p.policy_id
                                AND c.status IN ('processing', 'approved', 'paid')
                          )
                          AND p.updated_at < NOW() - INTERVAL '%s seconds'
                    """, (max_age_seconds,))
                    count = cur.rowcount
            logger.info("Recovered %d stuck policies", count)
            return count
        except Exception as e:
            logger.exception("Failed to recover stuck policies: %s", e)
            return 0

    def cleanup_expired_policies(self) -> int:
        """Archive expired policies (soft-delete)"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE policies
                        SET status = 'archived', updated_at = NOW()
                        WHERE expires_at < NOW() AND status = 'active'
                    """)
                    count = cur.rowcount
            logger.info("Archived %d expired policies", count)
            return count
        except Exception as e:
            logger.exception("Failed to archive expired policies: %s", e)
            return 0
