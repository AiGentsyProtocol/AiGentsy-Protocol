"""
AiGentsy + LangGraph — Basic Settlement Graph

pip install aigentsy-langgraph langgraph
python examples/basic_graph.py
"""

import asyncio
from aigentsy_langgraph import register_node, proof_pack_node, go_node, verify_node, timeline_node


async def main():
    state = {
        "agent_name": "langgraph_demo",
        "capabilities": ["marketing"],
        "agent_username": "langgraph_seller",
        "vertical": "marketing",
        "proof_type": "creative_preview",
        "scope_summary": "LangGraph integration demo",
        "proof_data": {
            "preview_url": "https://example.com/demo.jpg",
            "asset_type": "graphic",
            "timestamp": "2026-01-01T00:00:00Z",
        },
    }

    print("Register...")
    state = await register_node(state)
    print(f"  agent_id={state['agent_id']}")

    print("ProofPack...")
    state = await proof_pack_node(state)
    print(f"  deal_id={state['deal_id']}")

    print("GO...")
    state = await go_node(state)
    print(f"  approved={state.get('go_approved')}")

    print("Verify...")
    state = await verify_node(state)
    print(f"  verified={state.get('verified')}")

    print("Timeline...")
    state = await timeline_node(state)
    events = state.get("timeline", {}).get("events", [])
    print(f"  events={len(events)}")

    print(f"\nDone! deal_id={state['deal_id']}")


if __name__ == "__main__":
    asyncio.run(main())
