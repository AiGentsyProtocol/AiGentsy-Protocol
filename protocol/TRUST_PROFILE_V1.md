# Trust / Reputation Profile — Specification v1

**Status:** v1 (ed25519 signed, offline-verifiable)
**Module:** `protocol.trust_profile`
**Embedding path:** ProofPack `evidence.trust_profile`

## 1. Purpose

Trust Profile v1 summarizes an agent's accumulated reliability across
governed compute, authority compliance, coordination obligations, proof
completion, acceptance outcomes, and value release.

Six primitives now coexist:

- **HoverStack** — compute governance
- **Mandate Graph** — authority
- **Coordination Graph** — obligations & dependency
- **Value Flow Graph** — value allocation & release conditions
- **Trust Profile** — accumulated reliability & trust posture
- **ProofPack / GEP** — work proof / acceptance / downstream gating

## 2. Reused AiGentsy Logic

v1 wraps (does not replace) the existing OCS engine
(`brain_overlay/ocs.py`) and the W3C VC attestation path
(`protocol/reputation_attestation.py`). The `ocs_score` and `ocs_tier`
fields on the profile come directly from the OCS calculation. This
module adds structured trust signals, work-class-specific strengths,
and explicit negative signals alongside the canonical OCS number.

## 3. Schema

```
spec_version                        str
profile_id                          str     "tp_<16-hex>"
created_at                          str     ISO-8601
subject_agent                       str
issuer                              str
policy_version                      str
ocs_score                           float   0-100 (from existing OCS engine)
ocs_tier                            str     elite|trusted|standard|probation|restricted
trust_signals                       [TrustSignal]
work_class_strengths                [WorkClassStrength]
dispute_count                       int
failed_acceptance_count             int
release_failure_count               int
coordination_failure_count          int
delegation_violation_count          int
total_proofs_completed              int
total_mandates_complied             int
total_coordination_nodes_completed  int
total_value_released                float
sample_source_refs                  [str]
algorithm                           str
public_key                          str
profile_hash                        str
signature                           str
```

## 4. Trust Signal Categories

```
governed_compute_reliability
authority_compliance
coordination_reliability
proof_completion_reliability
acceptance_reliability
dispute_frequency
release_reliability
delegation_reliability
refusal_quality
```

Each TrustSignal carries: category, score (0-1), sample_count,
source_refs, work_class, last_updated.

## 5. ProofPack Embedding

```
proof.evidence.trust_profile = { ...profile dict... }
```

Peer to all other evidence primitives. All six coexist.

## 6. Evaluation

Deterministic methods on the profile:
- `positive_signals()` — signals with score > 0.5
- `negative_signals()` — signals with score ≤ 0.5 and samples > 0
- `strongest_work_classes(k)` / `weakest_work_classes(k)`
- `negative_signal_count()` — aggregate of all negative counters
- `evidence_backed()` — bool; True if real observations exist
- `summary()` — compact operator-facing dict
