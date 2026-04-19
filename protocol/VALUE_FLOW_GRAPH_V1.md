# Value Flow / Settlement Graph — Specification v1

**Status:** v1 (ed25519 signed, offline-verifiable)
**Module:** `protocol.value_flow_graph`
**Embedding path:** ProofPack `evidence.value_flow_graph`

## 1. Purpose

Value Flow Graph v1 models how value is apportioned across coordinated
autonomous work: who is entitled to what, under what conditions, after
which proofs/acceptances, with what splits, holds, and contingencies.

Five primitives now coexist:

- **HoverStack** — compute governance
- **Mandate Graph** — authority
- **Coordination Graph** — obligations & dependency
- **Value Flow Graph** — value allocation & release conditions
- **ProofPack / GEP** — work proof / acceptance / downstream gating

## 2. Schema

### Graph envelope

```
spec_version         str    "value_flow_graph/v1"
value_graph_id       str    "vfg_<16-hex>"
created_at           str    ISO-8601
issuer               str
policy_version       str
claims               [ValueClaim]
algorithm            str    "ed25519" | "hmac-sha256"
public_key           str
value_graph_hash     str    SHA-256 over canonical content
signature            str
```

### ValueClaim

```
claim_id                     str
claim_label                  str
beneficiary                  str
source_commitment_id         str
required_mandate_id          str
amount                       float
share                        float   (0-1 fractional)
asset_type                   str     e.g. "USD"
status                       str     pending | held | eligible | released |
                                     completed | disputed | reverted | failed
depends_on_claims            [str]   claim_ids
depends_on_commitments       [str]   commitment_ids from coordination graph
requires_acceptance          bool
requires_proof_types         [str]
release_conditions           [str]
hold_reason                  str
dispute_state                str
reversion_target             str     claim_id for fallback
unlocks_downstream_value     [str]   claim_ids unlocked on release
deadline                     str     ISO-8601 or empty
parent_claim_id              str     for split children
```

## 3. Graph Model

DAG with splits and contingent release:

```
[root_claim: $1000 to project]
  ├─ [split_A: $600 to agent_1] depends_on_commitments=["draft"]
  ├─ [split_B: $300 to agent_2] depends_on_commitments=["compliance"]
  └─ [split_C: $100 to platform] depends_on_claims=["split_A", "split_B"]
```

`split_C` releases only after both `split_A` and `split_B` are released.

## 4. Status Model

```
pending → held → eligible → released → completed
                          → disputed → reverted
                          → failed
```

## 5. Release Evaluation

`evaluate_release(graph, claim_id, ...)` checks: signature, claim
exists, beneficiary, status (not disputed/reverted/failed), deadline,
hold, claim deps, commitment deps, required proofs, acceptance.
Returns `ValueEvaluation(valid, checks_passed, checks_failed, reason)`.

## 6. ProofPack Embedding

```
proof.evidence.value_flow_graph = { ...graph dict... }
```

Peer to all other evidence primitives. All five coexist.

## 7. Holds / Disputes / Reversion

- `hold_reason` blocks release with a stated reason.
- `dispute_state` prevents release while active.
- `reversion_target` names the claim that receives value if this
  claim fails or reverts.
- All advisory in v1 — enforcement is the acceptance/settlement
  layer's responsibility.

## 8. Evaluation Algorithm — `evaluate_release()`

Deterministic, auditable. 10 checks. A claim is eligible for release
if and only if the failed list is empty.

```
function evaluate_release(graph, claim_id, context):
    passed = []
    failed = []

    # 1. Graph signature integrity
    if verify_signature(graph):
        passed.append("graph_signature_valid")
    else:
        failed.append("graph_signature_invalid")

    # 2. Claim exists
    claim = graph.find_claim(claim_id)
    if claim is null:
        failed.append("claim_not_found")
        return { valid: false, passed, failed }
    passed.append("claim_exists")

    # 3. Beneficiary match
    if context.beneficiary is provided:
        if claim.beneficiary == context.beneficiary:
            passed.append("beneficiary_matches")
        else:
            failed.append("beneficiary_mismatch")

    # 4. Status check
    if claim.status in ("disputed", "reverted", "failed"):
        failed.append("claim_" + claim.status)
    elif claim.status in ("released", "completed"):
        passed.append("already_" + claim.status)
    else:
        passed.append("status_ok")

    # 5. Deadline
    if claim.deadline AND claim.deadline < now:
        failed.append("claim_expired")
    else:
        passed.append("not_expired")

    # 6. Hold
    if claim.status == "held" AND claim.hold_reason:
        failed.append("held:" + claim.hold_reason)

    # 7. Claim dependencies (other claims that must release first)
    for each dep_id in claim.depends_on_claims:
        dep = graph.find_claim(dep_id)
        if dep AND dep.status in ("released", "completed"):
            passed.append("claim_dep_satisfied:" + dep_id)
        elif dep_id in context.released_claims:
            passed.append("claim_dep_satisfied_external:" + dep_id)
        else:
            failed.append("claim_dep_not_released:" + dep_id)

    # 8. Commitment dependencies
    for each cmt_id in claim.depends_on_commitments:
        if cmt_id in context.satisfied_commitments OR
           cmt_id in context.accepted_commitments:
            passed.append("commitment_satisfied:" + cmt_id)
        else:
            failed.append("commitment_not_satisfied:" + cmt_id)

    # 9. Required proofs
    for each proof_type in claim.requires_proof_types:
        if proof_type in context.available_proofs:
            passed.append("proof_available:" + proof_type)
        else:
            failed.append("proof_missing:" + proof_type)

    # 10. Required acceptance
    if claim.requires_acceptance:
        acceptance_sources = { claim_id, claim.source_commitment_id }
                             ∪ claim.depends_on_commitments
        if acceptance_sources ∩ context.accepted_commitments ≠ ∅:
            passed.append("acceptance_met")
        else:
            failed.append("acceptance_not_met")

    valid = (length(failed) == 0)
    return { valid, passed, failed }
```

Split integrity invariant: for all claims in a graph, the sum of
`splits[].fraction` must equal 1.0 for each unique `source_commitment_id`.
