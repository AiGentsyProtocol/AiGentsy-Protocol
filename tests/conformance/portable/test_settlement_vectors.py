"""Portable conformance tests for settlement/mandate/coordination vectors.

These tests load ONLY from JSON vector files. They do NOT import any
protocol.* module. They can be ported to any language to validate an
external implementation against the same conformance vectors.

To run:
    python -m pytest tests/conformance/portable/ -v
"""

import json
import os
from pathlib import Path

import pytest


_VECTORS_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "settlement_conformance_vectors.json"
_CORE_VECTORS_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "conformance_vectors.json"


@pytest.fixture(scope="module")
def vectors():
    assert _VECTORS_PATH.exists(), f"Missing {_VECTORS_PATH}"
    with open(_VECTORS_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def core_vectors():
    assert _CORE_VECTORS_PATH.exists(), f"Missing {_CORE_VECTORS_PATH}"
    with open(_CORE_VECTORS_PATH) as f:
        return json.load(f)


# ═══════════════════════════════════════════════════════════════════════
#  VECTOR STRUCTURE VALIDATION
# ═══════════════════════════════════════════════════════════════════════

def test_vectors_load_and_have_spec_version(vectors):
    assert "spec_version" in vectors
    assert vectors["spec_version"] == "settlement_conformance/v1"


def test_mandate_vectors_present(vectors):
    mvecs = vectors.get("mandate_evaluation_vectors", [])
    assert len(mvecs) >= 5, f"Expected >= 5 mandate vectors, got {len(mvecs)}"
    for v in mvecs:
        assert "id" in v
        assert "mandate" in v
        assert "expected" in v


def test_coordination_vectors_present(vectors):
    cvecs = vectors.get("coordination_dependency_vectors", [])
    assert len(cvecs) >= 3, f"Expected >= 3 coordination vectors, got {len(cvecs)}"
    for v in cvecs:
        assert "id" in v
        assert "nodes" in v


def test_value_flow_vectors_present(vectors):
    vvecs = vectors.get("value_flow_release_vectors", [])
    assert len(vvecs) >= 3, f"Expected >= 3 value flow vectors, got {len(vvecs)}"
    for v in vvecs:
        assert "id" in v
        assert "claims" in v
        assert "expected" in v


def test_settlement_workflow_vectors_present(vectors):
    svecs = vectors.get("settlement_workflow_vectors", [])
    assert len(svecs) >= 3, f"Expected >= 3 settlement workflow vectors, got {len(svecs)}"


# ═══════════════════════════════════════════════════════════════════════
#  DETERMINISTIC CALCULATIONS (portable — no protocol imports)
# ═══════════════════════════════════════════════════════════════════════

def test_fee_calculation(vectors):
    """Validate fee calculation from settlement workflow vector."""
    fee_vec = next(
        v for v in vectors["settlement_workflow_vectors"]
        if v["id"] == "settle_02_fee_deduction"
    )
    gross = fee_vec["input"]["gross_amount_usd"]
    fee_pct = fee_vec["input"]["fee_pct"]
    fee_fixed = fee_vec["input"]["fee_fixed"]

    computed_fee = round(gross * fee_pct + fee_fixed, 2)
    computed_net = round(gross - computed_fee, 2)

    assert computed_fee == fee_vec["expected"]["platform_fee"], (
        f"Fee: expected {fee_vec['expected']['platform_fee']}, got {computed_fee}"
    )
    assert computed_net == fee_vec["expected"]["net_to_agent"], (
        f"Net: expected {fee_vec['expected']['net_to_agent']}, got {computed_net}"
    )


def test_split_integrity(vectors):
    """Validate multi-party split sums to 1.0."""
    split_vec = next(
        v for v in vectors["settlement_workflow_vectors"]
        if v["id"] == "settle_03_split_integrity"
    )
    splits = split_vec["input"]["splits"]
    total_fraction = sum(s["fraction"] for s in splits)
    assert abs(total_fraction - 1.0) < 1e-9, (
        f"Split fractions sum to {total_fraction}, expected 1.0"
    )


def test_mandate_valid_basic(vectors):
    """Validate mandate_01: all checks pass → valid=true."""
    vec = next(v for v in vectors["mandate_evaluation_vectors"] if v["id"] == "mandate_01_valid_basic")
    assert vec["expected"]["valid"] is True
    assert len(vec["expected"]["checks_failed"]) == 0
    assert len(vec["expected"]["checks_passed"]) == 7


def test_mandate_expired(vectors):
    """Validate mandate_02: expired mandate → valid=false."""
    vec = next(v for v in vectors["mandate_evaluation_vectors"] if v["id"] == "mandate_02_expired")
    assert vec["expected"]["valid"] is False
    assert "expired" in vec["expected"]["checks_failed_contains"]


def test_coordination_linear_chain(vectors):
    """Validate coord_01: linear A→B→C, only A executable first."""
    vec = next(v for v in vectors["coordination_dependency_vectors"] if v["id"] == "coord_01_linear_chain")
    nodes = {n["commitment_id"]: n for n in vec["nodes"]}

    # A has no deps → executable
    assert len(nodes["A"]["depends_on"]) == 0
    # B depends on A → not executable until A completes
    assert "A" in nodes["B"]["depends_on"]
    # C depends on B
    assert "B" in nodes["C"]["depends_on"]

    assert vec["expected_first_executable"] == ["A"]


def test_coordination_parallel(vectors):
    """Validate coord_02: X,Y independent → both executable."""
    vec = next(v for v in vectors["coordination_dependency_vectors"] if v["id"] == "coord_02_parallel_independent")
    nodes = {n["commitment_id"]: n for n in vec["nodes"]}

    assert len(nodes["X"]["depends_on"]) == 0
    assert len(nodes["Y"]["depends_on"]) == 0
    assert set(nodes["Z"]["depends_on"]) == {"X", "Y"}

    assert set(vec["expected_first_executable"]) == {"X", "Y"}


def test_value_flow_held(vectors):
    """Validate vflow_03: held claim → release blocked."""
    vec = next(v for v in vectors["value_flow_release_vectors"] if v["id"] == "vflow_03_held_claim")
    assert vec["expected"]["valid"] is False
    assert "held:compliance_review" in vec["expected"]["checks_failed_contains"]


def test_core_vectors_have_invariants(core_vectors):
    """Core conformance vectors must include protocol invariants."""
    invariants = core_vectors.get("invariants", [])
    assert len(invariants) >= 10, f"Expected >= 10 invariants, got {len(invariants)}"
