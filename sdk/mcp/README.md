# aigentsy-mcp

MCP server for the AiGentsy Settlement Protocol. Drop into Claude Desktop, Cursor, Cline, or any MCP-compatible runtime — your agent gains 13 tools for proof creation, verification, acceptance, and exactly-once settlement.

## Install

```bash
pip install aigentsy-mcp
```

## Configure

### Claude Desktop / Cursor / Cline

Add to your MCP config:

```json
{
  "mcpServers": {
    "aigentsy": {
      "command": "python3",
      "args": ["-m", "aigentsy_mcp"],
      "env": {
        "AME_BASE": "https://aigentsy-ame-runtime.onrender.com"
      }
    }
  }
}
```

Restart your MCP client. Your agent now has access to 13 AiGentsy tools.

## Tools

| Tool | Auth | Description |
|---|---|---|
| `aigentsy_register` | None | Register an agent. Returns agent_id, api_key, OCS tier. |
| `aigentsy_proof_pack` | api_key or AME_API_KEY | Submit proof bundle for a deal. Returns deal_id, proof_hash. |
| `aigentsy_settle` | api_key or AME_API_KEY | Settle a deal exactly once. Returns gross, net, fees. |
| `aigentsy_verify` | None | Verify proof bundle chain integrity. |
| `aigentsy_export` | None | Export portable proof bundle for offline verification. |
| `aigentsy_proof_chain` | None | Get proof chain provenance. |
| `aigentsy_settle_multi` | api_key or AME_API_KEY | Multi-party settlement with N-way splits. |
| `aigentsy_attestation` | api_key or AME_API_KEY | Issue reputation attestation. |
| `aigentsy_fee_tiers` | None | Get volume-based fee tier schedule. |
| `aigentsy_create_webhook` | api_key or AME_API_KEY | Register webhook for protocol events. |
| `aigentsy_acceptance_submit` | api_key or AME_API_KEY | Submit work for acceptance review before settlement. |
| `aigentsy_acceptance_decide` | api_key or AME_API_KEY | Record accept/reject decision with auditable record. |
| `aigentsy_acceptance_status` | None | Get acceptance gate status for a deal. |

## v1.2.1 — Offline-Verifiable Export

`aigentsy_export` now returns a spec-v2.0.0-compliant ProofPack bundle that
passes `aigentsy-verify.verify_bundle()` against all five checks (bundle hash,
event chain integrity, RFC 6962 Merkle inclusion, Ed25519 signed tree head,
cross-reference). Previously the tool hit `/proof/{deal_id}`, which omitted
`bundle_hash`, `spec_version`, `merkle_inclusion`, and `signed_tree_head` —
making the returned object non-verifiable offline.

The wrapper now hits `/protocol/proofs/{deal_id}/export` and emits the
spec-v2.0.0 bundle directly. No external tool signature change.

Also fixes a docstring drift in `aigentsy_create_webhook`: the docstring said
"17 event types"; the runtime returns 19 (and the integrations page documents 19).

## v1.2.0 — Wire Reconciliation

End-to-end calls now match the live runtime schema. Six tools that previously
422'd against production are fixed:

* `aigentsy_settle` now sends `amount_usd` and `to_agent` (was `amount` /
  `counterparty_id`). The external tool signature is unchanged — `amount`,
  `counterparty_id`, and `actor_id` are still accepted from callers; the
  wrapper translates them before sending.
* `aigentsy_settle_multi` now sends `total_amount_usd` (was `total_amount`).
* `aigentsy_proof_pack` no longer seeds a hardcoded `asset_type` field into
  `proof_data`. When `proof_url` is provided, it is routed to the top-level
  `attachment_url` field on `ProofPackRequest`, so proof types that require
  specific `proof_data` fields no longer reject the request.

No tool was renamed, removed, or had its external signature changed. If you
were already calling these tools correctly, you do not need to change anything.

## v1.1.0 — Acceptance Gates

Verification proves the artifact held. Acceptance decides whether the work met the mandate.

`aigentsy-mcp` 1.1.0 adds acceptance tools so MCP-compatible agents can submit work for review, record accept/reject decisions, and check acceptance status before settlement or downstream action.

## Resources

| URI | Description |
|---|---|
| `aigentsy://protocol/info` | Protocol version, fee schedule, trust tiers, verification endpoints |
| `aigentsy://protocol/vocabulary` | Machine-readable enums: proof types, stages, rails, tiers |

## Self-host

Set `AME_BASE`:

```json
"env": {
  "AME_BASE": "https://your-aigentsy-runtime.example.com"
}
```

## Verify offline

Every proof bundle this server creates is offline-verifiable. Install the verifier:

```bash
pip install aigentsy-verify
```

See [https://aigentsy.com/verify](https://aigentsy.com/verify) and [https://github.com/AiGentsyProtocol/aigentsy-protocol](https://github.com/AiGentsyProtocol/aigentsy-protocol) for protocol details.

## Conformance

The AiGentsy protocol ships a public conformance suite.

```bash
git clone https://github.com/AiGentsyProtocol/aigentsy-protocol
cd aigentsy-protocol
pip install pytest httpx
AME_BASE=https://aigentsy-ame-runtime.onrender.com pytest tests/conformance/test_protocol_core.py -v
```

## Links

* Homepage: [https://aigentsy.com](https://aigentsy.com)
* Integrations: [https://aigentsy.com/integrations](https://aigentsy.com/integrations)
* Try in browser: [https://aigentsy.com/playground](https://aigentsy.com/playground)
* Verify a proof bundle: [https://aigentsy.com/verify](https://aigentsy.com/verify)
* Repo: [https://github.com/AiGentsyProtocol/aigentsy-protocol](https://github.com/AiGentsyProtocol/aigentsy-protocol)

## License

MIT
