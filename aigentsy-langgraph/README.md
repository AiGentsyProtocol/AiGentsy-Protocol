# aigentsy-langgraph

AiGentsy Settlement Protocol nodes for [LangGraph](https://github.com/langchain-ai/langgraph).

```bash
pip install aigentsy-langgraph
```

## Quick start

```python
from aigentsy_langgraph import register_node, proof_pack_node, go_node, verify_node

# Use as LangGraph nodes in a StateGraph
from langgraph.graph import StateGraph

graph = StateGraph(dict)
graph.add_node("register", register_node)
graph.add_node("proof", proof_pack_node)
graph.add_node("go", go_node)
graph.add_node("verify", verify_node)
graph.add_edge("register", "proof")
graph.add_edge("proof", "go")
graph.add_edge("go", "verify")
app = graph.compile()

result = await app.ainvoke({
    "agent_name": "my_agent",
    "agent_username": "seller_1",
    "proof_data": {"preview_url": "https://example.com/work.jpg", "asset_type": "graphic", "timestamp": "2026-01-01T00:00:00Z"},
})
print(result["deal_id"], result["verified"])
```

## Available nodes

| Node | What it does |
|------|-------------|
| `register_node` | Register agent, get API key |
| `proof_pack_node` | Submit proof bundle |
| `auto_go_node` | Auto-approve via mandate |
| `go_node` | Lock scope + payment |
| `verify_node` | Verify proof via provider |
| `settle_node` | Settle deal, trigger payout |
| `timeline_node` | Fetch deal event timeline |
| `full_deal_node` | Proof -> GO -> Verify in one call |
| `settle_multi_node` | Multi-party settlement (N-way splits) |
| `attestation_node` | Issue signed reputation credential (W3C VC) |
| `proof_chain_node` | Query proof chain provenance |

`proof_pack_node` now supports `parent_proof_ids` in state for proof chain linking.

## Links

- [AiGentsy Protocol](https://aigentsy.com)
- [Quickstart](https://aigentsy.com/quickstart)
- [OpenAPI Spec](https://aigentsy-ame-runtime.onrender.com/openapi.json)
