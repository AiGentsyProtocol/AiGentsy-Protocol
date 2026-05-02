# Changelog

## 1.2.1 — 2026-05-02

### Added
- `--fetch-key` flag for opt-in public key fetching from AiGentsy runtime
- `verification_level` field in output (`"offline"` or `"full"`)
- `steps_run` and `steps_skipped` counts in verification result
- Clearer SKIPPED messages with reason and remediation hint

### Changed
- STH SKIPPED now shows: `SKIPPED (no public key — use --fetch-key or --public-key)`
- `--strict` failure message includes remediation guidance
- Output footer shows `level: offline (4/5 steps)` or `level: full (5/5 steps)`

### Notes
- Default behavior remains offline (no network calls)
- Use `--fetch-key` to enable Step 4 (STH signature verification)

## 1.2.0 — 2026-05-01

### Added
- CLI entrypoint: `aigentsy-verify bundle proofpack.json`
- `--json` flag for machine-readable output
- `--strict` flag (fails if STH signature verification is skipped)
- `--public-key` flag for local Ed25519 key file
- `__main__.py` for `python -m aigentsy_verify`
- Agent trace display when present in bundle

## 1.1.0 — 2026-04-17

### Added
- Policy layer display
- Anchor receipt verification

## 1.0.0 — 2026-03-27

### Initial release
- 5-step offline bundle verification
- Ed25519 STH signature verification
- RFC 6962 Merkle inclusion and consistency proofs
- Attestation verification
- Public key fetching
