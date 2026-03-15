# Lapis Monetae (LMT)

**Website:** [https://lapismonetae.org](https://lapismonetae.org) — Pre-built binaries, wallet GUI, and mining tools available for download.

Lapis Monetae (LMT) is a Rust-based full node derived from the Kaspa codebase, adapted to run an independent network and currency named Lapis Monetae (ticker: LMT). This repository provides consensus, networking (P2P), RPC, wallet, and tooling necessary to operate the LMT network.

## Consensus & Roadmap
- Supply and Emission: Adjusted to a target of 100,000,000 LMT over ~8 years.
- Consensus: RandomX Proof-of-Work.
- Mining: RandomX PoW is active; LMT-native stratum tooling is integrated under `tools/xmrig-lmt`.

## Addresses & Networks
- Address prefixes: `lmt:` (mainnet), `lmttest:`, `lmtsim:`, `lmtdev:`.
- Network name strings: `lmt-mainnet`, `lmt-testnet-<suffix>`, etc.

## Default Ports

| Network   | P2P   | gRPC (RPC) | wRPC Borsh | wRPC JSON |
|-----------|-------|------------|------------|-----------|
| Mainnet   | 26111 | 26110      | 27110      | 28110     |
| Testnet-10| 26211 | 26210      | 27210      | 28210     |
| Testnet-11| 26311 | 26210      | 27210      | 28210     |
| Simnet    | 26511 | 26510      | 27510      | 28510     |
| Devnet    | 26611 | 26610      | 27610      | 28610     |

## Project Structure

```
lapis-monetae/
├── cli/            # CLI wallet and RPC interface
├── consensus/      # Consensus rules and DAG logic
├── core/           # Core primitives and utilities
├── crypto/         # Cryptographic primitives (addresses, hashes, signatures)
├── daemon/         # Node daemon wrapper
├── database/       # RocksDB storage layer
├── indexes/        # UTXO and transaction indexes
├── kaspad/         # Main node binary (lmtd)
├── math/           # Mathematical utilities
├── metrics/        # Prometheus metrics
├── mining/         # Mining manager and mempool
├── notify/         # Event notification system
├── protocol/       # P2P protocol and flows
├── RandomX/        # RandomX PoW algorithm
├── rpc/            # gRPC and wRPC servers
├── simpa/          # Simulation and testing tools
├── testing/        # Integration tests
├── tools/          # Auxiliary tools (xmrig-lmt, etc.)
├── utils/          # Shared utilities
├── wallet/         # Wallet core library
├── wallet-web/     # Web wallet components
├── wasm/           # WASM bindings for JS/TS
└── wallet.py       # Python GUI wallet launcher
```

## System Requirements

| Component | Minimum       | Recommended      |
|-----------|---------------|------------------|
| RAM       | 4 GB          | 8+ GB            |
| Disk      | 20 GB SSD     | 50+ GB NVMe SSD  |
| CPU       | 2 cores       | 4+ cores         |
| OS        | Linux/Windows/macOS (64-bit) |

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

## Python Wallet GUI
A graphical wallet launcher is available via `wallet.py` in the root directory:
```bash
python wallet.py
```
This GUI wraps the CLI wallet, providing a dark-themed interface for:
- Creating and importing wallets
- Managing addresses
- Sending transactions
- Connecting to different networks (mainnet, testnet-10, testnet-11)

Requirements: Python 3.8+ with Tkinter (included in most Python distributions).

## Tests, Lints, Benchmarks
```bash
cargo test --release
./check  # lints
cargo bench
```

## Troubleshooting

**Node won't start:**
- Ensure ports 26110-26111 (mainnet) or 26210-26211 (testnet) are not in use.
- Check file descriptor limits: `ulimit -n 4096`

**Mining not working:**
- Verify the node is running with `--utxoindex --enable-unsynced-mining` for local testing.
- Ensure the bridge is connecting to the correct gRPC port (default: 26110).

**Wallet connection issues:**
- Confirm the node has `--utxoindex` enabled (required for wallet operations).
- Check that wRPC is enabled if using remote connections.

**Build errors:**
- Ensure `protoc` (protobuf compiler) is installed and in PATH.
- On Windows, verify LLVM `bin` directory is in PATH.

## License

ISC License. See [LICENSE](LICENSE) for details.

---
