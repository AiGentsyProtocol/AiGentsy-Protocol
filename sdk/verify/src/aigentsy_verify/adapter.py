"""AdapterContract replay — explicit schema validation inside
offline `aigentsy-verify`.

A third party with only the bundle and this package can verify:

  1. adapter_contract_schema_status   — the embedded declaration
                                         conforms to the canonical
                                         AdapterContract schema
  2. contract_hash_status              — sha256(canonical(declaration))
                                         matches adapter_evaluation
                                         .contract_hash
  3. input_schema_hash_status          — same for input_schema_hash
  4. normalized_policy_inputs_status   — every key in
                                         normalized_policy_inputs is in
                                         adapter_contract
                                         .allowed_policy_fields
  5. adapter_validator_status          — the declared validator_name +
                                         validator_version are recorded
                                         (cannot RE-RUN the validator
                                         offline without code, but we
                                         can confirm provenance + that
                                         rejected/incomplete results did
                                         not emit normalized inputs they
                                         shouldn't)
  6. policy_replay_status              — if a REJECTED event in the
                                         bundle carries a policy_snapshot
                                         with matched_rule + evaluated_
                                         inputs, the rule's conditions
                                         must evaluate True against the
                                         inputs
  7. adapter_replay_status             — overall: ok iff every check is
                                         ok or skipped-legitimately

Backwards compat: bundles without ANY proof carrying adapter_evaluation
return adapter_replay_status="legacy_no_adapter" — the new step is
SKIPPED and does NOT fail the overall verifier verdict. Tampering with
an embedded adapter_contract or with allowed_policy_fields produces a
non-ok status AND, because adapter_evaluation rides in proof.evidence
which feeds bundle_hash, also breaks the bundle_hash step.

No network, no live registry, no runtime lookup.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple


# ── Embedded schema rules (mirror specs/adapter-contract.schema.json) ──
#
# We do NOT ship a JSON Schema validator dependency (e.g. jsonschema). The
# rules below are hand-written in pure Python and match the canonical
# schema 1:1. If the schema is ever extended, update both this module and
# specs/adapter-contract.schema.json; the test suite asserts they agree.

SCHEMA_REQUIRED_FIELDS = (
    "adapter_contract_version",
    "adapter_id",
    "adapter_version",
    "input_schema_version",
    "input_schema_hash",
    "output_fields",
    "allowed_policy_fields",
    "validator_name",
    "validator_version",
    "contract_hash",
)

_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_ADAPTER_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_][a-z0-9_]*)+$")
_FIELD_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SHA_RE = re.compile(r"^[a-f0-9]{64}$")


# ── Replay statuses ────────────────────────────────────────────────────

# Per-check status codes:
STATUS_OK = "ok"
STATUS_LEGACY_NO_ADAPTER = "legacy_no_adapter"
STATUS_SCHEMA_FAIL = "schema_fail"
STATUS_CONTRACT_HASH_MISMATCH = "contract_hash_mismatch"
STATUS_INPUT_SCHEMA_HASH_MISMATCH = "input_schema_hash_mismatch"
STATUS_NORMALIZED_NOT_ALLOWED = "normalized_inputs_not_in_allowed_policy_fields"
STATUS_VALIDATOR_MISSING = "validator_declaration_missing"
STATUS_VALIDATOR_INCONSISTENT = "validator_result_inconsistent"
STATUS_POLICY_RULE_MISMATCH = "matched_rule_does_not_fire_against_evaluated_inputs"
STATUS_BAD_SHAPE = "adapter_evaluation_shape_invalid"
# F3 — a policy-governed snapshot whose private rule/context were
# deliberately not distributed. Optional policy re-execution is therefore
# NOT APPLICABLE. This is an adapter-local diagnostic only: it is not a
# protocol decision category, not a published-verifier authority, and it
# does not affect canonical cryptographic verification.
STATUS_REPLAY_UNAVAILABLE = "policy_replay_unavailable_private_rule_not_distributed"


# ── Canonical hashing (mirror of runtime helper) ──────────────────────


def _canonical_hash(obj: Any) -> str:
    canonical = json.dumps(
        obj, sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def recompute_contract_hash(decl: Dict[str, Any]) -> str:
    return _canonical_hash({
        "adapter_contract_version": decl.get("adapter_contract_version", "1.0.0"),
        "adapter_id": decl.get("adapter_id", ""),
        "adapter_version": decl.get("adapter_version", ""),
        "input_schema_version": decl.get("input_schema_version", ""),
        "output_fields": sorted(decl.get("output_fields") or []),
        "allowed_policy_fields": sorted(decl.get("allowed_policy_fields") or []),
        "validator_name": decl.get("validator_name", ""),
        "validator_version": decl.get("validator_version", ""),
    })


def recompute_input_schema_hash(decl: Dict[str, Any]) -> str:
    return _canonical_hash({
        "input_schema_version": decl.get("input_schema_version", ""),
        "output_fields": sorted(decl.get("output_fields") or []),
        "validator_name": decl.get("validator_name", ""),
        "validator_version": decl.get("validator_version", ""),
    })


# ── Schema validation ─────────────────────────────────────────────────


def validate_adapter_contract_schema(decl: Any) -> Tuple[bool, List[str]]:
    """Validate a declaration against the embedded schema. Returns
    (ok, errors).
    """
    if not isinstance(decl, dict):
        return False, ["declaration is not a JSON object"]

    errors: List[str] = []
    missing = [k for k in SCHEMA_REQUIRED_FIELDS if k not in decl]
    if missing:
        for k in missing:
            errors.append(f"missing required field: {k}")
        return False, errors

    for vfield in ("adapter_contract_version", "adapter_version",
                   "input_schema_version", "validator_version"):
        v = decl.get(vfield)
        if not isinstance(v, str) or not _SEMVER_RE.match(v):
            errors.append(f"{vfield} is not semver MAJOR.MINOR.PATCH")

    if not _ADAPTER_ID_RE.match(str(decl.get("adapter_id", ""))):
        errors.append("adapter_id must be reverse-DNS style")

    for arrkey in ("output_fields", "allowed_policy_fields"):
        arr = decl.get(arrkey)
        if not isinstance(arr, list):
            errors.append(f"{arrkey} is not an array")
            continue
        if arrkey == "output_fields" and len(arr) == 0:
            errors.append("output_fields must have at least one entry")
        if len(arr) != len(set(arr)):
            errors.append(f"{arrkey} has duplicate entries")
        for item in arr:
            if not isinstance(item, str) or not _FIELD_RE.match(item):
                errors.append(f"{arrkey} entry {item!r} is not snake_case")

    if not isinstance(decl.get("validator_name", ""), str) or \
            not _FIELD_RE.match(str(decl.get("validator_name", ""))):
        errors.append("validator_name must be snake_case")

    for hkey in ("input_schema_hash", "contract_hash"):
        h = decl.get(hkey, "")
        if not isinstance(h, str) or not _SHA_RE.match(h):
            errors.append(
                f"{hkey} is not a sha256 hex digest (64 lowercase hex)"
            )

    # Subset: allowed_policy_fields ⊆ output_fields
    of = set(decl.get("output_fields") or [])
    apf = set(decl.get("allowed_policy_fields") or [])
    leaked = apf - of
    if leaked:
        errors.append(
            f"allowed_policy_fields not in output_fields: {sorted(leaked)}"
        )

    return len(errors) == 0, errors


# ── Per-evaluation offline replay ─────────────────────────────────────


def verify_adapter_evaluation(ae: Dict[str, Any]) -> Dict[str, Any]:
    """Run every replay check on one adapter_evaluation dict. Returns the
    full per-step status object."""
    out: Dict[str, Any] = {
        "adapter_contract_schema_status": STATUS_LEGACY_NO_ADAPTER,
        "contract_hash_status": STATUS_LEGACY_NO_ADAPTER,
        "input_schema_hash_status": STATUS_LEGACY_NO_ADAPTER,
        "normalized_policy_inputs_status": STATUS_LEGACY_NO_ADAPTER,
        "adapter_validator_status": STATUS_LEGACY_NO_ADAPTER,
        "schema_errors": [],
        "details": {},
    }

    if not isinstance(ae, dict) or not ae.get("adapter_id"):
        out["adapter_contract_schema_status"] = STATUS_BAD_SHAPE
        return out

    decl = ae.get("adapter_contract")
    if not isinstance(decl, dict):
        # Pass-62 legacy bundle — no embedded declaration. Cannot replay.
        return out

    schema_ok, schema_errors = validate_adapter_contract_schema(decl)
    out["schema_errors"] = schema_errors
    out["adapter_contract_schema_status"] = STATUS_OK if schema_ok else STATUS_SCHEMA_FAIL
    if not schema_ok:
        # If schema is broken, downstream hashes will also fail; surface
        # them as failures (cannot trust derived values).
        out["contract_hash_status"] = STATUS_CONTRACT_HASH_MISMATCH
        out["input_schema_hash_status"] = STATUS_INPUT_SCHEMA_HASH_MISMATCH
        out["normalized_policy_inputs_status"] = STATUS_BAD_SHAPE
        out["adapter_validator_status"] = STATUS_BAD_SHAPE
        return out

    # contract_hash
    recomputed_ch = recompute_contract_hash(decl)
    if recomputed_ch == ae.get("contract_hash"):
        out["contract_hash_status"] = STATUS_OK
    else:
        out["contract_hash_status"] = STATUS_CONTRACT_HASH_MISMATCH
        out["details"]["expected_contract_hash"] = ae.get("contract_hash")
        out["details"]["recomputed_contract_hash"] = recomputed_ch

    # input_schema_hash
    recomputed_ish = recompute_input_schema_hash(decl)
    if recomputed_ish == ae.get("input_schema_hash"):
        out["input_schema_hash_status"] = STATUS_OK
    else:
        out["input_schema_hash_status"] = STATUS_INPUT_SCHEMA_HASH_MISMATCH
        out["details"]["expected_input_schema_hash"] = ae.get("input_schema_hash")
        out["details"]["recomputed_input_schema_hash"] = recomputed_ish

    # normalized_policy_inputs ⊆ allowed_policy_fields
    allowed = set(decl.get("allowed_policy_fields") or [])
    normalized_keys = set((ae.get("normalized_policy_inputs") or {}).keys())
    leaked = normalized_keys - allowed
    if leaked:
        out["normalized_policy_inputs_status"] = STATUS_NORMALIZED_NOT_ALLOWED
        out["details"]["leaked_fields"] = sorted(leaked)
    else:
        out["normalized_policy_inputs_status"] = STATUS_OK

    # adapter_validator_status: cannot re-run the validator here, but
    # check the declaration carries name+version AND that for rejected /
    # unknown_adapter results normalized inputs ARE empty (the runtime's
    # fail-closed contract — if a tampered bundle says rejected but
    # carries inputs, that's inconsistent).
    if not decl.get("validator_name") or not decl.get("validator_version"):
        out["adapter_validator_status"] = STATUS_VALIDATOR_MISSING
    elif ae.get("validation_result") in ("rejected", "unknown_adapter") \
            and normalized_keys:
        out["adapter_validator_status"] = STATUS_VALIDATOR_INCONSISTENT
    else:
        out["adapter_validator_status"] = STATUS_OK

    return out


def replay_policy_decision(
    policy_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """Re-evaluate a matched rule against its evaluated_inputs offline.

    Pass-61 introduced structured `evaluated_inputs` carrying provenance.
    For policy replay we extract the value field (or use the bare value
    when the field is a plain primitive — legacy form).

    Returns {"status": ..., "details": ...}.
    """
    if not isinstance(policy_snapshot, dict):
        return {"status": STATUS_BAD_SHAPE, "details": {"reason": "not a dict"}}

    matched = policy_snapshot.get("matched_rule")
    evaluated = policy_snapshot.get("evaluated_inputs")
    if not isinstance(matched, dict) or not isinstance(evaluated, dict):
        # F3 — distinguish two cases that used to collapse into a false
        # "ok". A snapshot that RECORDS a matched rule (rule_index >= 0)
        # but does not carry the rule body or evaluated context is a
        # policy-governed decision whose replay inputs were deliberately
        # withheld: replay was NOT performed and must never be reported as
        # a successful one. A genuine default-action fallthrough (no rule
        # matched, rule_index < 0) keeps its historical "ok" semantics.
        rule_index = policy_snapshot.get("rule_index")
        governed_by_rule = isinstance(rule_index, int) and rule_index >= 0
        if governed_by_rule:
            return {
                "status": STATUS_REPLAY_UNAVAILABLE,
                "details": {
                    "replay": "not_performed",
                    "reason": "private matched rule and evaluated context are "
                              "not distributed in portable ProofPacks",
                    "rule_index": rule_index,
                    "note": "canonical cryptographic verification is "
                            "independent of this optional step",
                },
            }
        return {"status": STATUS_OK, "details": {"replay": "no_match_fallthrough"}}

    def _unwrap(v):
        if isinstance(v, dict) and "value" in v:
            return v["value"]
        return v

    def _eval_cond(c):
        field = c.get("field")
        op = c.get("op")
        expected = c.get("value")
        actual = _unwrap(evaluated.get(field))
        if actual is None:
            return False
        if op == ">=": return actual >= expected
        if op == "<=": return actual <= expected
        if op == ">":  return actual >  expected
        if op == "<":  return actual <  expected
        if op == "==": return actual == expected
        if op == "!=": return actual != expected
        if op == "in":
            return actual in expected if isinstance(expected, list) else False
        return False

    conditions = matched.get("conditions") or []
    all_fire = all(_eval_cond(c) for c in conditions)
    if not all_fire:
        return {
            "status": STATUS_POLICY_RULE_MISMATCH,
            "details": {
                "matched_rule_action": matched.get("action"),
                "evaluated_inputs": evaluated,
            },
        }
    return {
        "status": STATUS_OK,
        "details": {
            "matched_rule_action": matched.get("action"),
            "rule_index": policy_snapshot.get("rule_index"),
        },
    }


def verify_adapter_replay(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """The new top-level step. Returns a structured per-proof + per-event
    replay verdict. Sets `adapter_replay_status` to:

      - STATUS_OK: every adapter-backed proof + every REJECTED event with
        a policy_snapshot replay clean
      - any STATUS_* code from a sub-check on first failure
      - STATUS_LEGACY_NO_ADAPTER: no proof or event carries an
        adapter_evaluation (pre-Pass-65 bundles)
    """
    result: Dict[str, Any] = {
        "adapter_replay_status": STATUS_LEGACY_NO_ADAPTER,
        "proofs_with_adapter": 0,
        "events_with_policy_snapshot": 0,
        "per_proof": [],
        "per_event": [],
        "passed": True,
        "skipped": True,
    }

    proofs = bundle.get("proofs") or []
    events = bundle.get("events") or []

    # Per-proof adapter_evaluation
    for i, p in enumerate(proofs):
        evidence = (p.get("evidence") or {}) if isinstance(p, dict) else {}
        if not isinstance(evidence, dict):
            continue
        ae = evidence.get("adapter_evaluation")
        if not isinstance(ae, dict):
            continue
        result["proofs_with_adapter"] += 1
        report = verify_adapter_evaluation(ae)
        report["proof_index"] = i
        report["adapter_id"] = ae.get("adapter_id", "")
        result["per_proof"].append(report)

    # Per-event policy_snapshot + adapter_evaluation
    for j, e in enumerate(events):
        if not isinstance(e, dict):
            continue
        payload = e.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        ev_report: Dict[str, Any] = {"event_index": j,
                                     "event_type": e.get("event_type", "")}
        ae = payload.get("adapter_evaluation")
        if isinstance(ae, dict):
            ev_report["adapter_evaluation"] = verify_adapter_evaluation(ae)
        snap = payload.get("policy_snapshot")
        if isinstance(snap, dict):
            result["events_with_policy_snapshot"] += 1
            ev_report["policy_replay"] = replay_policy_decision(snap)
        if "adapter_evaluation" in ev_report or "policy_replay" in ev_report:
            result["per_event"].append(ev_report)

    # No adapter_evaluation anywhere → legacy bundle, skip cleanly.
    if not result["per_proof"] and not any(
        "adapter_evaluation" in ev for ev in result["per_event"]
    ):
        result["adapter_replay_status"] = STATUS_LEGACY_NO_ADAPTER
        return result

    # New bundle: roll up. First non-ok subcheck wins.
    result["skipped"] = False
    overall_status = STATUS_OK
    for pr in result["per_proof"]:
        for k in (
            "adapter_contract_schema_status",
            "contract_hash_status",
            "input_schema_hash_status",
            "normalized_policy_inputs_status",
            "adapter_validator_status",
        ):
            if pr.get(k) not in (STATUS_OK, STATUS_LEGACY_NO_ADAPTER):
                overall_status = pr.get(k)
                break
        if overall_status != STATUS_OK:
            break
    if overall_status == STATUS_OK:
        for ev in result["per_event"]:
            pr = ev.get("policy_replay")
            # F3 — `replay_unavailable` is a NOT-APPLICABLE result, not a
            # failed replay, so it must not flip the bundle verdict. A
            # future ProofPack that deliberately withholds the private rule
            # is fully valid; treating it as a failure would fail every
            # compliant bundle (cli.py flips `verified` on any non-passed
            # adapter step). It stays visible per-event so an auditor still
            # sees that replay did not run — honest in detail, non-failing
            # in verdict, exactly as STATUS_LEGACY_NO_ADAPTER is handled.
            # Genuine replay failures (e.g. rule does not fire against the
            # recorded inputs) still flip the verdict.
            if pr and pr.get("status") not in (STATUS_OK,
                                               STATUS_REPLAY_UNAVAILABLE):
                overall_status = pr["status"]
                break
            aev = ev.get("adapter_evaluation")
            if aev:
                for k in (
                    "adapter_contract_schema_status",
                    "contract_hash_status",
                    "input_schema_hash_status",
                    "normalized_policy_inputs_status",
                    "adapter_validator_status",
                ):
                    if aev.get(k) not in (STATUS_OK, STATUS_LEGACY_NO_ADAPTER):
                        overall_status = aev.get(k)
                        break
                if overall_status != STATUS_OK:
                    break

    result["adapter_replay_status"] = overall_status
    result["passed"] = overall_status == STATUS_OK
    return result
