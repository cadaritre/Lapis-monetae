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
Use the XMRig deps bundle and pass it to CMake:

```powershell
# From tools/xmrig-lmt
if (-not (Test-Path deps)) { mkdir deps | Out-Null }
Invoke-WebRequest -Uri "https://github.com/xmrig/xmrig-deps/archive/refs/heads/master.zip" -OutFile "deps/xmrig-deps-master.zip"
Expand-Archive -Path "deps/xmrig-deps-master.zip" -DestinationPath "deps" -Force

# From tools/xmrig-lmt/xmrig-fork
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/xmrig/xmrig/master/bin/WinRing0/WinRing0x64.sys" -OutFile "bin/WinRing0/WinRing0x64.sys"
cmake -S . -B build -DXMRIG_DEPS="../deps/xmrig-deps-master/msvc2022/x64" -DWITH_MSR=OFF
cmake --build build --config Release
```

Binary output (default):
`build/Release/xmrig.exe`

### Run against the bridge
Example:
```bash
xmrig.exe -o stratum+tcp://127.0.0.1:3333 -u lmt:YOUR_ADDRESS -p x
```
