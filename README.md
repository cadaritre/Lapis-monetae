# Lapis Monetae (LMT)

Lapis Monetae (LMT) is a Rust full node forked from the Kaspa codebase and adapted to run an independent network and currency named Lapis Monetae (ticker: LMT).

This workspace contains:
- Full node daemon (`lmtd` binary in `kaspad` crate)
- Consensus, P2P, RPC (gRPC + wRPC), indexing and mining components
- CLI and wallet-related crates (native + wasm)

## Current network identity in code
- Address prefixes: `lmt:` (mainnet), `lmttest:`, `lmtsim:`, `lmtdev:`
- Network identifiers: `mainnet`, `testnet-<suffix>`, `devnet`, `simnet`
- Prefixed network identifier format: `lmt-<network-id>` (for example `lmt-mainnet`)

## Consensus / mining notes
- PoW uses RandomX (implemented in `consensus/pow` via `randomx-rs`)
- Emission target logic is configured around a 100,000,000 LMT supply model in coinbase subsidy code

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

## Running the node
Start a mainnet node:
```bash
cargo run --release --bin lmtd
# or with UTXO index enabled (needed for some wallet queries)
cargo run --release --bin lmtd -- --utxoindex
```

Start a testnet node (default suffix is `10` unless overridden):
```bash
cargo run --release --bin lmtd -- --testnet
# explicit suffix example
cargo run --release --bin lmtd -- --testnet --netsuffix=11
```

Using a config file:
```bash
cargo run --release --bin lmtd -- --configfile /path/to/configfile.toml
# or
cargo run --release --bin lmtd -- -C /path/to/configfile.toml
```

See available arguments:
```bash
cargo run --release --bin lmtd -- --help
```

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

## CLI
Run the CLI:
```bash
cargo run --release -p kaspa-cli
```

## Tests, lints, benchmarks
```bash
cargo test --release
./check  # fmt + clippy checks
cargo bench
```

---
by: cadaritre
