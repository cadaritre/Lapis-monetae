use kaspa_hashes::{Hash, ZERO_HASH};
use kaspa_math::Uint256;
use kaspa_muhash::EMPTY_MUHASH;
use kaspa_utils::hex::ToHex;

use kaspa_consensus_core::{
    config::bps::TenBps,
    header::Header,
    merkle::calc_hash_merkle_root,
    subnets::SUBNETWORK_ID_COINBASE,
    tx::Transaction,
    BlueWorkType,
};

const GENESIS_VERSION: u16 = 0;
const DAA_SCORE: u64 = 0;
const GENESIS_BITS_EASY: u32 = 0x207fffff; // max target (2^255 - 1)

fn main() {
    let payloads = [
        ("mainnet", payload_for("lapis-monetae-mainnet", &[])),
        ("testnet", payload_for("lapis-monetae-testnet", &[])),
        ("simnet", payload_for("lapis-monetae-simnet", &[])),
        ("devnet", payload_for("lapis-monetae-devnet", &[])),
        ("testnet11", payload_for("lapis-monetae-testnet", &[11, 4])),
    ];

    let timestamps = [
        ("mainnet", 1769947200000u64),
        ("testnet", 0x17c5f62fbb6),
        ("simnet", 0x17c5f62fbb6),
        ("devnet", 0x11e9db49828),
        ("testnet11", 0x17c5f62fbb6),
    ];

    let mut outputs = Vec::new();
    for (name, payload) in payloads {
        let timestamp = timestamps.iter().find(|(n, _)| *n == name).unwrap().1;
        let bits = match name {
            "testnet11" => testnet11_bits(GENESIS_BITS_EASY),
            _ => GENESIS_BITS_EASY,
        };
        let result = mine_genesis(name, payload, timestamp, bits);
        outputs.push(result);
    }

    for out in outputs {
        println!("== {} ==", out.name);
        println!("hash: {}", out.hash.to_hex());
        println!("hash_merkle_root: {}", out.hash_merkle_root.to_hex());
        println!("utxo_commitment: {}", out.utxo_commitment.to_hex());
        println!("timestamp: {}", out.timestamp);
        println!("bits: 0x{:08x}", out.bits);
        println!("nonce: 0x{:x}", out.nonce);
        println!("daa_score: {}", out.daa_score);
        println!("coinbase_payload:");
        print_bytes(&out.coinbase_payload);
        println!();
    }
}

fn payload_for(text: &str, suffix: &[u8]) -> Vec<u8> {
    let mut payload = Vec::with_capacity(32 + text.len() + suffix.len());
    payload.extend_from_slice(&[0x00; 8]); // Blue score
    payload.extend_from_slice(&[0x00, 0xE1, 0xF5, 0x05, 0x00, 0x00, 0x00, 0x00]); // Subsidy
    payload.extend_from_slice(&[0x00, 0x00]); // Script version
    payload.push(0x01); // Varint
    payload.push(0x00); // OP-FALSE
    payload.extend_from_slice(text.as_bytes());
    payload.extend_from_slice(suffix);
    payload
}

fn mine_genesis(name: &str, coinbase_payload: Vec<u8>, timestamp: u64, bits: u32) -> GenesisOutput {
    let tx = Transaction::new(0, Vec::new(), Vec::new(), 0, SUBNETWORK_ID_COINBASE, 0, coinbase_payload.clone());
    let hash_merkle_root = calc_hash_merkle_root(std::iter::once(&tx), false);
    let utxo_commitment = EMPTY_MUHASH;
    let target = Uint256::from_compact_target_bits(bits);
    let mut header = Header::new_finalized(
        GENESIS_VERSION,
        Vec::new(),
        hash_merkle_root,
        ZERO_HASH,
        utxo_commitment,
        timestamp,
        bits,
        0,
        DAA_SCORE,
        BlueWorkType::from(0u64),
        0,
        ZERO_HASH,
    );

    let mut nonce = 0u64;
    loop {
        let hash_value = Uint256::from_le_bytes(header.hash.as_bytes());
        if hash_value <= target {
            break;
        }
        nonce = nonce.wrapping_add(1);
        header.nonce = nonce;
        header.finalize();
    }

    GenesisOutput {
        name: name.to_string(),
        hash: header.hash,
        hash_merkle_root,
        utxo_commitment,
        timestamp,
        bits,
        nonce,
        daa_score: DAA_SCORE,
        coinbase_payload,
    }
}

fn testnet11_bits(base_bits: u32) -> u32 {
    let bps = TenBps::bps();
    let target = Uint256::from_compact_target_bits(base_bits);
    let scaled_target = (target / 100) * bps;
    scaled_target.compact_target_bits()
}

fn print_bytes(bytes: &[u8]) {
    let mut line = String::new();
    for (idx, value) in bytes.iter().enumerate() {
        if idx % 16 == 0 {
            if !line.is_empty() {
                println!("{}", line);
                line.clear();
            }
            line.push_str("    ");
        }
        line.push_str(&format!("0x{:02x}, ", value));
    }
    if !line.is_empty() {
        println!("{}", line);
    }
}

struct GenesisOutput {
    name: String,
    hash: Hash,
    hash_merkle_root: Hash,
    utxo_commitment: Hash,
    timestamp: u64,
    bits: u32,
    nonce: u64,
    daa_score: u64,
    coinbase_payload: Vec<u8>,
}
