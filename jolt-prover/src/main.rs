//! Jolt Claims Prover — real SNARK proof generation over ONNX model inference.
//!
//! Uses the Jolt Atlas zkML framework (https://github.com/ICME-Lab/jolt-atlas)
//! to generate and verify cryptographic proofs that an ONNX claim classifier
//! was executed correctly on given inputs.
//!
//! Usage:
//!   ./jolt_claims_prover <http_status> <body_length>
//!   ./jolt_claims_prover --verify <proof_json_file>

use ark_bn254::Fr;
use ark_serialize::{CanonicalDeserialize, CanonicalSerialize};
use base64::Engine as _;
use jolt_core::{poly::commitment::dory::DoryCommitmentScheme, transcripts::KeccakTranscript};
use onnx_tracer::{model, tensor::Tensor, ProgramIO};
use sha2::{Digest, Sha256};
use std::{env, fs, path::PathBuf, process, time::Instant};
use zkml_jolt_core::jolt::{JoltSNARK, JoltVerifierPreprocessing};

#[allow(clippy::upper_case_acronyms)]
type PCS = DoryCommitmentScheme;
type Snark = JoltSNARK<Fr, PCS, KeccakTranscript>;

/// JSON output format for proof generation.
#[derive(serde::Serialize)]
struct ProverOutput {
    /// Base64-encoded SNARK proof (ark-serialize compressed)
    proof: String,
    /// Base64-encoded ProgramIO (serde_json)
    program_io: String,
    /// [is_failure, http_status, body_length, payout_amount]
    public_inputs: Vec<i64>,
    /// SHA-256 of the ONNX model file
    model_hash: String,
    proof_system: String,
    /// Proving time in milliseconds
    proving_time_ms: u128,
    /// Proof size in bytes
    proof_size_bytes: usize,
}

/// JSON input for verification.
#[derive(serde::Deserialize)]
struct VerifyInput {
    proof: String,
    program_io: String,
    public_inputs: Vec<i64>,
    model_hash: String,
    #[serde(default)]
    proof_system: String,
}

/// JSON output for verification.
#[derive(serde::Serialize)]
struct VerifyOutput {
    valid: bool,
}

/// Max trace length for the prover (2^14 = 16384).
/// Sufficient for a small MLP (4->8->2).
const MAX_TRACE_LENGTH: usize = 1 << 14;

fn find_model_path() -> PathBuf {
    if let Ok(p) = env::var("ONNX_MODEL_PATH") {
        return PathBuf::from(p);
    }
    let candidates = [
        "models/claim_classifier.onnx",
        "../models/claim_classifier.onnx",
        "./claim_classifier.onnx",
    ];
    for c in &candidates {
        let p = PathBuf::from(c);
        if p.exists() {
            return p;
        }
    }
    PathBuf::from("models/claim_classifier.onnx")
}

fn compute_model_hash(path: &PathBuf) -> String {
    let data = fs::read(path).unwrap_or_default();
    let hash = Sha256::digest(&data);
    hex::encode(hash)
}

fn run_prove(http_status: i64, body_length: i64, coverage_amount_units: i64) {
    let start = Instant::now();
    let model_path = find_model_path();

    if !model_path.exists() {
        eprintln!("ONNX model not found at {:?}", model_path);
        process::exit(1);
    }

    let model_hash = compute_model_hash(&model_path);

    // Compute derived features (quantized to i32 for Jolt Atlas)
    let has_server_error: i32 = if (500..=504).contains(&http_status) { 1 } else { 0 };
    let is_empty_body: i32 = if body_length == 0 { 1 } else { 0 };

    // Build input tensor: [http_status, body_length, has_server_error, is_empty_body]
    let input_data: Vec<i32> = vec![
        http_status as i32,
        body_length as i32,
        has_server_error,
        is_empty_body,
    ];
    let input_tensor = Tensor::new(Some(&input_data), &[1, 4])
        .expect("Failed to create input tensor");

    // Leak model_path so closures get a 'static ref (Jolt Atlas requires Copy closures)
    let model_path_static: &'static PathBuf =
        Box::leak(Box::new(model_path.clone()));
    let model_fn = || model(model_path_static);

    eprintln!("Preprocessing ONNX model for SNARK...");
    let preprocessing = Snark::prover_preprocess(
        model_fn,
        MAX_TRACE_LENGTH,
    );

    eprintln!("Generating Jolt Atlas SNARK proof...");
    let prove_start = Instant::now();
    let (snark, program_io, _debug_info) = Snark::prove(
        &preprocessing,
        model_fn,
        &input_tensor,
    );
    let prove_time = prove_start.elapsed();
    eprintln!("Proof generated in {:?}", prove_time);

    // Verify locally before outputting (sanity check)
    let verifier_preprocessing: JoltVerifierPreprocessing<Fr, PCS> = (&preprocessing).into();
    snark.clone()
        .verify(&verifier_preprocessing, program_io.clone(), None)
        .expect("Self-verification failed — this is a bug");
    eprintln!("Self-verification passed");

    // Run model to get classification result for public_inputs
    let model_instance = model(&model_path);
    let result = model_instance.forward(&[input_tensor.clone()])
        .expect("Model forward pass failed");
    let output = &result.outputs[0];

    // Get predicted class: index 0 = no failure, index 1 = failure
    let (pred_idx, _max_val) = output
        .iter()
        .enumerate()
        .max_by(|a, b| a.1.partial_cmp(b.1).unwrap())
        .unwrap_or((0, &0));

    let is_failure: i64 = pred_idx as i64;
    let payout_amount: i64 = if is_failure == 1 { coverage_amount_units } else { 0 };

    // Serialize proof using ark-serialize (canonical compressed form)
    let mut proof_buffer = Vec::new();
    snark
        .serialize_compressed(&mut proof_buffer)
        .expect("Proof serialization failed");
    let proof_b64 = base64::engine::general_purpose::STANDARD.encode(&proof_buffer);

    // Serialize ProgramIO using serde_json
    let program_io_json = serde_json::to_string(&program_io)
        .expect("ProgramIO serialization failed");
    let program_io_b64 = base64::engine::general_purpose::STANDARD
        .encode(program_io_json.as_bytes());

    let total_time = start.elapsed();

    let output = ProverOutput {
        proof: proof_b64,
        program_io: program_io_b64,
        public_inputs: vec![is_failure, http_status, body_length, payout_amount],
        model_hash,
        proof_system: "jolt-atlas-snark".to_string(),
        proving_time_ms: total_time.as_millis(),
        proof_size_bytes: proof_buffer.len(),
    };

    println!("{}", serde_json::to_string(&output).unwrap());
}

fn run_verify(proof_file: &str) {
    let content = fs::read_to_string(proof_file).unwrap_or_else(|e| {
        eprintln!("Failed to read proof file {}: {}", proof_file, e);
        process::exit(1);
    });

    let input: VerifyInput = serde_json::from_str(&content).unwrap_or_else(|e| {
        eprintln!("Failed to parse proof JSON: {}", e);
        process::exit(1);
    });

    // Validate basic structure
    if input.proof_system != "jolt-atlas-snark" {
        eprintln!("Unknown proof system: {}", input.proof_system);
        let output = VerifyOutput { valid: false };
        println!("{}", serde_json::to_string(&output).unwrap());
        return;
    }

    if input.public_inputs.len() != 4 {
        eprintln!("Invalid public_inputs length: {}", input.public_inputs.len());
        let output = VerifyOutput { valid: false };
        println!("{}", serde_json::to_string(&output).unwrap());
        return;
    }

    // Check model hash matches current model
    let model_path = find_model_path();
    let current_model_hash = compute_model_hash(&model_path);
    if current_model_hash != input.model_hash {
        eprintln!(
            "Model hash mismatch: proof={}, current={}",
            input.model_hash, current_model_hash
        );
        let output = VerifyOutput { valid: false };
        println!("{}", serde_json::to_string(&output).unwrap());
        return;
    }

    // Deserialize the SNARK proof
    let proof_bytes = match base64::engine::general_purpose::STANDARD.decode(&input.proof) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("Failed to decode proof base64: {}", e);
            let output = VerifyOutput { valid: false };
            println!("{}", serde_json::to_string(&output).unwrap());
            return;
        }
    };

    let snark = match Snark::deserialize_compressed(proof_bytes.as_slice()) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("Failed to deserialize SNARK proof: {}", e);
            let output = VerifyOutput { valid: false };
            println!("{}", serde_json::to_string(&output).unwrap());
            return;
        }
    };

    // Deserialize ProgramIO
    let program_io_bytes = match base64::engine::general_purpose::STANDARD
        .decode(&input.program_io)
    {
        Ok(b) => b,
        Err(e) => {
            eprintln!("Failed to decode program_io base64: {}", e);
            let output = VerifyOutput { valid: false };
            println!("{}", serde_json::to_string(&output).unwrap());
            return;
        }
    };

    let program_io_json = match String::from_utf8(program_io_bytes) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("Invalid UTF-8 in program_io: {}", e);
            let output = VerifyOutput { valid: false };
            println!("{}", serde_json::to_string(&output).unwrap());
            return;
        }
    };

    let program_io: ProgramIO = match serde_json::from_str(&program_io_json) {
        Ok(io) => io,
        Err(e) => {
            eprintln!("Failed to deserialize ProgramIO: {}", e);
            let output = VerifyOutput { valid: false };
            println!("{}", serde_json::to_string(&output).unwrap());
            return;
        }
    };

    // Reconstruct verifier preprocessing from the model
    let model_path_static: &'static PathBuf =
        Box::leak(Box::new(model_path.clone()));
    let preprocessing = Snark::prover_preprocess(
        || model(model_path_static),
        MAX_TRACE_LENGTH,
    );
    let verifier_preprocessing: JoltVerifierPreprocessing<Fr, PCS> = (&preprocessing).into();

    // Verify the SNARK proof
    eprintln!("Verifying Jolt Atlas SNARK proof...");
    let verify_start = Instant::now();
    let valid = snark
        .verify(&verifier_preprocessing, program_io, None)
        .is_ok();
    let verify_time = verify_start.elapsed();
    eprintln!("Verification completed in {:?}: {}", verify_time, if valid { "VALID" } else { "INVALID" });

    let output = VerifyOutput { valid };
    println!("{}", serde_json::to_string(&output).unwrap());
}

fn main() {
    let args: Vec<String> = env::args().collect();

    if args.len() < 2 {
        eprintln!("Jolt Atlas Claims Prover — real SNARK proofs over ONNX model inference");
        eprintln!();
        eprintln!("Usage:");
        eprintln!("  {} <http_status> <body_length> <coverage_amount_units>  Generate proof", args[0]);
        eprintln!("  {} --verify <proof_json_file>                              Verify proof", args[0]);
        process::exit(1);
    }

    if args[1] == "--verify" {
        if args.len() < 3 {
            eprintln!("Usage: {} --verify <proof_json_file>", args[0]);
            process::exit(1);
        }
        run_verify(&args[2]);
    } else {
        if args.len() < 4 {
            eprintln!("Usage: {} <http_status> <body_length> <coverage_amount_units>", args[0]);
            process::exit(1);
        }
        let http_status: i64 = args[1].parse().unwrap_or_else(|_| {
            eprintln!("Invalid http_status: {}", args[1]);
            process::exit(1);
        });
        let body_length: i64 = args[2].parse().unwrap_or_else(|_| {
            eprintln!("Invalid body_length: {}", args[2]);
            process::exit(1);
        });
        let coverage_amount_units: i64 = args[3].parse().unwrap_or_else(|_| {
            eprintln!("Invalid coverage_amount_units: {}", args[3]);
            process::exit(1);
        });
        run_prove(http_status, body_length, coverage_amount_units);
    }
}

mod hex {
    pub fn encode(data: impl AsRef<[u8]>) -> String {
        data.as_ref().iter().map(|b| format!("{:02x}", b)).collect()
    }
}
