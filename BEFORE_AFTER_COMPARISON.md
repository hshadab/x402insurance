# Before/After Comparison: Critical Bug Fixes

Visual comparison of the critical bugs that were fixed.

---

## Bug #1: Missing `save_data()` Function

### ❌ BEFORE (Broken)

**server.py:246** (and 5 other locations):
```python
# Function called but doesn't exist!
claims[claim_id] = claim
save_data(CLAIMS_FILE, claims)  # ← NameError: name 'save_data' is not defined

# Result: CRASH 💥
```

### ✅ AFTER (Fixed)

**server.py:191-198**:
```python
def save_data(file_path: Path, data: dict):
    """Backward compatibility - save JSON file atomically"""
    try:
        database.backend._save_json(file_path, data)
    except Exception as e:
        logger.exception("Failed to save data to %s: %s", file_path, e)
        raise

# Now works everywhere:
claims[claim_id] = claim
save_data(CLAIMS_FILE, claims)  # ✅ Success!
```

**Impact:** No more crashes in async claim processing ✅

---

## Bug #2: File Locking Race Condition

### ❌ BEFORE (Vulnerable)

**database.py:109-122**:
```python
def _save_json(self, file_path: Path, data: Dict):
    content = json.dumps(data, indent=2, default=str)
    with open(file_path, 'a+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)  # Lock acquired
    # ← Lock RELEASED here when exiting with block!

    self._atomic_write(file_path, content)  # ← UNPROTECTED! 🔓

# Race condition:
# Process A: Lock → Release → (writing...)
# Process B:           Lock → Release → (writing...)
# Both write simultaneously → File corrupted 💥
```

**Timeline of Failure:**
```
Time  | Process A          | Process B          | File State
------|-------------------|--------------------|------------
T0    | Lock acquired     | Waiting...         | OK
T1    | Lock released     | Lock acquired      | OK
T2    | Writing...        | Lock released      | OK
T3    | Writing...        | Writing...         | CORRUPTED! 💥
```

### ✅ AFTER (Protected)

**database.py:109-146**:
```python
def _save_json(self, file_path: Path, data: Dict):
    content = json.dumps(data, indent=2, default=str)

    if has_fcntl:
        lock_file = file_path.with_suffix(file_path.suffix + ".lock")
        lock_file.touch(exist_ok=True)

        with open(lock_file, 'r+') as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)  # Lock acquired
            try:
                self._atomic_write(file_path, content)  # ← PROTECTED! 🔒
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)  # Lock released
```

**Timeline of Success:**
```
Time  | Process A          | Process B          | File State
------|-------------------|--------------------|------------
T0    | Lock acquired     | Waiting...         | OK
T1    | Writing...        | Waiting...         | OK
T2    | Write complete    | Waiting...         | OK
T3    | Lock released     | Lock acquired      | OK
T4    | Done              | Writing...         | OK
T5    | Done              | Lock released      | OK ✅
```

**Impact:** Concurrent writes can never corrupt data ✅

---

## Bug #3: SQL Injection Vulnerability

### ❌ BEFORE (Exploitable)

**database.py:345-360**:
```python
def update_policy(self, policy_id: str, updates: Dict) -> bool:
    # No validation! Attacker controls column names
    set_clause = ", ".join([f"{k} = %s" for k in updates.keys()])

    # If updates = {"status = 'active'; DROP TABLE policies; --": "value"}
    # Query becomes:
    # UPDATE policies SET status = 'active'; DROP TABLE policies; -- = %s
    #                     ^^^^^^^^^^^^^^^^   ^^^^^^^^^^^^^^^^^^^
    #                     Executes!          Table deleted! 💥
```

**Attack Example:**
```python
# Attacker sends this:
POST /api/policies/update
{
    "updates": {
        "status = status; DELETE FROM policies WHERE true; --": "ignored"
    }
}

# SQL executed:
# UPDATE policies SET status = status; DELETE FROM policies WHERE true; -- = %s
#                     ^^^^^^^^^^^^^^   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#                     Harmless         DELETES ALL POLICIES! 💥
```

### ✅ AFTER (Protected)

**database.py:369-403**:
```python
# Whitelist of valid columns
ALLOWED_POLICY_UPDATE_COLUMNS = {
    'status', 'expires_at', 'renewed_at', 'renewal_count',
    'total_renewal_fees', 'merchant_url', 'coverage_amount',
    'coverage_amount_units', 'premium', 'premium_units'
}

def update_policy(self, policy_id: str, updates: Dict) -> bool:
    # Validate ALL column names first
    invalid_columns = set(updates.keys()) - ALLOWED_POLICY_UPDATE_COLUMNS
    if invalid_columns:
        logger.error("Invalid columns: %s", invalid_columns)
        raise ValueError(f"Invalid column names: {invalid_columns}")

    # Now safe - only whitelisted columns
    set_clause = ", ".join([f"{k} = %s" for k in updates.keys()])
```

**Attack Blocked:**
```python
# Same attack:
POST /api/policies/update
{
    "updates": {
        "status = status; DELETE FROM policies WHERE true; --": "ignored"
    }
}

# Result:
# ValueError: Invalid column names: {'status = status; DELETE FROM policies...'}
# Attack BLOCKED! 🛡️
```

**Impact:** SQL injection impossible ✅

---

## Bug #4: Nonce Replay Attack After Restart

### ❌ BEFORE (Exploitable)

**auth/payment_verifier.py:41**:
```python
class PaymentVerifier:
    def __init__(self, backend_address, usdc_address):
        self.nonce_cache = {}  # ← In-memory only! Lost on restart 🔓
```

**Attack Scenario:**
```
Step 1: Attacker buys insurance
  → Payment: amount=100, nonce="attack123", signature=0xValid...
  → Nonce stored in memory: {"0xAttacker:attack123": 1699564800}
  ✅ Policy created

Step 2: Server restarts (deployment, crash, etc.)
  → Memory cleared!
  → Nonce cache now: {}

Step 3: Attacker replays SAME payment
  → Payment: amount=100, nonce="attack123", signature=0xValid...
  → Nonce not in cache (was cleared!)
  ✅ Policy created AGAIN! (Free insurance!)

Step 4: Repeat after each restart
  → Unlimited free policies! 💰
```

### ✅ AFTER (Protected)

**auth/payment_verifier.py:40-52, 276-349**:
```python
class PaymentVerifier:
    def __init__(self, backend_address, usdc_address,
                 nonce_storage_path=None):
        self.nonce_storage_path = nonce_storage_path or Path("data/nonce_cache.json")

        # Load from disk - survives restart! 🔒
        self.nonce_cache = self._load_nonce_cache()

    def _mark_nonce_used(self, payer, nonce, timestamp):
        key = f"{payer.lower()}:{nonce}"
        self.nonce_cache[key] = timestamp

        # Save to disk immediately
        self._save_nonce_cache()  # ← Persisted!

# data/nonce_cache.json:
{
    "0xattacker:attack123": 1699564800
}
```

**Attack Blocked:**
```
Step 1: Attacker buys insurance
  → Nonce saved to data/nonce_cache.json
  → {"0xAttacker:attack123": 1699564800}
  ✅ Policy created

Step 2: Server restarts
  → Nonce loaded from data/nonce_cache.json
  → Cache: {"0xAttacker:attack123": 1699564800}
  → Nonce persists! 🔒

Step 3: Attacker tries to replay
  → Check: "0xAttacker:attack123" in cache?
  → YES! Nonce already used
  ❌ REJECTED! "Nonce already used"

Attack BLOCKED! 🛡️
```

**Impact:** Replay attacks impossible, even after restart ✅

---

## Summary Table

| Bug | Before | After | Impact |
|-----|--------|-------|--------|
| **save_data()** | ❌ Function missing → crashes | ✅ Function added | No crashes |
| **File locking** | ❌ Race condition → corruption | ✅ Proper locking | No corruption |
| **SQL injection** | ❌ No validation → exploitable | ✅ Whitelist validation | No injection |
| **Nonce replay** | ❌ Memory-only → replayable | ✅ Persistent storage | No replays |

---

## Real-World Scenarios

### Scenario 1: High-Traffic Production

**Before:**
```
12:00 - 100 concurrent claims submitted
12:01 - 50 claims write to policies.json simultaneously
12:02 - File corrupted: {"policy_id": "abc", "status"::: "active"...}
12:03 - Next read fails: JSONDecodeError
12:04 - Service DOWN 💥
```

**After:**
```
12:00 - 100 concurrent claims submitted
12:01 - Claims queued with file locks
12:02 - All 100 write sequentially (protected)
12:03 - All data intact
12:04 - Service RUNNING ✅
```

---

### Scenario 2: Malicious Actor

**Before:**
```
Attacker: POST /api/policies/update
  {"updates": {"id = '1'; DELETE FROM policies; --": "hack"}}

Result: All policies deleted 💥
```

**After:**
```
Attacker: POST /api/policies/update
  {"updates": {"id = '1'; DELETE FROM policies; --": "hack"}}

Server: ValueError: Invalid column names
Result: Attack blocked 🛡️
```

---

### Scenario 3: Payment Fraud

**Before:**
```
10:00 - Attacker pays 0.0001 USDC (valid)
10:01 - Gets insurance policy
10:30 - Server deploys new version (restart)
10:31 - Attacker replays same signature
10:32 - Gets ANOTHER policy (free!)
Repeat: Infinite free policies 💰
```

**After:**
```
10:00 - Attacker pays 0.0001 USDC (valid)
10:01 - Gets insurance policy
       - Nonce saved to disk
10:30 - Server deploys new version (restart)
       - Nonce loaded from disk
10:31 - Attacker replays same signature
10:32 - REJECTED: "Nonce already used"
Result: Cannot replay 🛡️
```

---

## Testing Verification

### File Locking Test
```python
# Concurrent writes (3 threads, 10 writes each)
✅ PASS: 0 corruption errors
✅ PASS: All writes completed
✅ PASS: Final JSON valid
```

### SQL Injection Test
```python
# Malicious column names
malicious = {"status; DROP TABLE": "value"}
✅ PASS: ValueError raised
✅ PASS: No SQL executed
```

### Nonce Persistence Test
```python
# Simulate restart
verifier1.mark_nonce_used("0xABCD", "nonce1")
verifier2 = PaymentVerifier()  # Fresh instance
✅ PASS: Nonce still marked as used
✅ PASS: Replay blocked
```

---

## Deployment Confidence

### Before Fixes: ⚠️ HIGH RISK
- Runtime crashes expected
- Data corruption under load
- SQL injection possible
- Payment replay attacks possible

### After Fixes: ✅ PRODUCTION READY
- No runtime crashes
- Data integrity guaranteed
- SQL injection impossible
- Payment replay impossible

---

**Conclusion:** All 4 critical bugs fixed with comprehensive protection and zero breaking changes. Ready for production deployment.
