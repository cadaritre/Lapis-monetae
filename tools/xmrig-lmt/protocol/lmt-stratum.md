# LMT Stratum (native job)

This document defines a minimal, LMT-native Stratum extension intended for the XMRig fork.
It keeps the standard JSON-RPC framing but uses LMT-specific job fields.

## Transport
- TCP, line-delimited JSON.
- Requests and responses follow JSON-RPC style: `{ "id": <int>, "method": "...", "params": [...] }`.

## Handshake
1. `mining.subscribe`
2. `mining.authorize`
3. Server replies with the first `mining.notify`

## Methods

### mining.subscribe
Request:
```json
{"id":1,"method":"mining.subscribe","params":["xmrig-lmt/0.1"]}
```
Response:
```json
{"id":1,"result":{"protocol":"lmt-stratum/1.0"},"error":null}
```

### mining.authorize
Request:
```json
{"id":2,"method":"mining.authorize","params":["lmt:ADDRESS","x"]}
```
Response:
```json
{"id":2,"result":true,"error":null}
```

### mining.notify
Notification (server -> miner):
```json
{"method":"mining.notify","params":[
  "job_id",
  "pre_pow_hash_hex",
  1769947200000,
  "bits_hex",
  "target_hex"
]}
```

Fields:
- `job_id`: server-generated id for the template.
- `pre_pow_hash_hex`: header hash with nonce=0 and timestamp=0.
- `timestamp`: milliseconds (from template header).
- `bits_hex`: compact target bits (hex string).
- `target_hex`: full target (hex string, little-endian).

### mining.submit
Request:
```json
{"id":3,"method":"mining.submit","params":[
  "worker",
  "job_id",
  "nonce_hex",
  1769947200000
]}
```

Notes:
- `timestamp` is optional; if omitted, the template timestamp is used.
- The server will update the template header nonce and timestamp before submitting.
