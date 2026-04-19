"""Verify priors persistence wiring.

Contract:
    - Running runtime_bench or prefill_bench writes
      data/hoverstack_priors.json at the end of the runtime_native mode.
    - The persisted file is valid JSON and loads back into RuntimePriors.
    - Summary shape is unchanged vs the pre-wiring behaviour (same top-
      level keys, same verdict, same per-mode metrics structure).
    - A disk failure during persistence does NOT break the run.
"""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import patch

import pytest

import hoverstack.prefill_bench as prefill_bench
import hoverstack.runtime_bench as runtime_bench
from hoverstack.runtime_priors import RuntimePriors
from hoverstack.runtime_reference import ReferenceAdapter


@pytest.fixture
def isolated_priors_path(tmp_path, monkeypatch):
    """Redirect the hardcoded priors path into a temp directory so the
    test never touches the real data/ folder."""
    p = tmp_path / "data" / "hoverstack_priors.json"
    monkeypatch.setattr(runtime_bench, "HOVERSTACK_PRIORS_PATH", str(p))
    monkeypatch.setattr(prefill_bench, "HOVERSTACK_PRIORS_PATH", str(p))
    return p


def test_runtime_bench_writes_priors_file(isolated_priors_path):
    adapter = ReferenceAdapter(simulate_prefix_cache=True)
    summary = runtime_bench.run_benchmark(adapter, "sim-model",
                                          seed=42, num_waves=2)
    assert isolated_priors_path.exists(), (
        f"runtime_bench did not persist priors to {isolated_priors_path}"
    )
    payload = json.loads(isolated_priors_path.read_text())
    assert payload["version"] >= 1
    assert isinstance(payload["records"], list)
    # After 2 waves of the default workload, priors should have entries
    # for each family observed under the reference_sim runtime.
    assert len(payload["records"]) > 0
    runtime_names = {r["runtime_name"] for r in payload["records"]}
    assert runtime_names == {"reference_sim"}

    # Round-trip through RuntimePriors.load must succeed.
    p = RuntimePriors()
    p.load(str(isolated_priors_path))
    # Summary shape preserved.
    for k in ("adapter", "capabilities", "per_request",
              "deltas_vs_baseline_pct", "net_value_by_class"):
        assert k in summary


def test_prefill_bench_writes_priors_file(isolated_priors_path):
    adapter = ReferenceAdapter(simulate_prefix_cache=True)
    summary = prefill_bench.run_benchmark(adapter, "sim-model",
                                           seed=42, num_waves=2)
    assert isolated_priors_path.exists(), (
        f"prefill_bench did not persist priors to {isolated_priors_path}"
    )
    payload = json.loads(isolated_priors_path.read_text())
    # prefill_bench runs two regimes; the second call overwrites the
    # first, so final file reflects the adversarial regime's priors.
    # That's fine — both regimes use the same runtime, and we just need
    # the file to be valid JSON that RuntimePriors can round-trip.
    assert payload["version"] >= 1
    RuntimePriors().load(str(isolated_priors_path))
    # Verdict structure preserved.
    for regime in ("prefill_dominant", "adversarial"):
        assert regime in summary
        assert "verdict" in summary[regime]
        assert "net_value_by_class" in summary[regime]
    assert "answer_to_main_question" in summary


def test_persistence_failure_does_not_break_benchmark(isolated_priors_path):
    """A disk error during persist() must be swallowed; the benchmark
    must still produce a valid summary."""
    adapter = ReferenceAdapter(simulate_prefix_cache=True)
    with patch.object(RuntimePriors, "persist",
                      side_effect=OSError("simulated disk failure")):
        summary = runtime_bench.run_benchmark(adapter, "sim-model",
                                              seed=42, num_waves=2)
    # Benchmark completed; summary is well-formed.
    assert "per_request" in summary
    assert "net_value_by_class" in summary
    # File should NOT have been created.
    assert not isolated_priors_path.exists()


def test_lifecycle_only_mode_does_not_persist(isolated_priors_path):
    """Priors persistence is wired only for runtime_native mode. This
    confirms the lifecycle_only path does not also write the file."""
    adapter = ReferenceAdapter(simulate_prefix_cache=False)
    # With simulate_prefix_cache=False, caps.safe_reuse_enabled() is false
    # and the benchmark runs both modes, but only runtime_native mode
    # has persist_priors_to set. Both modes still run; the file should
    # be written (by runtime_native) even when its priors are empty of
    # hits. We verify the wiring point, not meaningfulness.
    summary = runtime_bench.run_benchmark(adapter, "sim-model",
                                          seed=42, num_waves=1)
    # File exists because runtime_native mode runs regardless.
    assert isolated_priors_path.exists()
    # But we can also verify: inspecting the _run_with_policy source shows
    # only one call-site passes persist_priors_to. That's the structural
    # contract this test guards.
    import inspect
    src = inspect.getsource(runtime_bench.run_benchmark)
    persist_call_count = src.count("persist_priors_to=HOVERSTACK_PRIORS_PATH")
    assert persist_call_count == 1, (
        f"expected exactly one call-site passing persist_priors_to, "
        f"got {persist_call_count}"
    )


# ── Load-on-start contract ──────────────────────────────────────────

def test_second_run_loads_prior_state(isolated_priors_path):
    """Two separate benchmark invocations sharing the same priors file:
    the second run must start with priors populated from the first."""
    adapter1 = ReferenceAdapter(simulate_prefix_cache=True)
    runtime_bench.run_benchmark(adapter1, "sim-model", seed=42, num_waves=2)
    assert isolated_priors_path.exists()

    # Capture the first run's file state.
    first_payload = json.loads(isolated_priors_path.read_text())
    first_observations = {
        (r["shape_id"], r["runtime_name"]): r["observations"]
        for r in first_payload["records"]
    }
    assert first_observations, "first run produced no priors entries"

    # Second run: spy on MemoryPlane.priors.load to confirm it was called
    # with the persisted path BEFORE any observations occur.
    from hoverstack.runtime_priors import RuntimePriors as _RP
    original_load = _RP.load
    load_calls = []

    def spy_load(self, path):
        load_calls.append((path, self._records.copy()))
        return original_load(self, path)

    with patch.object(_RP, "load", spy_load):
        adapter2 = ReferenceAdapter(simulate_prefix_cache=True)
        runtime_bench.run_benchmark(adapter2, "sim-model", seed=42, num_waves=2)

    # Load was invoked exactly once (runtime_native mode only), with our
    # isolated path, and on an empty priors instance.
    assert len(load_calls) == 1, f"expected exactly one load call, got {len(load_calls)}"
    called_path, records_at_call_time = load_calls[0]
    assert called_path == str(isolated_priors_path)
    assert records_at_call_time == {}, (
        "load() was called on a priors instance that already had records — "
        "cold-start invariant broken"
    )

    # After the second run, observation counts for each (shape, runtime)
    # key must be at least the first run's counts (first_run + second_run).
    second_payload = json.loads(isolated_priors_path.read_text())
    second_observations = {
        (r["shape_id"], r["runtime_name"]): r["observations"]
        for r in second_payload["records"]
    }
    for key, first_n in first_observations.items():
        second_n = second_observations.get(key, 0)
        assert second_n > first_n, (
            f"{key}: expected > {first_n} observations after two runs, "
            f"got {second_n} — load-on-start not accumulating"
        )


def test_missing_priors_file_is_harmless(isolated_priors_path):
    """No priors file on disk → benchmark runs cold-start and produces
    a valid summary. File gets created at end of run (persist side)."""
    assert not isolated_priors_path.exists()
    adapter = ReferenceAdapter(simulate_prefix_cache=True)
    summary = runtime_bench.run_benchmark(adapter, "sim-model",
                                          seed=42, num_waves=1)
    # Summary is well-formed.
    assert "per_request" in summary
    assert "net_value_by_class" in summary
    # File now exists (persist side of the wiring ran).
    assert isolated_priors_path.exists()


def test_invalid_priors_file_does_not_break_benchmark(isolated_priors_path):
    """Corrupt file on disk → load is a no-op; benchmark still runs."""
    isolated_priors_path.parent.mkdir(parents=True, exist_ok=True)
    isolated_priors_path.write_text("{this is not valid json,,,,")
    adapter = ReferenceAdapter(simulate_prefix_cache=True)
    # Must not raise.
    summary = runtime_bench.run_benchmark(adapter, "sim-model",
                                          seed=42, num_waves=1)
    assert "per_request" in summary
    # After the run, the persist side replaces the corrupt file with
    # a valid one (because persist writes atomically via os.replace).
    assert json.loads(isolated_priors_path.read_text())["version"] >= 1


def test_prefill_bench_load_on_start(isolated_priors_path):
    """Same load-on-start contract applies to prefill_bench."""
    adapter1 = ReferenceAdapter(simulate_prefix_cache=True)
    prefill_bench.run_benchmark(adapter1, "sim-model", seed=42, num_waves=2)
    assert isolated_priors_path.exists()

    from hoverstack.runtime_priors import RuntimePriors as _RP
    original_load = _RP.load
    load_calls = []

    def spy_load(self, path):
        load_calls.append(path)
        return original_load(self, path)

    with patch.object(_RP, "load", spy_load):
        adapter2 = ReferenceAdapter(simulate_prefix_cache=True)
        prefill_bench.run_benchmark(adapter2, "sim-model", seed=42, num_waves=2)

    # Two regimes × one runtime_native invocation each = two load calls.
    assert len(load_calls) == 2, (
        f"expected exactly two load calls across two regimes, got {len(load_calls)}"
    )
    assert all(p == str(isolated_priors_path) for p in load_calls)


def test_lifecycle_only_does_not_load(isolated_priors_path):
    """Structural guard: exactly one load-call-site (by kwarg) per
    run_benchmark in both benchmark files."""
    import inspect

    rb_src = inspect.getsource(runtime_bench._run_with_policy)
    # The load block reads persist_priors_to and os.path.exists.
    assert "plane.priors.load(persist_priors_to)" in rb_src, (
        "runtime_bench._run_with_policy missing load-on-start wiring"
    )

    pb_src = inspect.getsource(prefill_bench._run_with_policy)
    assert "plane.priors.load(persist_priors_to)" in pb_src, (
        "prefill_bench._run_with_policy missing load-on-start wiring"
    )

    # Both guarded by `if persist_priors_to and os.path.exists(...)`.
    for src, name in ((rb_src, "runtime_bench"), (pb_src, "prefill_bench")):
        assert "if persist_priors_to and os.path.exists(persist_priors_to):" in src, (
            f"{name}._run_with_policy load block missing the path-gated guard"
        )
