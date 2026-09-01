"""
aigentsy-verify CLI — Offline ProofPack verification from the command line.

Usage:
    aigentsy-verify bundle proofpack.json
    aigentsy-verify bundle proofpack.json --json
    aigentsy-verify bundle proofpack.json --strict
    aigentsy-verify bundle proofpack.json --fetch-key
    aigentsy-verify bundle proofpack.json --public-key key.pem
"""

import argparse
import json
import sys
from pathlib import Path

from aigentsy_verify import __version__, verify_bundle, load_public_key_from_file

_DEFAULT_KEY_URL = "https://aigentsy-ame-runtime.onrender.com/protocol/merkle/public-key"


def _load_bundle(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(2)
    try:
        with open(p) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON: {e}", file=sys.stderr)
        sys.exit(2)


def _fetch_public_key() -> str:
    try:
        from urllib.request import urlopen
        with urlopen(_DEFAULT_KEY_URL, timeout=10) as r:
            data = json.loads(r.read())
            return data.get("public_key_base64", "")
    except Exception as e:
        print(f"Warning: could not fetch public key: {e}", file=sys.stderr)
        return ""


def _status(passed: bool, skipped: bool = False, reason: str = "") -> str:
    if skipped:
        return f"SKIPPED ({reason})" if reason else "SKIPPED"
    return "PASS" if passed else "FAIL"


def _short_hash(h: str, n: int = 12) -> str:
    if not h or not isinstance(h, str):
        return ""
    return h if len(h) <= n else (h[:n] + "...")


def _short_ts(ts: str) -> str:
    if not ts or not isinstance(ts, str):
        return ""
    if "T" in ts:
        try:
            return ts.split("+")[0].split(".")[0]
        except Exception:
            return ts
    return ts


def _render_governance(gov: dict) -> None:
    """Print the governance summary if present.

    Honest framing: header explicitly labels these as recorded values
    tamper-evident via the bundle hash — NOT per-actor cryptographic claims.
    """
    if not gov:
        return
    print()
    print("  Governance (recorded; tamper-evident via the bundle hash):")
    pol = gov.get("policy")
    if pol:
        print(f"    policy_hash:        {pol.get('policy_hash', '')}"
              f"  ({pol.get('mandate_type', '') or 'flat'})")
    pp = gov.get("policy_profile")
    if pp:
        print(f"    policy_profile:     {pp.get('value', '')}")
    ph = gov.get("policy_hash")
    if ph and not pol:
        print(f"    policy_hash:        {ph.get('value', '')}")
    slh = gov.get("scope_lock_hash")
    if slh:
        print(f"    scope_lock_hash:    {slh.get('value', '')}")
    fsh = gov.get("fee_schedule_hash")
    if fsh:
        print(f"    fee_schedule_hash:  {fsh.get('value', '')}")
    de = gov.get("decision_envelope")
    if de:
        env_h = _short_hash(de.get("envelope_hash", ""), 16)
        print(f"    decision_envelope:  {de.get('decision', '')}"
              f"  (decision_id={de.get('decision_id', '')},"
              f" envelope_hash={env_h})")
    mid = gov.get("mandate_id")
    if mid:
        print(f"    mandate_id:         {mid.get('value', '')}")
    mr = gov.get("mandate_reviewed")
    if mr:
        print(f"    mandate_reviewed:   yes - by {mr.get('reviewer', '')}"
              f" at {_short_ts(mr.get('timestamp', ''))}")
    sla = gov.get("sla")
    if sla:
        print(f"    sla:                {sla.get('sla_id', '')}"
              f" (sla_hash={_short_hash(sla.get('sla_hash', ''), 16)})")


def _render_provenance(bundle: dict) -> None:
    """Print per-event actor attribution.

    HONEST: uses "actor=", "role=", "src=" — NEVER "signed by" or
    "Signature:". The block header makes the signing model explicit so
    the reader cannot misread label-attribution as per-actor crypto.
    """
    events = bundle.get("events") or []
    if not events:
        return
    print()
    print("  Provenance (per-event attribution; NOT per-actor signed):")
    for ev in events:
        et = ev.get("event_type", "")
        actor = ev.get("actor_id", "") or "(unknown)"
        role = ev.get("actor_role", "")
        src = ev.get("source", "")
        ts = _short_ts(ev.get("timestamp", ""))
        meta_parts = []
        if role:
            meta_parts.append(f"role={role}")
        if src:
            meta_parts.append(f"src={src}")
        meta = (" (" + ", ".join(meta_parts) + ")") if meta_parts else ""
        print(f"    {et:24s} actor={actor}{meta} @ {ts}")


def _render_signing_model(bundle: dict) -> None:
    """Render the explicit signing-model framing.

    Load-bearing honest line: states exactly what IS and ISN'T
    cryptographically signed so the auditor cannot misread per-event
    attribution as per-actor cryptographic signing.

    2.0.0 bundles: text byte-identical to 1.3.0.
    3.0.0 bundles: footer updated to reflect that per-actor signatures
    ARE present and were verified by step #6 above.
    """
    sth = bundle.get("signed_tree_head") or {}
    key_id = sth.get("key_id") or "aigentsy_log_signer_v1"
    algorithm = sth.get("algorithm") or "Ed25519"
    spec_version = bundle.get("spec_version") or ""

    # ── 3.0.0 footer (per-actor signatures present + checked above) ──
    if spec_version == "3.0.0" and bundle.get("key_directory"):
        print()
        print("  Signing model:")
        print(f"    The signed Merkle tree head ({algorithm}, key_id: {key_id})")
        print( "    attests to the aggregate event chain. Per-actor signatures")
        print( "    ARE present in this bundle for events that carry one — each")
        print( "    one was Ed25519-verified above (step #6: actor_signatures)")
        print( "    against the key_directory snapshot, with validity-at-")
        print( "    signing-time enforced. Events without an actor_signature")
        print( "    are labeled attribution-only (mixed-bundle support).")
        print( "    Governance hashes are recorded values, tamper-evident via")
        print( "    the bundle hash.")
        return

    # ── 2.0.0 footer (byte-identical to 1.3.0; no per-actor signatures) ──
    print()
    print("  Signing model:")
    print(f"    The signed Merkle tree head ({algorithm}, key_id: {key_id})")
    print( "    attests to the aggregate event chain. Per-actor signatures")
    print( "    are NOT present in this bundle - actors are attributed by")
    print( "    label only. Governance hashes (policy / decision envelope /")
    print( "    scope lock / fee schedule) are recorded values, tamper-")
    print( "    evident via the bundle hash.")


def _render_actor_signatures_step(as_step: dict) -> None:
    """Render the 6th step's PASS/FAIL line + per-event rows.

    Anti-pattern guard: this function is only invoked for 3.0.0 bundles
    (caller checks spec_version). It MUST never appear in 2.0.0 output.
    """
    if not as_step:
        return
    if as_step.get("skipped"):
        # No signed events → don't render the step at all. The 3.0.0
        # bundle shouldn't have reached this state under normal
        # assembly (key_directory only attaches when ≥1 signed event),
        # but be defensive.
        return
    signed = as_step.get("signed_count", 0)
    passed = as_step.get("passed_count", 0)
    overall = "PASS" if (signed > 0 and passed == signed) else "FAIL"
    print(f"  actor_signatures: {overall}  ({passed}/{signed} events)")


def _render_adapter_replay(adapter_step: dict) -> None:
    """Render the Pass-66 AdapterContract replay step.

    Layer-boundary statement is intentional: this step verifies
    declaration integrity + hash recomputation + allow-list membership
    + matched-rule replay. The user-authored AcceptancePolicy still
    decides whether validated signals constitute acceptable work.
    """
    if not adapter_step:
        return
    status = adapter_step.get("status", "")
    print()
    if adapter_step.get("skipped"):
        print(f"  adapter_replay:   skipped  ({status})")
        return
    overall = "PASS" if adapter_step.get("passed") else "FAIL"
    print(f"  adapter_replay:   {overall}  (status={status})")
    pwa = adapter_step.get("proofs_with_adapter", 0)
    epp = adapter_step.get("events_with_policy_snapshot", 0)
    print(f"    proofs_with_adapter:        {pwa}")
    print(f"    events_with_policy_snapshot: {epp}")
    # Per-proof status rollup
    per_proof = adapter_step.get("per_proof") or []
    for pr in per_proof:
        print(f"    proof[{pr.get('proof_index')}] "
              f"adapter_id={pr.get('adapter_id', '')}:")
        for k in (
            "adapter_contract_schema_status",
            "contract_hash_status",
            "input_schema_hash_status",
            "normalized_policy_inputs_status",
            "adapter_validator_status",
        ):
            v = pr.get(k, "")
            label = "ok" if v == "ok" else v
            print(f"      {k.replace('_status', '').replace('_', ' '):32s} {label}")
        if pr.get("schema_errors"):
            print(f"      schema_errors: {pr['schema_errors']}")
    # Per-event policy_replay rollup
    per_event = adapter_step.get("per_event") or []
    for ev in per_event:
        et = ev.get("event_type", "")
        pr = ev.get("policy_replay")
        if pr:
            print(f"    event[{ev.get('event_index')}] {et:24s} "
                  f"policy_replay={pr.get('status', '')}")


def cmd_bundle(args):
    bundle = _load_bundle(args.file)

    public_key_b64 = ""
    if args.public_key:
        try:
            public_key_b64 = load_public_key_from_file(args.public_key)
        except Exception as e:
            print(f"Error: cannot load public key: {e}", file=sys.stderr)
            sys.exit(2)
    elif args.fetch_key:
        public_key_b64 = _fetch_public_key()

    # SWARM-B: --swarm-strict selects the explicit strict swarm profile
    # (complete designated-event signature coverage + historical-time key
    # rules). Without the flag, behavior is byte-identical to the legacy
    # default profile.
    if getattr(args, "swarm_strict", False):
        from aigentsy_verify.bundle import verify_bundle_swarm_strict
        result = verify_bundle_swarm_strict(
            bundle, public_key_base64=public_key_b64)
    else:
        result = verify_bundle(bundle, public_key_base64=public_key_b64)

    # AdapterContract replay as an additive verifier step.
    # Runs AFTER verify_bundle so bundle.py stays off-limits (the
    # bundle.py invariant). Skipped (legacy_no_adapter) does not fail;
    # any non-ok sub-status flips overall verified to False.
    #
    # Byte-identity invariant: a 2.0.0 bundle with NO
    # adapter_evaluation anywhere — i.e., truly pre-Pass-65 — gets the
    # exact same CLI output it always did. The step is only added when
    # the bundle actually carries adapter data to replay.
    from aigentsy_verify.adapter import verify_adapter_replay
    _adapter_step = verify_adapter_replay(bundle)
    _has_adapter_data = (
        _adapter_step.get("proofs_with_adapter", 0) > 0
        or _adapter_step.get("events_with_policy_snapshot", 0) > 0
    )
    if _has_adapter_data:
        result["steps"]["adapter_replay"] = {
            "passed": bool(_adapter_step.get("passed")),
            "skipped": bool(_adapter_step.get("skipped")),
            "status": _adapter_step.get("adapter_replay_status"),
            "proofs_with_adapter": _adapter_step.get("proofs_with_adapter", 0),
            "events_with_policy_snapshot": _adapter_step.get(
                "events_with_policy_snapshot", 0,
            ),
            "per_proof": _adapter_step.get("per_proof", []),
            "per_event": _adapter_step.get("per_event", []),
        }
        # If adapter replay actually ran and failed, flip overall verified.
        if not _adapter_step.get("skipped") and not _adapter_step.get("passed"):
            result["verified"] = False
        # Update steps_run/skipped counters to include the new step.
        if _adapter_step.get("skipped"):
            result["steps_skipped"] = result.get("steps_skipped", 0) + 1
        else:
            result["steps_run"] = result.get("steps_run", 0) + 1

    if args.json:
        json.dump(result, sys.stdout, indent=2, default=str)
        print()
        sys.exit(0 if result["verified"] else 1)

    steps = result.get("steps", {})
    trace = bundle.get("agent_trace", [])
    level = result.get("verification_level", "unknown")

    print()
    print("AiGentsy ProofPack verification")
    print()
    print(f"  deal_id:          {result.get('deal_id', 'N/A')}")
    print(f"  spec_version:     {result.get('spec_version') or 'legacy'}")
    print(f"  proofs:           {result.get('proof_count', 0)}")
    print(f"  events:           {result.get('event_count', 0)}")
    print()

    bh = steps.get("bundle_hash", {})
    ec = steps.get("event_chain", {})
    mi = steps.get("merkle_inclusion", {})
    ss = steps.get("sth_signature", {})
    cr = steps.get("cross_reference", {})

    print(f"  bundle_hash:      {_status(bh.get('passed', False))}")
    print(f"  event_chain:      {_status(ec.get('passed', False))}  ({ec.get('event_count', 0)} events)")
    print(f"  merkle_inclusion: {_status(mi.get('passed', False), mi.get('skipped', False), 'no inclusion data')}")
    print(f"  sth_signature:    {_status(ss.get('passed', False), ss.get('skipped', False), 'no public key — use --fetch-key or --public-key')}")
    print(f"  cross_reference:  {_status(cr.get('passed', False), cr.get('skipped', False), 'no STH or inclusion')}")

    # The 6th step appears ONLY on 3.0.0 bundles. For
    # 2.0.0 bundles, steps["actor_signatures"] is never set (the
    # verify_bundle dispatch in bundle.py only adds it on spec_version
    # == "3.0.0"), so this branch is dead for every existing bundle —
    # preserving byte-identity to 1.3.0 output.
    if result.get("spec_version") == "3.0.0" and "actor_signatures" in steps:
        _render_actor_signatures_step(steps["actor_signatures"])

    if trace:
        print(f"\n  agent_trace:      {len(trace)} roles")
        for t in trace:
            print(f"    {t.get('role', ''):22s} {t.get('event', '')}")

    # For 3.0.0 bundles, render per-event signature
    # rows after agent_trace. Honest labels: PASS / FAIL /
    # attribution-only — never "signed by X" or unlabeled "Signature: PASS".
    if result.get("spec_version") == "3.0.0" and "actor_signatures" in steps:
        as_step = steps["actor_signatures"]
        ev_rows = as_step.get("events", [])
        if ev_rows:
            print(f"\n  actor_signatures per event:")
            for r in ev_rows:
                label = r.get("result", "")  # PASS | FAIL | attribution-only
                et = r.get("event_type", "")
                kid = r.get("key_id") or "(no key_id)"
                print(f"    {et:24s} {label:18s} key={kid}")
                if label == "FAIL" and r.get("reason"):
                    print(f"      reason: {r['reason']}")

    # Tier-1 additions: surface governance + per-event provenance + the
    # signing-model framing line. All three render existing bundle data —
    # no new cryptographic claims, no per-actor "signed by" / "PASS" lines.
    _render_governance(bundle.get("governance_summary") or {})
    _render_provenance(bundle)
    _render_signing_model(bundle)

    # AdapterContract replay. New per-step statuses inside
    # offline verification. Legacy bundles (no embedded adapter_contract)
    # report `legacy_no_adapter` and the step is skipped — old bundles
    # never fail on this account. Fresh adapter-backed bundles report
    # ok across every sub-check.
    _render_adapter_replay(steps.get("adapter_replay") or {})

    # SWARM-B strict swarm profile: render coverage + snapshot steps.
    # Only present when --swarm-strict was passed; legacy output is
    # untouched otherwise.
    if "swarm_coverage" in steps:
        cov = steps["swarm_coverage"]
        print(f"\n  swarm_coverage:   {_status(cov.get('passed', False))}")
        for etype, row in (cov.get("per_type") or {}).items():
            print(f"    {etype:24s} {row.get('passed', 0)}/{row.get('present', 0)} signed")
        for err in (cov.get("errors") or []):
            print(f"      reason: {err}")
        snap = steps.get("swarm_snapshot") or {}
        print(f"  swarm_snapshot:   "
              f"{_status(snap.get('passed', False), snap.get('skipped', False), 'no snapshot section')}")
        for err in (snap.get("errors") or []):
            print(f"      reason: {err}")

    print()
    verified = result["verified"]

    if args.strict and ss.get("skipped"):
        verified = False
        print(f"  verified:         false")
        print(f"  reason:           --strict requires STH signature (use --fetch-key or --public-key)")
    else:
        print(f"  verified:         {str(verified).lower()}")
        steps_run = result.get("steps_run", "?")
        steps_total = steps_run + result.get("steps_skipped", 0)
        print(f"  level:            {level} ({steps_run}/{steps_total} steps)")

    print()
    sys.exit(0 if verified else 1)


def main():
    # Handle bare `aigentsy-verify file.json` shortcut
    if len(sys.argv) >= 2 and sys.argv[1].endswith(".json"):
        sys.argv.insert(1, "bundle")

    parser = argparse.ArgumentParser(
        prog="aigentsy-verify",
        description="Standalone offline verification for AiGentsy ProofPack bundles.",
    )
    parser.add_argument("--version", action="version", version=f"aigentsy-verify {__version__}")

    sub = parser.add_subparsers(dest="command")

    bundle_p = sub.add_parser("bundle", help="Verify a ProofPack bundle JSON file")
    bundle_p.add_argument("file", help="Path to ProofPack bundle JSON")
    bundle_p.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    bundle_p.add_argument("--strict", action="store_true", help="Fail if STH signature verification is skipped")
    bundle_p.add_argument(
        "--swarm-strict", action="store_true", dest="swarm_strict",
        help="Strict swarm profile: additionally require complete, "
             "temporally-valid actor-signature coverage of the bundle's "
             "designated swarm event set")
    bundle_p.add_argument("--fetch-key", action="store_true", help="Fetch Ed25519 public key from AiGentsy runtime for STH verification")
    bundle_p.add_argument("--public-key", help="Path to Ed25519 public key PEM file")

    args = parser.parse_args()

    if args.command == "bundle":
        cmd_bundle(args)
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
