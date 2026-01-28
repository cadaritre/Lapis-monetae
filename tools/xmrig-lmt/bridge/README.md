## LMT Stratum Bridge

Minimal TCP Stratum bridge that serves LMT-native mining jobs and submits blocks
using LMT gRPC RPC (`get_block_template` / `submit_block`).

### Build
```bash
cargo build --release
```

### Run (example)
```bash
./target/release/lmt-stratum-bridge \
  --listen 0.0.0.0:3333 \
  --rpc-url grpc://127.0.0.1:26110 \
  --pay-address lmt:YOUR_ADDRESS \
  --refresh-ms 5000
```

### Protocol
See `../protocol/lmt-stratum.md` for the LMT-native job format used by the XMRig fork.
