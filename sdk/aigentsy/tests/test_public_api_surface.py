"""Regression guard: porting gate_and_prove (1.15.0) must NOT remove any public
surface shipped in 1.14.0 — especially the Tier-2 signing methods. Asserts
public names only (not private internals), so it isn't brittle.
"""
import aigentsy
from aigentsy import AiGentsyClient


def test_version_bumped_to_1_16_0():
    assert aigentsy.__version__ == "1.16.0"


def test_public_exports_preserved_and_gate_added():
    # everything 1.14.0 exported must still be exported
    for name in ("AiGentsyClient", "AsyncAiGentsyClient", "SigningKeypair", "NON_CUSTODIAL_NOTICE"):
        assert name in aigentsy.__all__ and hasattr(aigentsy, name), name
    # gate_and_prove is purely ADDITIVE
    for name in ("gate_and_prove", "GateResult", "gate_langchain_tool"):
        assert name in aigentsy.__all__ and hasattr(aigentsy, name), name


def test_public_api_surface_contains_tier2_methods():
    tier2 = [
        "generate_signing_keypair", "enroll_signing_key", "register_with_signing_key",
        "send_signed_event", "record_signed_outcome", "open_signed_dispute",
        "decide_acceptance", "get_signing_capability",
    ]
    for m in tier2:
        assert callable(getattr(AiGentsyClient, m, None)), f"Tier-2 method removed: {m}"


def test_core_client_methods_preserved():
    for m in ("create_proof_pack", "go", "settle", "get_proof_bundle",
              "verify_proof_bundle", "get_merkle_root", "register"):
        assert callable(getattr(AiGentsyClient, m, None)), f"1.14.0 method removed: {m}"


def test_gate_and_prove_exports_without_removing_existing_api():
    # the acceptance-runtime methods that back gate_and_prove are additive
    for m in ("acceptance_runtime_evaluate", "export_run", "get_public_key"):
        assert callable(getattr(AiGentsyClient, m, None)), f"missing new method: {m}"
    assert callable(aigentsy.gate_and_prove)
