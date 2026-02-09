# Lapis Monetae (LMT)

Lapis Monetae (LMT) is a Rust full node derived from Kaspa, adapted for an independent network and currency (ticker: **LMT**).
This repository includes consensus, P2P, RPC, wallet/CLI tooling, and mining-template management.

## Protocol facts (from current code)
- **PoW algorithm:** RandomX (`randomx-rs`) is used for block validation/mining.
- **Block target:** 1 second pre-Crescendo, then 100 ms post-Crescendo (10 BPS).
- **Address prefixes:** `lmt:`, `lmttest:`, `lmtsim:`, `lmtdev:`.
- **Network name format:** `lmt-mainnet`, `lmt-testnet-<suffix>`, etc.

## Emission / coin distribution (as implemented)
LMT emission is enforced in consensus coinbase logic.

- Unit: `1 LMT = 100,000,000 sompi`.
- Pre-deflation subsidy base is `50,000,000,000` sompi per block before scaling (500 LMT at 1 BPS).
- Deflationary phase starts at DAA score `15,778,800 - 259,200 = 15,519,600`.
- Deflation table has 426 steps.
- To fit an ~8-year target schedule, subsidy "months" are compressed to `556,920` seconds per step.
- A dynamic **emission divisor** is computed at startup of the coinbase manager so total scheduled emission targets **~100,000,000 LMT**.
- Subsidies are then rounded with `div_ceil` so rewards remain valid across BPS changes (including Crescendo activation).

In short: the schedule is not a README-only promise; it is encoded directly in `consensus/src/processes/coinbase.rs` and network params.

## Mining (solo/local)
This repo ships the node and block-template logic, but **not** a built-in stratum/pool server binary.

Miner flow:
1. Request a template with RPC `get_block_template`.
2. Build PoW input from pre-PoW hash + timestamp + nonce.
3. Solve RandomX target.
4. Submit solved block via RPC `submit_block`.

Run local node for mining tests:
```bash
cargo run --release --bin lmtd -- --enable-unsynced-mining
```

Start mainnet node:
```bash
cargo run --release --bin lmtd
# optional UTXO index (useful for wallet/indexer flows)
cargo run --release --bin lmtd -- --utxoindex
```

Start testnet node:
```bash
cargo run --release --bin lmtd -- --testnet
```

Using a config file:
```bash
cargo run --release --bin lmtd -- --configfile /path/to/configfile.toml
# or
cargo run --release --bin lmtd -- -C /path/to/configfile.toml
```

See all arguments:
```bash
cargo run --release --bin lmtd -- --help
```

## Build
### Linux
1) Prerequisites
```bash
sudo apt install curl git build-essential libssl-dev pkg-config protobuf-compiler libprotobuf-dev
```
2) LLVM/Clang (for RocksDB and WASM secp256k1 when needed)
```bash
sudo apt-get install clang lld
```
3) Rust toolchain
```bash
curl https://sh.rustup.rs -sSf | sh
rustup update
```
4) wasm-pack and wasm32 target (optional)
```bash
cargo install wasm-pack
rustup target add wasm32-unknown-unknown
```
5) Clone and enter
```bash
git clone <your-repo-url>
cd lapis-monetae
```

### Windows (PowerShell)
- Install Git for Windows.
- Install `protoc` and add to `Path`.
- Install LLVM, add `bin` to `Path`.
- Install Rust toolchain and update (`rustup update`).
- Optional: `wasm-pack` and wasm32 target as above.
- Clone and enter the repo.

### macOS (Homebrew)
```bash
brew install protobuf llvm
# Ensure Homebrew llvm is on PATH and set AR if needed
export PATH="/opt/homebrew/opt/llvm/bin:$PATH"
export LDFLAGS="-L/opt/homebrew/opt/llvm/lib"
export CPPFLAGS="-I/opt/homebrew/opt/llvm/include"
export AR=/opt/homebrew/opt/llvm/bin/llvm-ar
```
Install Rust, wasm-pack, wasm32 target (optional), then clone and enter the repo.

## wRPC
wRPC is optional and can be enabled via:
- JSON protocol:
```bash
--rpclisten-json=<interface:port>
# or defaults
--rpclisten-json=default
```
- Borsh protocol:
```bash
--rpclisten-borsh=<interface:port>
# or defaults
--rpclisten-borsh=default
```

## CLI & Wallet
From `cli/`:
```bash
cd cli
cargo run --release
```

## Checks
```bash
cargo test --release
./check  # lints
cargo bench
```

---
by: cadaritre
