"""Human-readable report for delta-savings curve (uniform + localized)."""

import json
from typing import Any, Dict


def generate_report(results: Dict[str, Any]) -> str:
    lines = [
        "=" * 70,
        "DELTA-SAVINGS CURVE REPORT (Uniform vs Localized)",
        "=" * 70,
        "",
        f"Adapter: {results.get('adapter', '')} | Model: {results.get('model', '')}",
        f"Base prompt: {results.get('base_prompt_tokens', 0)} tokens",
        f"Pairs per point: {results.get('pairs_per_point', 0)}",
        "",
        f"{'Diff %':>8} | {'Uniform Savings':>16} {'Mode':>14} | {'Localized Savings':>18} {'Mode':>14}",
        "-" * 70,
    ]

    for p in results.get("points", []):
        u = p.get("uniform", {})
        l = p.get("localized", {})
        lines.append(
            f"{p['diff_percent']:>7}% | "
            f"{u.get('avg_savings_percent', 0):>15.1f}% {u.get('dominant_mode', ''):>13s} | "
            f"{l.get('avg_savings_percent', 0):>17.1f}% {l.get('dominant_mode', ''):>13s}"
        )

    be = results.get("breakeven_thresholds", {})
    for dist in ("uniform", "localized"):
        d = be.get(dist, {})
        lines += ["", f"--- BREAKEVEN: {dist.upper()} ---"]
        for key, val in d.items():
            label = key.replace("diff_percent_at_", "").replace("_savings", "% savings")
            lines.append(f"  {label}: {val if val is not None else 'never drops below'}% diff")

    lines += ["", "--- WHAT IS NOT CLAIMED ---"]
    for note in results.get("what_is_not_claimed", []):
        lines.append(f"  - {note}")
    lines.append("=" * 70)

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    with open(sys.argv[1] if len(sys.argv) > 1 else "data/delta_savings_curve.json") as f:
        print(generate_report(json.load(f)))
