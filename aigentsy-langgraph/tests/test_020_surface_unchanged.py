"""The 0.2.0 surface MUST be byte-unchanged at 0.3.0.

Every node and every client method that existed at 0.2.0 must still
import, still be callable, and still hit the same backend endpoint
shape. The 0.3.0 additions are additive — existing users upgrade
without breakage."""
from __future__ import annotations

import inspect

import aigentsy_langgraph
from aigentsy_langgraph.client import AsyncAiGentsyClient


EXISTING_NODE_NAMES = (
    "register_node", "proof_pack_node", "auto_go_node", "go_node",
    "verify_node", "settle_node", "timeline_node", "full_deal_node",
    "settle_multi_node", "attestation_node", "proof_chain_node",
)

EXISTING_CLIENT_METHODS = (
    "register", "create_proof_pack", "auto_go", "go", "verify_proof",
    "settle", "get_timeline", "get_attribution", "get_proof_bundle",
    "get_reputation", "settle_multi", "issue_attestation",
    "get_proof_chain",
)


def test_all_eleven_existing_nodes_exported():
    for name in EXISTING_NODE_NAMES:
        assert hasattr(aigentsy_langgraph, name), (
            f"0.2.0 node {name!r} missing from package exports"
        )
        fn = getattr(aigentsy_langgraph, name)
        assert callable(fn), f"{name} is not callable"
        assert inspect.iscoroutinefunction(fn), (
            f"{name} must still be a coroutine function"
        )


def test_existing_client_methods_present():
    for name in EXISTING_CLIENT_METHODS:
        assert hasattr(AsyncAiGentsyClient, name), (
            f"0.2.0 AsyncAiGentsyClient.{name} missing"
        )
        m = getattr(AsyncAiGentsyClient, name)
        assert inspect.iscoroutinefunction(m), (
            f"{name} must still be a coroutine method"
        )


def test_existing_node_signatures_unchanged():
    """Spot-check on a representative subset: signature didn't drift
    (single positional ``state: Dict``). A more thorough golden-master
    of signatures would be over-engineering; the catch is "did anyone
    rename a kwarg" — same one-positional-arg test handles that."""
    for name in EXISTING_NODE_NAMES:
        fn = getattr(aigentsy_langgraph, name)
        sig = inspect.signature(fn)
        params = list(sig.parameters.values())
        assert len(params) == 1, (
            f"{name}: 0.2.0 signature is (state: Dict) — drifted to "
            f"{[str(p) for p in params]}"
        )
        assert params[0].name == "state", (
            f"{name}: 0.2.0 first arg is `state` — got {params[0].name}"
        )


def test_new_030_nodes_also_exported():
    """The four new nodes ARE exported alongside the eleven."""
    for name in ("enroll_key_node", "accept_node", "reject_node",
                 "outcome_receipt_node"):
        assert hasattr(aigentsy_langgraph, name), (
            f"0.3.0 node {name!r} missing from package exports"
        )


def test_total_node_count_is_15():
    """Sanity: 11 existing + 4 new = 15 node-shaped exports. A future
    addition should flip this test honestly."""
    node_names = [n for n in aigentsy_langgraph.__all__ if n.endswith("_node")]
    assert len(node_names) == 15, (
        f"expected 15 *_node exports (11 0.2.0 + 4 0.3.0), got "
        f"{len(node_names)}: {sorted(node_names)}"
    )
