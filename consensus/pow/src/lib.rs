// public for benchmarks
#[doc(hidden)]
pub mod matrix;
#[cfg(feature = "wasm32-sdk")]
pub mod wasm;
#[doc(hidden)]
pub mod xoshiro;

use std::cmp::max;

use kaspa_consensus_core::{hashing, header::Header, BlockLevel};
use kaspa_hashes::{Hash, PowHash};
use kaspa_math::Uint256;
#[cfg(not(target_arch = "wasm32"))]
use randomx_rs::{RandomXCache, RandomXFlag, RandomXVM};

/// State is an intermediate data structure with pre-computed values to speed up mining.
pub struct State {
    pub(crate) target: Uint256,
    pub(crate) pre_pow_hash: Hash,
    pub(crate) timestamp: u64,
    #[cfg(not(target_arch = "wasm32"))]
    pub(crate) vm: RandomXVM,
    #[cfg(target_arch = "wasm32")]
    pub(crate) matrix: matrix::Matrix,
}

impl State {
    #[inline]
    pub fn new(header: &Header) -> Self {
        #[cfg(not(target_arch = "wasm32"))]
        {
            let target = Uint256::from_compact_target_bits(header.bits);
            // Zero out the time and nonce to keep a stable pre-PoW hash.
            let pre_pow_hash = hashing::header::hash_override_nonce_time(header, 0, 0);
            let flags = RandomXFlag::get_recommended_flags();
            let cache = RandomXCache::new(flags, &pre_pow_hash.as_bytes()).expect("RandomX cache initialization failed for PoW");
            let vm = RandomXVM::new(flags, Some(cache), None).expect("RandomX VM initialization failed for PoW");

            Self { target, pre_pow_hash, timestamp: header.timestamp, vm }
        }
        #[cfg(target_arch = "wasm32")]
        {
            let target = Uint256::from_compact_target_bits(header.bits);
            // Zero out the time and nonce to keep a stable pre-PoW hash.
            let pre_pow_hash = hashing::header::hash_override_nonce_time(header, 0, 0);
            let matrix = matrix::Matrix::generate(pre_pow_hash);
            Self { target, pre_pow_hash, timestamp: header.timestamp, matrix }
        }
    }

    pub fn from_pre_pow(pre_pow_hash: Hash, timestamp: u64, bits: u32) -> Self {
        #[cfg(not(target_arch = "wasm32"))]
        {
            let target = Uint256::from_compact_target_bits(bits);
            let flags = RandomXFlag::get_recommended_flags();
            let cache = RandomXCache::new(flags, &pre_pow_hash.as_bytes()).expect("RandomX cache initialization failed for PoW");
            let vm = RandomXVM::new(flags, Some(cache), None).expect("RandomX VM initialization failed for PoW");

            Self { target, pre_pow_hash, timestamp, vm }
        }
        #[cfg(target_arch = "wasm32")]
        {
            let target = Uint256::from_compact_target_bits(bits);
            let matrix = matrix::Matrix::generate(pre_pow_hash);
            Self { target, pre_pow_hash, timestamp, matrix }
        }
    }

    #[inline]
    #[must_use]
    pub fn calculate_pow(&self, nonce: u64) -> Uint256 {
        #[cfg(not(target_arch = "wasm32"))]
        {
            let input = build_randomx_input(self.pre_pow_hash, self.timestamp, nonce);
            let hash_bytes = self.vm.calculate_hash(&input).expect("RandomX PoW hash calculation failed");
            let hash = Hash::from_slice(&hash_bytes);
            return Uint256::from_le_bytes(hash.as_bytes());
        }

        #[cfg(target_arch = "wasm32")]
        {
            let hash = PowHash::new(self.pre_pow_hash, self.timestamp).finalize_with_nonce(nonce);
            let hash = self.matrix.heavy_hash(hash);
            Uint256::from_le_bytes(hash.as_bytes())
        }
    }

    #[inline]
    #[must_use]
    pub fn check_pow(&self, nonce: u64) -> (bool, Uint256) {
        let pow = self.calculate_pow(nonce);
        // The pow hash must be less or equal than the claimed target.
        (pow <= self.target, pow)
    }
}

pub fn calc_block_level(header: &Header, max_block_level: BlockLevel) -> BlockLevel {
    let (block_level, _) = calc_block_level_check_pow(header, max_block_level);
    block_level
}

pub fn calc_block_level_check_pow(header: &Header, max_block_level: BlockLevel) -> (BlockLevel, bool) {
    if header.parents_by_level.is_empty() {
        return (max_block_level, true); // Genesis has the max block level
    }

    let state = State::new(header);
    let (passed, pow) = state.check_pow(header.nonce);
    let block_level = calc_level_from_pow(pow, max_block_level);
    (block_level, passed)
}

pub fn calc_level_from_pow(pow: Uint256, max_block_level: BlockLevel) -> BlockLevel {
    let signed_block_level = max_block_level as i64 - pow.bits() as i64;
    max(signed_block_level, 0) as BlockLevel
}

#[cfg(not(target_arch = "wasm32"))]
fn build_randomx_input(pre_pow_hash: Hash, timestamp: u64, nonce: u64) -> Vec<u8> {
    let mut input = Vec::with_capacity(48);
    input.extend_from_slice(&pre_pow_hash.as_bytes());
    input.extend_from_slice(&timestamp.to_le_bytes());
    input.extend_from_slice(&nonce.to_le_bytes());
    input
}
