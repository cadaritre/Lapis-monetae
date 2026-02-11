# Lapis Monetae (LMT)

Lapis Monetae (LMT) is a Rust-based full node derived from the Kaspa codebase, adapted to run an independent network and currency named Lapis Monetae (ticker: LMT). This repository provides consensus, networking (P2P), RPC, wallet, and tooling necessary to operate the LMT network.

## Consensus & Roadmap
- Supply and Emission: Adjusted to a target of 100,000,000 LMT over ~8 years.
- Consensus: PoW-first with planned PoA (Proof of Authority) augmentation for governance and anchoring.
- Mining: RandomX PoW is active; LMT-native stratum tooling is integrated under `tools/xmrig-lmt`.
- Platform Integration: Planned integration with the "Lapis Mens" platform for ecosystem services.

## Addresses & Networks
- Address prefixes: `lmt:` (mainnet), `lmttest:`, `lmtsim:`, `lmtdev:`.
- Network name strings: `lmt-mainnet`, `lmt-testnet-<suffix>`, etc.

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
# or with UTXO-index enabled (needed when using wallets)
cargo run --release --bin lmtd -- --utxoindex
```
Start a testnet node:
```bash
cargo run --release --bin lmtd -- --testnet
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

## Mining (solo/local)
LMT mining flow uses `get_block_template` and `submit_block` from node RPC, with an LMT-native Stratum bridge and XMRig fork in this repository:

- `tools/xmrig-lmt/bridge/` - LMT Stratum bridge
- `tools/xmrig-lmt/protocol/lmt-stratum.md` - native job protocol (`mining.subscribe`, `mining.authorize`, `mining.notify`, `mining.submit`)
- `tools/xmrig-lmt/xmrig-fork/` - XMRig fork adapted for LMT-native jobs
- `tools/xmrig-lmt/gui/` - Python Tkinter launcher for bridge + miner

### Quickstart (Windows)
1) Start node (test mode flags are acceptable for local validation):
```powershell
cargo run --release --bin lmtd -- --utxoindex --enable-unsynced-mining
```

2) Build bridge:
```powershell
cd tools\xmrig-lmt\bridge
cargo build --release
```

3) Build XMRig fork:
```powershell
cd ..\xmrig-fork
mkdir build
cd build
cmake ..
cmake --build . --config Release
```

4) Run GUI and start both bridge and miner:
```powershell
cd ..\..\gui
python app.py
```

5) In GUI:
- Bridge binary: `tools\xmrig-lmt\bridge\target\release\lmt-stratum-bridge.exe`
- XMRig binary: `tools\xmrig-lmt\xmrig-fork\build\Release\xmrig.exe` (path may vary by generator)
- RPC URL: `grpc://127.0.0.1:26110`
- XMRig URL: `stratum+tcp://127.0.0.1:3333`
- Pay address: `lmt:...`

Protocol note: LMT notify includes `target64_hex` and uses subscribe/authorize handshake (see `tools/xmrig-lmt/protocol/lmt-stratum.md`).

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
JSON protocol is based on LMT data structures and is data-structure-version agnostic. Clients for JS/TS are available via the WASM framework.

## CLI & Wallet
From `cli/`:
```bash
cd cli
cargo run --release
```
This provides a CLI-driven RPC interface to the node and a terminal wallet runtime compatible with the WASM SDK.

## Tests, Lints, Benchmarks
```bash
cargo test --release
./check  # lints
cargo bench
```

---
by: cadaritre
