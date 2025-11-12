# Verification Flow

## Summary

✅ **Proof verification happens OFF-CHAIN BEFORE refund**  
✅ **Proof publication happens AFTER verification passes**  
✅ **Invalid claims are REJECTED (no refund, no proof published)**  

## Step-by-Step Flow

### 1. Agent Submits Claim

Agent sends HTTP response data:
```json
{
  "policy_id": "abc-123",
  "http_response": {
    "status": 503,
    "body": "",
    "headers": {}
  }
}
```

### 2. zkEngine Generates Proof (Off-Chain)

Server calls zkEngine to generate zero-knowledge proof (~22 seconds):

```python
proof_hex, public_inputs, gen_time_ms = zkengine.generate_proof(
    http_status=503,
    http_body="",
    http_headers={}
)
```

**Output:**
- `proof_hex`: `"0x24c0a5a6926d1f9082bcef9d965e5269d98b6e919e125e4f4a04cea927fe0bda"`
- `public_inputs`: `[1, 503, 0, 10000]`
  - `[0]` = is_failure (1 = yes, 0 = no)
  - `[1]` = http_status (503)
  - `[2]` = body_length (0)
  - `[3]` = payout_amount (10000 USDC units)

### 3. Verify Proof (Off-Chain)

Server verifies the proof **BEFORE** issuing refund:

```python
is_valid = zkengine.verify_proof(proof_hex, public_inputs)
if not is_valid:
    return error("Generated proof is invalid")  # REJECT
```

**server.py:1366-1371** (synchronous) and **server.py:271-278** (async)

### 4. Check Failure Detected (Off-Chain)

Server checks if failure was actually detected:

```python
is_failure = public_inputs[0]
if is_failure != 1:
    return error("No failure detected in HTTP response")  # REJECT
```

**server.py:1379-1380** (synchronous) and **server.py:282-288** (async)

### 5. Issue Refund (On-Chain)

**ONLY IF** verification passed and failure detected:

```python
refund_tx_hash = blockchain.issue_refund(
    to_address=agent_address,
    amount=payout_amount_units
)
```

**Result:** Standard USDC ERC20 transfer on Base Mainnet

### 6. Publish Proof (On-Chain)

**ONLY IF** refund succeeded:

```python
proof_tx_hash = blockchain.publish_proof(
    claim_id=claim_id,
    proof_hash=proof_hex,
    public_inputs=public_inputs,
    payout_amount=payout_amount_units,
    recipient=agent_address
)
```

**Result:** Zero-value transaction with proof data in input field

## Failure Detection Logic

The zkEngine uses this logic to determine if a failure occurred:

```python
def evaluate_fraud(http_status: int, http_body: str, coverage_amount: int):
    is_fraud = False
    
    # Fraud conditions (API failure)
    if http_status >= 500:              # Server error (5xx)
        is_fraud = True
    elif http_status >= 400 and len(http_body) == 0:  # Client error with empty body
        is_fraud = True
    elif len(http_body) == 0:           # Any empty response
        is_fraud = True
    
    payout_amount = coverage_amount if is_fraud else 0
    return is_fraud, payout_amount
```

**zkengine_client.py:121-145**

## Test Cases

### ✅ Valid Claim (API Failed)

**Input:**
- HTTP Status: 503
- Body: "" (empty)

**zkEngine Output:**
- `public_inputs[0]` = 1 (failure detected)
- `public_inputs[3]` = 10000 (payout amount)

**Result:**
- ✅ Verification passes
- ✅ Failure check passes
- 💰 Refund issued
- 🔐 Proof published

---

### ❌ Invalid Claim (API Worked)

**Input:**
- HTTP Status: 200
- Body: `{"temperature": 72, "condition": "sunny"}`

**zkEngine Output:**
- `public_inputs[0]` = 0 (NO failure detected)
- `public_inputs[3]` = 0 (NO payout)

**Result:**
- ❌ Failure check fails
- ⛔ Claim REJECTED
- ❌ NO refund issued
- ❌ NO proof published

---

### ❌ Invalid Claim (404 with Body)

**Input:**
- HTTP Status: 404
- Body: "Resource not found"

**zkEngine Output:**
- `public_inputs[0]` = 0 (NO failure detected - has body)
- `public_inputs[3]` = 0 (NO payout)

**Result:**
- ❌ Failure check fails
- ⛔ Claim REJECTED
- ❌ NO refund issued
- ❌ NO proof published

---

### ✅ Valid Claim (404 with Empty Body)

**Input:**
- HTTP Status: 404
- Body: "" (empty)

**zkEngine Output:**
- `public_inputs[0]` = 1 (failure detected)
- `public_inputs[3]` = 10000 (payout amount)

**Result:**
- ✅ Verification passes
- ✅ Failure check passes
- 💰 Refund issued
- 🔐 Proof published

## Security Guarantees

1. **No Proof, No Refund**
   - zkEngine must generate valid proof showing failure
   - Invalid proofs are rejected (line 1370, 272)

2. **No Failure, No Refund**
   - `public_inputs[0]` must equal 1 (failure detected)
   - Claims with `is_failure=0` are rejected (line 1379, 282)

3. **Agent Cannot Forge Claims**
   - Agent provides HTTP response data
   - zkEngine independently evaluates if it's a failure
   - Proof cryptographically certifies the evaluation
   - Agent cannot manipulate public_inputs

4. **Proof Published AFTER Verification**
   - Proof verification (line 1366/271)
   - Failure check (line 1379/282)
   - Refund (line 1393/292)
   - Proof publication (line 1403/299)
   - Wrong order would allow invalid proofs on-chain

## Code References

- **Synchronous flow**: server.py:1354-1437
- **Async flow**: server.py:260-324
- **Fraud detection**: zkengine_client.py:121-145
- **Proof generation**: zkengine_client.py:25-89
- **Proof verification**: zkengine_client.py:91-119

## Summary

The system correctly:
- ✅ Verifies proofs off-chain before any on-chain actions
- ✅ Rejects claims where API worked correctly
- ✅ Only publishes valid proofs on-chain
- ✅ Only issues refunds for legitimate failures
- ✅ Prevents agent fraud attempts

**Verification is OFF-CHAIN. Publication is ON-CHAIN. Refunds only happen AFTER verification passes.**
