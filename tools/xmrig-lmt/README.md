## XMRig LMT tools

This directory contains the LMT-native mining stack around the XMRig fork.

## Structure
- `bridge/` - Rust stratum bridge that fetches templates from LMT RPC and serves native jobs.
- `gui/` - Python Tkinter launcher to run bridge and optionally auto-start miner.
- `protocol/` - LMT-native stratum protocol reference (`lmt-stratum.md`).
- `xmrig-fork/` - XMRig source adapted to LMT-native job format.

## Recommended order
1. Build and run node (`lmtd`) with RPC enabled.
2. Build `bridge/`.
3. Build `xmrig-fork/`.
4. Launch `gui/app.py` and configure paths/URLs.
5. Start bridge and miner from GUI.

## Docs
- Bridge usage: `bridge/README.md`
- GUI usage: `gui/README.md`
- Protocol details: `protocol/lmt-stratum.md`
- XMRig fork notes: `xmrig-fork/README.md`
