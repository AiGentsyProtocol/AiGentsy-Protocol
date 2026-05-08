# aigentsy-mcp

MCP server for the AiGentsy Settlement Protocol. Drop into Claude Desktop, Cursor, Cline, or any MCP-compatible runtime — your agent gains 10 tools for proof creation, verification, and exactly-once settlement.

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

Restart your MCP client. Your agent now has access to 10 AiGentsy tools.

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
