"""
ProofPack v2 Policy Layer Parser
==================================

Parses and displays the policy_layer from ProofPack v2 bundles.

Usage:
    from aigentsy_verify.policy_layer import parse_policy_layer, format_policy_summary
    policy = parse_policy_layer(bundle)
    print(format_policy_summary(policy))
"""

from typing import Any, Dict, List


def parse_policy_layer(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Extract and validate the policy_layer from a ProofPack v2 bundle."""
    policy = bundle.get("policy_layer")
    if not policy or not isinstance(policy, dict):
        return {"version": "1.0", "has_policy": False}

    result = {"version": "2.0", "has_policy": True, "sections": []}

    for key in ("sla", "mandate", "spawn", "attestation", "outcome"):
        val = policy.get(key)
        if val and isinstance(val, dict):
            result[key] = val
            result["sections"].append(key)

    referral = policy.get("referral_chain")
    if referral and isinstance(referral, list) and len(referral) > 0:
        result["referral_chain"] = referral
        result["sections"].append("referral_chain")

    return result


def format_policy_summary(policy: Dict[str, Any]) -> str:
    """Format a human-readable policy layer summary."""
    if not policy.get("has_policy"):
        return "ProofPack v1 — no policy layer"

    lines = [f"ProofPack v2 — {len(policy.get('sections', []))} policy sections"]

    if "sla" in policy:
        s = policy["sla"]
        g = s.get("guarantees", s)
        lines.append(f"  SLA: delivery {g.get('delivery_hours', '?')}h, quality >= {g.get('quality_floor', '?')}")

    if "attestation" in policy:
        a = policy["attestation"]
        lines.append(f"  Trust: OCS {a.get('ocs_score', 0)} ({a.get('ocs_tier', '')})")

    if "referral_chain" in policy:
        lines.append(f"  Referrals: {' -> '.join(policy['referral_chain'])}")

    if "outcome" in policy:
        o = policy["outcome"]
        lines.append(f"  Outcome: {o.get('metric', '')} >= {o.get('threshold', 0)}")

    lines.append("  Note: Policy layer is commercial context, not cryptographically verified.")
    return "\n".join(lines)
