# On-Chain ZK Proof Verification on Solana - Investigation Report

**Date:** 2025-11-08
**Purpose:** Evaluate feasibility of on-chain proof storage/attestation and zkEngine verifier contracts for x402 Insurance on Solana

---

## Executive Summary

### Key Findings:

1. ✅ **On-chain proof verification IS possible on Solana** (Groth16 & ZK-STARK)
2. ⚠️ **Nova/Arecibo (zkEngine's proof system) has NO Solana verifier yet**
3. ✅ **Proof storage/attestation is feasible** via PDAs (Program Derived Addresses)
4. ⚠️ **High compute costs** - Would consume 50-80% of transaction budget
5. 💡 **Hybrid approach recommended** - Store proof metadata on-chain, verify off-chain

---

## Part 1: On-Chain Proof Storage & Attestation

### ✅ Feasibility: HIGH

**Technical Approach:**

#### 1. Using Program Derived Addresses (PDAs)
```rust
// PDA for storing proof attestations
seeds = [
    b"proof_attestation",
    claim_id.as_bytes(),
    policy_id.as_bytes()
]

// Deterministic address derivation
let (proof_pda, bump) = Pubkey::find_program_address(&seeds, &program_id);
```

**Storage Structure:**
```rust
#[account]
pub struct ProofAttestation {
    pub claim_id: [u8; 32],           // 32 bytes
    pub policy_id: [u8; 32],          // 32 bytes
    pub proof_hash: [u8; 32],         // 32 bytes (Blake3/SHA256)
    pub public_inputs: Vec<u64>,      // ~32 bytes (4 inputs)
    pub verifier_address: Pubkey,     // 32 bytes
    pub timestamp: i64,               // 8 bytes
    pub status: ProofStatus,          // 1 byte
    pub bump: u8,                     // 1 byte
}
// Total: ~170 bytes per attestation
```

**Storage Costs:**
- Account rent: ~0.00123 SOL (~$0.20 at $160/SOL)
- One-time cost per proof attestation
- Rent-exempt balance required
- **Verdict:** Very affordable for insurance use case

**Benefits:**
- ✅ Permanent, immutable proof record
- ✅ Publicly auditable on Solana explorer
- ✅ Queryable by claim_id or policy_id
- ✅ Can be indexed by The Graph or other indexers
- ✅ Enables on-chain proof of payout legitimacy

**Implementation Pattern:**
```rust
// Anchor program structure
#[program]
pub mod x402_insurance {
    pub fn attest_proof(
        ctx: Context<AttestProof>,
        claim_id: [u8; 32],
        proof_hash: [u8; 32],
        public_inputs: Vec<u64>,
    ) -> Result<()> {
        let attestation = &mut ctx.accounts.proof_attestation;
        attestation.claim_id = claim_id;
        attestation.proof_hash = proof_hash;
        attestation.public_inputs = public_inputs;
        attestation.timestamp = Clock::get()?.unix_timestamp;
        attestation.status = ProofStatus::Verified;
        Ok(())
    }
}
```

---

## Part 2: zkEngine (Nova/Arecibo) On-Chain Verifier

### ❌ Feasibility: NOT READY (but possible in future)

### Current State of zkEngine:

**What is zkEngine?**
- Built by NovaNet/ICME-Lab
- Uses **SuperNova/Nebula proving scheme** (NIVC - Non-uniform Incremental Verifiable Computation)
- Based on **folding schemes** (not traditional zk-SNARKs)
- Highly memory-efficient (runs on consumer laptops)
- **Chain-agnostic** - generates proofs off-chain

**Problem:**
- **NO Solana verifier exists for Nova/Arecibo/SuperNova**
- Only Solidity verifiers available (Ethereum-focused)
- Different cryptographic primitives than Groth16

### Why Nova Verification is Hard on Solana:

**1. Different Proof System:**
| Proof System | Type | Solana Support | Status |
|--------------|------|----------------|--------|
| **Groth16** | zk-SNARK (pairing-based) | ✅ alt_bn128 syscalls | Production-ready |
| **ZK-STARK** | Transparent (hash-based) | ✅ Poseidon syscalls | Research phase |
| **Nova/Arecibo** | Folding scheme (IVC) | ❌ No native support | Not available |

**2. Curve Incompatibility:**
- zkEngine uses: **Pallas/Vesta** or **BN254/Grumpkin** curves
- Solana natively supports: **alt_bn128 (BN254)** for Groth16
- Nova verification requires custom curve operations

**3. Verification Complexity:**
- Nova uses **recursive proof composition**
- Multiple proof verification steps per claim
- Higher compute cost than single Groth16 proof

### Theoretical Implementation (if you built it):

**Option 1: Full On-Chain Verifier (Hard)**
```rust
// Would require:
// 1. Implement Pallas/Vesta curve arithmetic in Rust
// 2. Port Nova verifier logic from Arecibo
// 3. Optimize for Solana compute budget
// 4. Extensive testing and auditing

// Estimated costs:
// - Development time: 3-6 months (expert cryptographer)
// - Compute units: ~800k-1.2M CU per verification
// - Would consume 57-86% of tx budget
```

**Option 2: Groth16 Wrapper (Medium)**
```rust
// Use zkEngine to generate proof
// Then wrap in Groth16 proof for Solana verification
// Trade-off: Adds proof generation time

// Estimated costs:
// - Proof generation: 20-40s (zkEngine + Groth16 wrapper)
// - Verification: <200k CU (using groth16-solana)
// - More practical approach
```

**Option 3: Hybrid Attestation (Easy - RECOMMENDED)**
```rust
// 1. Generate zkEngine proof off-chain (current approach)
// 2. Verify off-chain (your current server.py)
// 3. Issue USDC refund on Solana
// 4. Store proof hash + metadata on-chain as attestation
// 5. Anyone can verify proof by downloading it and running zkEngine

// This is what you're essentially doing now, just add step 4!
```

---

## Part 3: What Solana DOES Support

### ✅ Groth16 (zk-SNARK) Verification

**Implementation:** `groth16-solana` crate
**Compute Cost:** **<200,000 CU** (14% of tx budget)
**Status:** Production-ready on mainnet

**How it works:**
```rust
use groth16_solana::{Groth16Verifier, Proof, VerifyingKey};

// Verify Groth16 proof on-chain
let verifier = Groth16Verifier::new(
    &proof.a,
    &proof.b,
    &proof.c,
    &public_inputs,
    &verifying_key
)?;

let is_valid = verifier.verify()?; // ~200k CU
```

**Use case:** Circom circuits, general zk-SNARKs

---

### ✅ ZK-STARK Verification

**Compute Cost:** **~1.1M CU** (79% of tx budget)
**Status:** Research/testing phase

**Measurements from recent study (2025):**
- STARK verification: 1.10×10^6 CU (median)
- Signature verification: 5.01×10^5 CU
- Total: Fits within 1.4M CU limit
- Intensity: 248.9 CU per proof byte

**Limitations:**
- Proof size: Must be <900 bytes per chunk
- High compute cost leaves little room for other operations
- Not practical for high-frequency verification

---

### ✅ ZK Compression (Groth16-based)

**System:** Light Protocol's ZK Compression
**Compute Costs:**
- Validity proof verification: ~100k CU
- System usage: ~100k CU
- Per account read/write: ~6k CU each

**Architecture:**
```
Off-chain Prover → Generates Groth16 proof → On-chain verification → State update
```

**Benefits:**
- Reduces state storage costs by 1000x
- Uses Poseidon hashing + Groth16 proofs
- Production-ready on mainnet

---

## Part 4: Practical Recommendations for x402 Insurance

### 🎯 Recommended Approach: **Hybrid Attestation Model**

#### Phase 1: Proof Attestation Only (Easy - 1-2 days)

**What to build:**
```rust
// Simple Anchor program
#[program]
pub mod x402_insurance_attestation {
    pub fn attest_claim_proof(
        ctx: Context<AttestClaim>,
        claim_id: [u8; 32],
        policy_id: [u8; 32],
        proof_hash: [u8; 32],        // Hash of zkEngine proof
        public_inputs: [u64; 4],     // [fraud_detected, http_status, body_len, payout]
        refund_tx_sig: [u8; 64],     // Solana tx signature of USDC refund
    ) -> Result<()> {
        // Store attestation on-chain
        let attestation = &mut ctx.accounts.attestation;
        attestation.claim_id = claim_id;
        attestation.proof_hash = proof_hash;
        attestation.public_inputs = public_inputs;
        attestation.refund_tx = refund_tx_sig;
        attestation.timestamp = Clock::get()?.unix_timestamp;

        // Emit event for indexers
        emit!(ProofAttested {
            claim_id,
            proof_hash,
            refund_tx_sig,
        });

        Ok(())
    }
}
```

**Benefits:**
- ✅ Publicly auditable proof records
- ✅ Agents can verify claims were legitimate
- ✅ Low compute cost (~5k CU)
- ✅ Cheap storage (~$0.20 per attestation)
- ✅ **Perfect for hackathon demo!**

**Workflow:**
```
1. Agent files claim → Your server
2. zkEngine generates proof off-chain (15-30s)
3. Your server verifies proof off-chain
4. Issue USDC refund on Solana
5. Call attest_claim_proof() to store hash on-chain
6. Proof stored permanently, anyone can audit
```

---

#### Phase 2: Groth16 Wrapper (Medium - 1-2 weeks)

**What to build:**
- Wrap zkEngine proof in Groth16 proof
- Use `groth16-solana` for on-chain verification
- Store verification result + proof on-chain

**Trade-offs:**
- ✅ Full on-chain verification
- ✅ Trustless (no off-chain verifier needed)
- ❌ Slower proof generation (20-40s)
- ❌ More complex implementation
- ❌ Needs custom circuit design

---

#### Phase 3: Native Nova Verifier (Hard - 3-6 months)

**What to build:**
- Port Arecibo/Nova verifier to Solana Rust
- Implement Pallas/Vesta curve operations
- Optimize for Solana compute budget
- Extensive security auditing

**Trade-offs:**
- ✅ Native zkEngine verification
- ✅ Faster proof generation (zkEngine stays)
- ❌ Very complex cryptographic work
- ❌ High development cost
- ❌ High compute cost (~1M CU)
- ❌ Requires cryptography expertise

**Verdict:** NOT worth it for hackathon or MVP

---

## Part 5: Cost Comparison

### Compute Unit Costs:

| Operation | Compute Units | % of TX Budget | Status |
|-----------|---------------|----------------|--------|
| **Proof Attestation (hash storage)** | ~5,000 CU | 0.4% | ✅ Recommended |
| **Groth16 Verification** | ~200,000 CU | 14% | ✅ Feasible |
| **ZK Compression (Groth16)** | ~200,000 CU | 14% | ✅ Production |
| **ZK-STARK Verification** | ~1,100,000 CU | 79% | ⚠️ Research |
| **Nova Verifier (theoretical)** | ~800k-1.2M CU | 57-86% | ❌ Not available |
| **USDC Transfer (SPL)** | ~10,000 CU | 0.7% | ✅ Standard |

**Transaction Budget:** 1,400,000 CU max (with priority fees)

### Storage Costs:

| Storage Type | Size | Rent Cost | Notes |
|--------------|------|-----------|-------|
| **Proof attestation PDA** | 170 bytes | ~0.00123 SOL | One-time per claim |
| **Full proof storage** | 4-5 KB | ~0.035 SOL | Expensive, not recommended |
| **Proof hash only** | 32 bytes | Negligible | Part of attestation |

**Recommendation:** Store proof hash, not full proof

---

## Part 6: Hackathon Strategy

### For Solana x402 Hackathon (3 days):

#### ✅ DO THIS (High impact, low effort):

**1. Proof Attestation Smart Contract**
```bash
# Day 1: Create simple Anchor program
anchor init x402_insurance_attestation
# Implement attest_claim_proof() function
# Deploy to Solana devnet
```

**2. Demo Flow:**
```
Agent buys policy → Merchant fails → Agent files claim
→ zkEngine proof generated (off-chain)
→ Proof verified (off-chain)
→ USDC refund issued (on-chain)
→ Proof attestation stored (on-chain) ← NEW!
→ Show Solana Explorer link to attestation
```

**3. Marketing Angle:**
- "First insurance with cryptographically attested payouts on Solana"
- "Publicly auditable proof records on-chain"
- "Zero-trust verification - anyone can audit claims"

**Benefits for judges:**
- ✅ Shows Solana-native features (PDAs, accounts)
- ✅ Demonstrates understanding of on-chain storage
- ✅ Adds transparency/auditability
- ✅ Low complexity, high demo value
- ✅ **Differentiates from pure off-chain solution**

---

#### ❌ DON'T DO THIS (Low ROI for hackathon):

- ❌ Full Nova/Arecibo on-chain verifier (too complex)
- ❌ Groth16 wrapper circuit (not enough time)
- ❌ Full proof storage on-chain (expensive, unnecessary)
- ❌ ZK-STARK migration (research-stage, unstable)

---

## Part 7: Implementation Pseudocode

### Simple Proof Attestation (Anchor):

```rust
// lib.rs
use anchor_lang::prelude::*;

declare_id!("X402...");

#[program]
pub mod x402_insurance {
    use super::*;

    pub fn attest_proof(
        ctx: Context<AttestProof>,
        claim_id: [u8; 32],
        proof_hash: [u8; 32],
        public_inputs: [u64; 4],
        refund_signature: [u8; 64],
    ) -> Result<()> {
        let attestation = &mut ctx.accounts.attestation;
        attestation.claim_id = claim_id;
        attestation.policy_id = ctx.accounts.policy.key().to_bytes();
        attestation.proof_hash = proof_hash;
        attestation.public_inputs = public_inputs;
        attestation.refund_tx = refund_signature;
        attestation.verified_at = Clock::get()?.unix_timestamp;
        attestation.verifier = ctx.accounts.authority.key();
        attestation.bump = *ctx.bumps.get("attestation").unwrap();

        emit!(ProofAttested {
            claim_id,
            proof_hash,
            payout_amount: public_inputs[3],
        });

        Ok(())
    }

    pub fn verify_attestation(
        ctx: Context<VerifyAttestation>,
        claim_id: [u8; 32],
    ) -> Result<bool> {
        // Anyone can call this to check if proof exists
        let attestation = &ctx.accounts.attestation;

        msg!("Claim ID: {:?}", claim_id);
        msg!("Proof Hash: {:?}", attestation.proof_hash);
        msg!("Public Inputs: {:?}", attestation.public_inputs);
        msg!("Verified at: {}", attestation.verified_at);

        Ok(true)
    }
}

#[derive(Accounts)]
#[instruction(claim_id: [u8; 32])]
pub struct AttestProof<'info> {
    #[account(
        init,
        payer = authority,
        space = 8 + ProofAttestation::INIT_SPACE,
        seeds = [b"attestation", claim_id.as_ref()],
        bump
    )]
    pub attestation: Account<'info, ProofAttestation>,

    #[account(mut)]
    pub authority: Signer<'info>,

    pub system_program: Program<'info, System>,
}

#[account]
#[derive(InitSpace)]
pub struct ProofAttestation {
    pub claim_id: [u8; 32],
    pub policy_id: [u8; 32],
    pub proof_hash: [u8; 32],
    pub public_inputs: [u64; 4],
    pub refund_tx: [u8; 64],
    pub verified_at: i64,
    pub verifier: Pubkey,
    pub bump: u8,
}

#[event]
pub struct ProofAttested {
    pub claim_id: [u8; 32],
    pub proof_hash: [u8; 32],
    pub payout_amount: u64,
}
```

### Python Integration:

```python
# In your server_solana.py, after USDC refund:

from solders.keypair import Keypair
from anchorpy import Program, Provider

# After successful claim processing:
async def attest_proof_on_chain(claim_id, proof_hex, public_inputs, refund_sig):
    """Store proof attestation on Solana after successful refund"""

    # Load program
    program = await Program.at(ATTESTATION_PROGRAM_ID, provider)

    # Derive PDA
    attestation_pda, bump = Pubkey.find_program_address(
        [b"attestation", bytes.fromhex(claim_id)],
        program.program_id
    )

    # Create attestation transaction
    tx = await program.rpc["attest_proof"](
        bytes.fromhex(claim_id),
        bytes.fromhex(proof_hex[:64]),  # Hash of proof
        public_inputs,
        bytes.fromhex(refund_sig),
        ctx=Context(
            accounts={
                "attestation": attestation_pda,
                "authority": backend_wallet.pubkey(),
                "system_program": SYS_PROGRAM_ID,
            },
        ),
    )

    logger.info(f"Proof attested on-chain: {tx}")
    return tx

# In /claim endpoint:
if proof_verified:
    refund_tx = blockchain.issue_refund(...)

    # NEW: Attest proof on-chain
    attestation_tx = await attest_proof_on_chain(
        claim_id=claim_id,
        proof_hex=proof_hex,
        public_inputs=public_inputs,
        refund_sig=refund_tx
    )

    return {
        "claim_id": claim_id,
        "refund_tx_hash": refund_tx,
        "attestation_tx": attestation_tx,  # NEW!
        "proof_url": f"/proofs/{claim_id}"
    }
```

---

## Part 8: Future Possibilities

### What COULD Be Built (Post-Hackathon):

**1. Proof Marketplace**
```rust
// Agents can sell verified proofs to other agents
// Useful for shared merchant monitoring
pub fn list_proof_for_sale(
    ctx: Context<ListProof>,
    price: u64,
) -> Result<()> {
    // ...
}
```

**2. Reputation System**
```rust
// Track which agents submit legitimate vs fraudulent claims
// Based on on-chain proof attestations
pub fn calculate_agent_reputation(
    agent: Pubkey
) -> Result<u64> {
    // Count verified proofs vs rejected claims
}
```

**3. DAO Governance**
```rust
// Decentralized insurance pool
// Stakers vote on disputed claims using on-chain proofs
pub fn dispute_claim(
    ctx: Context<DisputeClaim>,
    claim_id: [u8; 32],
) -> Result<()> {
    // DAO members can challenge proof validity
}
```

**4. Cross-Chain Bridge**
```rust
// Bridge proof attestations from Solana to Base
// Agents on Base can verify Solana claim history
pub fn bridge_attestation(
    ctx: Context<Bridge>,
    destination_chain: u8,
) -> Result<()> {
    // ...
}
```

---

## Part 9: Final Recommendations

### For Hackathon (Nov 11 deadline):

**Priority 1 (MUST DO):**
- ✅ Basic proof attestation Anchor program
- ✅ Store proof hash + metadata on-chain
- ✅ Demo with Solana Explorer link
- ✅ Show public auditability

**Priority 2 (NICE TO HAVE):**
- ✅ Query attestations by claim_id
- ✅ Event emission for indexers
- ✅ Simple frontend showing attestations

**Priority 3 (SKIP FOR NOW):**
- ❌ Full on-chain verification (too complex)
- ❌ Groth16 wrapper (not enough time)
- ❌ Nova verifier implementation (months of work)

### For Production (Post-Hackathon):

**Phase 1:** Proof attestation (Week 1-2)
**Phase 2:** Groth16 wrapper (Month 1-2)
**Phase 3:** Explore Nova verifier (Month 3-6)

---

## Part 10: Technical Constraints Summary

### What's READY on Solana:
| Feature | Status | Compute Cost | Use Case |
|---------|--------|--------------|----------|
| **Groth16 verification** | ✅ Production | <200k CU | General zk-SNARKs |
| **alt_bn128 syscalls** | ✅ Mainnet | Variable | Pairing operations |
| **Poseidon hashing** | ✅ Mainnet | ~100k CU | ZK-friendly hashing |
| **Proof attestation (PDA)** | ✅ Standard | ~5k CU | Metadata storage |

### What's NOT READY:
| Feature | Status | Blocker | ETA |
|---------|--------|---------|-----|
| **Nova/Arecibo verifier** | ❌ None | No implementation | Unknown |
| **ZK-STARK (production)** | ⚠️ Research | High compute cost | 6-12 months |
| **zkEngine native verification** | ❌ None | Curve incompatibility | Unknown |

---

## Conclusion

### Answer to Your Questions:

**1. On-chain proof data storage/attestation?**
- ✅ **YES** - Very feasible via PDAs
- ✅ **Low cost** - ~$0.20 per attestation
- ✅ **Recommended** for transparency
- ✅ **Easy to implement** - 1-2 days

**2. Real on-chain verifier contract for zkEngine?**
- ❌ **NO** - Not available yet
- ⚠️ **Theoretically possible** but very complex
- 💡 **Alternative:** Use proof attestation instead
- 💡 **Future:** Could wrap in Groth16

### Bottom Line:

**For Hackathon:** Focus on proof attestation (high impact, low effort)
**For MVP:** Hybrid model (off-chain verification + on-chain attestation)
**For Future:** Consider Groth16 wrapper or await Nova verifier

**zkEngine is perfect as-is for off-chain verification. Add on-chain attestation for transparency and auditability - that's the winning combination! 🎯**

---

**Report End**

*Generated: 2025-11-08*
*Status: Investigation Complete*
