"""Tests for the apex benchmark staircase (A/B/C/D regimes).

Covers:
    - Regime registry contents
    - Family subset selection per regime
    - Wave plan selection per regime
    - Tail-mode selection per regime
    - run_apex_regime emits a well-formed flat summary with all required
      headline_economics keys and an apex_verdict
    - Verdict rubric is regime-aware
    - Simulator runs are honestly labeled `cannot_assess`
    - Back-compat: legacy run_benchmark still emits the two-regime shape
    - CLI routes correctly between --regime and legacy paths
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import pytest

from hoverstack import prefill_bench
from hoverstack.prefill_bench import (
    APEX_REGIMES, ADVERSARIAL_FAMILIES, PREFILL_DOMINANT_FAMILIES,
    PREFILL_WAVES, _regime_families, _regime_wave_plan,
    run_apex_regime, run_benchmark,
)
from hoverstack.runtime_reference import ReferenceAdapter


# ══════════════════════════════════════════════════════════════════════
#   REGISTRY + ROUTING
# ══════════════════════════════════════════════════════════════════════

EXPECTED_REGIMES = {"recall_suitable", "delta_suitable",
                    "risk_restricted", "mixed"}


def test_registry_contains_exactly_four_regimes():
    assert set(APEX_REGIMES.keys()) == EXPECTED_REGIMES


@pytest.mark.parametrize("regime", sorted(EXPECTED_REGIMES))
def test_regime_has_required_fields(regime):
    r = APEX_REGIMES[regime]
    for k in ("description", "family_source", "families_subset", "wave_plan",
              "tail_mode", "with_long_system_prefix", "exercises",
              "expected_verdict"):
        assert k in r, f"{regime} missing {k}"


def test_recall_suitable_family_subset():
    fams = _regime_families(APEX_REGIMES["recall_suitable"])
    assert set(fams.keys()) == {"contract_review", "bom_extract"}
    # rare_freeform explicitly excluded so open_reasoning doesn't
    # pollute the regime.
    assert "rare_freeform" not in fams


def test_delta_suitable_uses_repeated_tail_mode():
    assert APEX_REGIMES["delta_suitable"]["tail_mode"] == "repeated"


def test_risk_restricted_includes_medical_and_open_reasoning():
    fams = _regime_families(APEX_REGIMES["risk_restricted"])
    # clinical_qa is domain_criticality=medical → HIGH
    assert "clinical_qa" in fams
    # rare_freeform is answer_form=open_reasoning → ELEVATED
    assert "rare_freeform" in fams
    # Plus a safe family to show the plane doesn't gratuitously block.
    assert "contract_review" in fams


def test_mixed_uses_full_prefill_family_set():
    fams = _regime_families(APEX_REGIMES["mixed"])
    assert set(fams.keys()) == set(PREFILL_DOMINANT_FAMILIES.keys())


def test_mixed_uses_default_wave_plan():
    assert _regime_wave_plan(APEX_REGIMES["mixed"]) == PREFILL_WAVES


def test_unknown_regime_raises():
    with pytest.raises(ValueError):
        run_apex_regime(ReferenceAdapter(), "sim-model", "not_a_regime")


# ══════════════════════════════════════════════════════════════════════
#   RUN_APEX_REGIME SUMMARY SHAPE
# ══════════════════════════════════════════════════════════════════════

REQUIRED_HEADLINE_KEYS = (
    "recall_attempt_rate", "recall_success_rate", "recall_reversion_rate",
    "delta_attempt_rate", "delta_success_rate", "delta_fallback_rate",
    "risk_forced_full_compute_rate",
    "compute_avoided_by_recall_ms", "compute_avoided_by_delta_ms",
    "net_value_by_class", "waste_carry_units",
    "top_negative_net_shapes", "top_positive_recall_shapes",
    "top_positive_delta_shapes",
    "proof_completeness_rate",
)


@pytest.mark.parametrize("regime", sorted(EXPECTED_REGIMES))
def test_run_apex_regime_summary_shape(regime):
    """Every regime emits the spec-required headline metrics and a
    regime-metadata block suitable for CI-side inspection."""
    adapter = ReferenceAdapter(simulate_prefix_cache=True)
    summary = run_apex_regime(adapter, "sim-model", regime,
                                seed=42, num_waves=2)

    # Top-level regime metadata.
    assert summary["regime_name"] == regime
    assert summary["regime_description"]
    assert summary["regime_families"]
    assert summary["regime_expected"]
    assert summary["tail_mode"] in ("varied", "repeated")
    assert "apex_verdict" in summary
    assert "capabilities" in summary
    assert "headline_economics" in summary

    # Required headline keys.
    he = summary["headline_economics"]
    for k in REQUIRED_HEADLINE_KEYS:
        assert k in he, f"[{regime}] headline_economics missing {k}"


def test_simulator_regime_is_labeled_cannot_assess():
    """Simulator + cap-off default path must not claim a real verdict."""
    adapter = ReferenceAdapter(simulate_prefix_cache=False)
    summary = run_apex_regime(adapter, "sim-model", "mixed",
                                seed=42, num_waves=2)
    assert summary["meaningful"] is False
    assert summary["apex_verdict"]["label"] == "cannot_assess"


def test_simulator_with_sim_caps_still_labeled_cannot_assess():
    """Even with caps simulated on, `meaningful` stays False because the
    adapter is the reference sim. The verdict refuses to label a win."""
    adapter = ReferenceAdapter(simulate_prefix_cache=True)
    summary = run_apex_regime(adapter, "sim-model", "recall_suitable",
                                seed=42, num_waves=2)
    assert summary["adapter_is_simulated"] is True
    assert summary["meaningful"] is False
    assert summary["apex_verdict"]["label"] == "cannot_assess"


# ══════════════════════════════════════════════════════════════════════
#   REGIME-SPECIFIC BEHAVIOUR (simulator-backed; directional only)
# ══════════════════════════════════════════════════════════════════════

def test_risk_restricted_drives_forced_full_compute_rate():
    """The risk plane must force full compute on the high-risk families.
    clinical_qa (medical=HIGH) and rare_freeform contribute ~6/10 of
    cells per wave; the `risk_forced_full_compute_rate` should be > 0."""
    adapter = ReferenceAdapter(simulate_prefix_cache=True)
    summary = run_apex_regime(adapter, "sim-model", "risk_restricted",
                                seed=42, num_waves=2)
    he = summary["headline_economics"]
    assert he["risk_forced_full_compute_rate"] > 0.0, (
        "risk_restricted must force at least one full_compute; got "
        f"{he['risk_forced_full_compute_rate']}"
    )


def test_recall_suitable_shows_no_risk_forced_full():
    """In the recall_suitable regime, families are all low-risk so the
    risk plane should not force full compute for any cell."""
    adapter = ReferenceAdapter(simulate_prefix_cache=True)
    summary = run_apex_regime(adapter, "sim-model", "recall_suitable",
                                seed=42, num_waves=2)
    he = summary["headline_economics"]
    assert he["risk_forced_full_compute_rate"] == 0.0


def test_delta_suitable_high_delta_rate():
    """With repeated tails, the delta plane should fire on essentially
    every cell after the first wave."""
    adapter = ReferenceAdapter(simulate_prefix_cache=True)
    summary = run_apex_regime(adapter, "sim-model", "delta_suitable",
                                seed=42, num_waves=2)
    he = summary["headline_economics"]
    assert he["delta_attempt_rate"] >= 0.5, (
        f"delta_suitable should fire delta on ≥50% of cells; got "
        f"{he['delta_attempt_rate']}"
    )


# ══════════════════════════════════════════════════════════════════════
#   BACK-COMPAT
# ══════════════════════════════════════════════════════════════════════

def test_legacy_run_benchmark_still_emits_two_regime_shape():
    """Legacy callers that do not pass a regime should see the exact
    same top-level summary shape as before (prefill_dominant +
    adversarial sub-dicts, answer_to_main_question)."""
    adapter = ReferenceAdapter(simulate_prefix_cache=True)
    s = run_benchmark(adapter, "sim-model", seed=42, num_waves=2)
    assert "prefill_dominant" in s
    assert "adversarial" in s
    assert "answer_to_main_question" in s


def test_legacy_summary_keeps_headline_economics_block():
    adapter = ReferenceAdapter(simulate_prefix_cache=True)
    s = run_benchmark(adapter, "sim-model", seed=42, num_waves=2)
    for regime in ("prefill_dominant", "adversarial"):
        assert "headline_economics" in s[regime]


# ══════════════════════════════════════════════════════════════════════
#   CLI CONTRACT
# ══════════════════════════════════════════════════════════════════════

def test_cli_regime_flag_produces_flat_summary():
    """Invoke the module with --regime and verify the resulting
    summary.json is a flat apex summary (no prefill_dominant /
    adversarial sub-dicts)."""
    with tempfile.TemporaryDirectory() as td:
        run_dir = os.path.join(td, "apex_out")
        proc = subprocess.run(
            [sys.executable, "-m", "hoverstack.prefill_bench",
             "--adapter", "reference", "--sim-prefix-cache",
             "--waves", "2", "--regime", "recall_suitable",
             "--run-dir", run_dir],
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))),
            capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, f"CLI failed: {proc.stderr}"
        payload = json.load(open(os.path.join(run_dir, "summary.json")))
        assert payload["regime_name"] == "recall_suitable"
        assert "apex_verdict" in payload
        # Legacy two-regime keys must NOT be present.
        assert "prefill_dominant" not in payload
        assert "adversarial" not in payload


def test_cli_legacy_path_still_emits_two_regime_shape():
    """Invoke the module WITHOUT --regime and verify back-compat."""
    with tempfile.TemporaryDirectory() as td:
        run_dir = os.path.join(td, "legacy_out")
        proc = subprocess.run(
            [sys.executable, "-m", "hoverstack.prefill_bench",
             "--adapter", "reference", "--sim-prefix-cache",
             "--waves", "2",
             "--run-dir", run_dir],
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))),
            capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, f"CLI failed: {proc.stderr}"
        payload = json.load(open(os.path.join(run_dir, "summary.json")))
        assert "prefill_dominant" in payload
        assert "adversarial" in payload
        assert "answer_to_main_question" in payload
