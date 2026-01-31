# Verification Flow

## Summary

- **Proof generation uses Jolt Atlas zkML — real SNARK proofs over ONNX model inference**
- **Proof verification happens OFF-CHAIN (locally) BEFORE refund**
- **Refund is issued BEFORE the claim is persisted** (refund-before-persist)
- **Policy is atomically marked "claimed" to prevent race conditions**
- **Full proof data stored locally in claim record for auditability**
- **Invalid claims are REJECTED (no refund)**
- **No on-chain proof publication -- saves gas, verification is local**

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

Claim authentication is always required (x402 V2 payment via `PAYMENT-SIGNATURE` header).

### 2. Atomic Policy Claim (Prevents Race Conditions)

Before any proof generation, the server atomically marks the policy as "claimed":

```python
policy = database.claim_policy(policy_id)
if policy is None:
    return error("Policy cannot be claimed")  # already claimed, expired, or not found
```

### 3. Jolt Atlas Generates SNARK Proof (Off-Chain)

#### Server-Side Re-fetch (v2.3.0)

Before proof generation, the server independently re-fetches the `merchant_url` stored
on the policy to verify the claimed failure:

```python
server_status, server_body = refetch_merchant_url(policy.merchant_url)
```

The `server_verified` and `server_http_status` fields in the response indicate
whether the server confirmed the failure independently.

#### SNARK Proof Generation

Server calls the Jolt Atlas prover binary (3-argument interface, v2.3.0) to generate
a SNARK proof of correct ONNX model inference:

```python
proof_b64, public_inputs, gen_time_ms = proof_client.generate_proof(
    http_status=503,
    http_body="",
    http_headers={},
    coverage_amount_units=10000
)
```

The prover binary (`jolt-atlas/jolt_claims_prover`) accepts 3 positional arguments:
```
./jolt_claims_prover <http_status> <body_length> <coverage_amount_units>
```

Steps:
1. Loads the ONNX claim classifier model (`models/claim_classifier.onnx`)
2. Computes derived features: `has_server_error`, `is_empty_body`
3. Runs inference through the MLP (4->8->2)
4. Uses `coverage_amount_units` to compute payout amount in public inputs
5. Generates a SNARK proof committing to the execution trace
6. Outputs JSON with base64-encoded proof, public inputs, and model hash

**Output:**
- `proof`: Base64-encoded SNARK proof (ark-serialize compressed, typically hundreds of KB)
- `program_io`: Base64-encoded ProgramIO JSON (Jolt execution trace I/O)
- `public_inputs`: `[1, 503, 0, 10000]`
  - `[0]` = is_failure (1 = yes, 0 = no) — model classification
  - `[1]` = http_status (503)
  - `[2]` = body_length (0)
  - `[3]` = payout_amount (10000 USDC units)
- `model_hash`: SHA-256 of the ONNX model file
- `proof_system`: `"jolt-atlas-snark"`

### 4. Verify Proof (Off-Chain)

Server verifies the proof **BEFORE** issuing refund:

```python
is_valid = proof_client.verify_proof(proof_b64, public_inputs)
if not is_valid:
    database.update_policy(policy_id, {'status': 'active'})  # revert
    return error("Generated proof is invalid")  # REJECT
```

Verification calls `jolt_claims_prover --verify <proof.json>` which:
- Checks the model hash matches the current ONNX model
- Deserializes the SNARK proof (ark-serialize CanonicalDeserialize)
- Deserializes ProgramIO (serde_json)
- Reconstructs verifier preprocessing from the ONNX model
- Calls `snark.verify(&verifier_preprocessing, program_io, None)` — the real Jolt SNARK verifier
- This is a **cryptographic verification**, not re-execution — the verifier checks polynomial commitments

### 5. Check Failure Detected (Off-Chain)

```python
is_failure = public_inputs[0]
if is_failure != 1:
    database.update_policy(policy_id, {'status': 'active'})  # revert
    return error("No failure detected in HTTP response")  # REJECT
```

### 6. Issue Refund (On-Chain) -- BEFORE Persisting Claim

**ONLY IF** verification passed and failure detected:

```python
try:
    refund_tx_hash = blockchain.issue_refund(
        to_address=agent_address,
        amount=payout_amount_units
    )
except Exception as e:
    database.create_claim(claim_id, {..., "status": "refund_failed", "error": str(e)})
    return error("Refund failed")
```

### 7. Persist Claim Record (Database)

Only after refund succeeds:

```python
database.create_claim(claim_id, {
    ...,
    "status": "paid",
    "refund_tx_hash": refund_tx_hash,
    "paid_at": iso_utc_now(),
})
```

## ONNX Claim Classifier Model

The claim classifier is a scikit-learn MLPClassifier (4→8→2) exported to ONNX:

**Input features** (quantized to float32):
- `http_status` (100-599)
- `body_length` (0-500000)
- `has_server_error` (0 or 1) — status in 500-504
- `is_empty_body` (0 or 1)

**Output:** Binary classification — `is_failure` (0 or 1)

The model is trained on synthetic data matching the previous rule-based logic
(HTTP 500-504 or empty body = failure). The ONNX model is deterministic and
its SHA-256 hash is embedded in every proof for auditability.

## Security Guarantees

1. **No Double Claims** -- `claim_policy()` atomically marks policy as "claimed"
2. **No Phantom Payments** -- Refund issued before claim persisted
3. **Model Integrity** -- Model hash in proof must match current ONNX file
4. **Deterministic Proofs** -- Same inputs always produce same SNARK proof
5. **Payout Cap** -- `public_inputs[3]` must not exceed `MAX_COVERAGE_USDC`
6. **Payment Signature Verification** -- `FacilitatorPaymentVerifier` calls x402.org
7. **Nonce Replay Prevention** -- Database-backed nonce storage
8. **Claim Authentication** -- Always required (x402 V2 payment)

## Code References

- **Atomic claim**: `database.py` `claim_policy()`
- **Proof generation**: `proof_client.py` `generate_proof()` -> `subprocess.run(jolt_claims_prover)`
- **Proof verification**: `proof_client.py` `verify_proof()` -> `subprocess.run(jolt_claims_prover --verify)`
- **ONNX model**: `models/claim_classifier.onnx` (trained by `models/train_claim_model.py`)
- **Rust prover**: `jolt-prover/src/main.rs` (loads ONNX via tract, builds SNARK commitment)
- **Refund**: `blockchain.py` `_send_refund_transaction()` -> web3 ERC-20 transfer
- **Claims flow**: `blueprints/claims.py`
- **Verify endpoint**: `blueprints/verify.py`
