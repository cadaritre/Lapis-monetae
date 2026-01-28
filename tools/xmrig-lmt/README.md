## XMRig LMT fork (placeholder)

This directory is reserved for the LMT-native XMRig fork and its tooling.

Contents:
- `bridge/` - LMT Stratum bridge (LMT-native job protocol).
- `protocol/` - LMT-native Stratum job specification used by the fork.
- `xmrig-fork/` - placeholder for the upstream XMRig fork.

Notes:
- The fork will use an LMT-native job format instead of Monero blobs.
- Keep the fork in this directory to avoid conflicts with the workspace crates.
