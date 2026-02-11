## XMRig LMT fork

This fork is wired for LMT-native stratum jobs served by `tools/xmrig-lmt/bridge`.

### LMT-specific behavior
- Detects LMT mode automatically when user starts with `lmt:`.
- Uses `mining.subscribe` + `mining.authorize`.
- Parses `mining.notify` array payload from `tools/xmrig-lmt/protocol/lmt-stratum.md`.
- Builds RandomX input from a 48-byte blob:
  - bytes `[0..31]`: `pre_pow_hash`
  - bytes `[32..39]`: `timestamp` (LE)
  - bytes `[40..47]`: nonce area (mutated by miner)
- Submits shares with `mining.submit`.

### Build (Windows)
Use the regular XMRig build flow (`cmake` + `cmake --build`) from this directory.

### Run against the bridge
Example:
```bash
xmrig.exe -o stratum+tcp://127.0.0.1:3333 -u lmt:YOUR_ADDRESS -p x
```
