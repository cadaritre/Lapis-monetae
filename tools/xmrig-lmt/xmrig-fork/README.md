## XMRig LMT fork (scaffold)

Place the upstream XMRig source here and apply the LMT job protocol changes.

Recommended workflow:
1. Clone XMRig into this directory.
2. Apply LMT patches (to be created under `patches/`).
3. Build and test against the local bridge.

This fork will implement:
- LMT-native job parsing for `mining.notify`
- RandomX input based on `pre_pow_hash + timestamp + nonce`
- `mining.submit` payload compatible with the bridge
