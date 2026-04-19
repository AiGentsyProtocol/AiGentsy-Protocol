# Commitment / Coordination Graph — Specification v1

**Status:** v1 (ed25519 signed, offline-verifiable)
**Module:** `protocol.coordination_graph`
**Embedding path:** ProofPack `evidence.coordination_graph`

## 1. Purpose

Coordination Graph v1 models how multiple authorized agents and
dependent work commitments are structured, constrained, satisfied,
and unlocked before downstream consequences. It is the coordination
primitive in AiGentsy Stack.

Four primitives now coexist:

- **HoverStack** — compute governance
- **Mandate Graph** — authority
- **Coordination Graph** — multi-agent obligations and dependency
- **ProofPack / GEP** — work proof / acceptance / downstream gating

## 2. Schema

### Graph envelope

```
spec_version          str    "coordination_graph/v1"
graph_id              str    "cg_<16-hex>"
created_at            str    ISO-8601
issuer                str
policy_version        str
commitments           [CommitmentNode]
algorithm             str    "ed25519" | "hmac-sha256"
public_key            str
graph_hash            str    SHA-256 over canonical content
signature             str
```

### CommitmentNode

```
commitment_id                  str
work_label                     str
responsible_agent              str
required_mandate_id            str
work_class                     str
status                         str    pending | ready | in_progress |
                                      completed | accepted | blocked |
                                      failed | escalated
depends_on                     [str]  commitment_ids this node waits for
parallelizable                 bool
joint_completion_group         str    group ID for joint completion
required_proof_types           [str]
required_acceptance_state      str
unlocks_consequences           [str]  e.g. ["settlement_request", "release"]
allowed_downstream_actions     [str]
deadline                       str    ISO-8601 or empty
failure_mode                   str    "escalate" | "fail" | "retry"
```

## 3. Graph Model

DAG with optional join groups:

```
[A: research]  →  [B: draft]  →  [D: review]  →  [E: release]
                  [C: compliance] ──┘
                  (joint group "review_gate": B + C must both complete)
```

- Sequential: `B.depends_on = ["A"]`
- Parallel: `B.parallelizable = True, C.parallelizable = True`
- Join: `B.joint_completion_group = "review_gate"`,
  `C.joint_completion_group = "review_gate"`

Constraints narrow down the chain; no node can unlock consequences
beyond what its predecessors permit.

## 4. Status Model

```
pending → ready → in_progress → completed → accepted
                              → failed → escalated
blocked (when dependencies unmet)
```

## 5. Transition Evaluation

`evaluate_transition(graph, commitment_id, new_status=..., ...)`
checks: signature valid, node exists, agent matches, dependencies
satisfied, joint group complete, required proofs available, acceptance
met, status transition valid.

Returns `CoordinationEvaluation(valid, checks_passed, checks_failed,
reason)`.

## 6. ProofPack Embedding

```
proof.evidence.coordination_graph = { ...graph dict... }
```

Peer to `evidence.mandate`, `evidence.governance_attestation`, and
`evidence.hoverstamp`. A ProofPack MAY carry any combination.

## 7. Consequence Unlock

A node's `unlocks_consequences` list names what downstream actions
become available when the node (or its joint group) reaches the
required state. Advisory in v1 — enforcement is the caller's or
acceptance layer's responsibility.

## 8. Evaluation Algorithm — `evaluate_transition()`

Deterministic, auditable. 8 checks. A transition is valid if and only
if the failed list is empty.

```
function evaluate_transition(graph, commitment_id, context):
    passed = []
    failed = []

    # 1. Graph signature integrity
    if verify_signature(graph):
        passed.append("graph_signature_valid")
    else:
        failed.append("graph_signature_invalid")

    # 2. Node exists
    node = graph.find_node(commitment_id)
    if node is null:
        failed.append("commitment_not_found")
        return { valid: false, passed, failed }
    passed.append("commitment_exists")

    # 3. Agent matches
    if context.acting_agent is provided:
        if node.responsible_agent == context.acting_agent:
            passed.append("agent_matches")
        else:
            failed.append("agent_mismatch")

    # 4. Dependencies satisfied (DAG resolution)
    for each dep_id in node.depends_on:
        dep_node = graph.find_node(dep_id)
        if dep_node AND dep_node.status in ("completed", "accepted"):
            passed.append("dep_satisfied:" + dep_id)
        elif dep_id in context.accepted_commitments:
            passed.append("dep_satisfied_external:" + dep_id)
        else:
            failed.append("dep_not_satisfied:" + dep_id)

    # 5. Joint completion group
    if node.joint_completion_group is set:
        group = all nodes sharing that group name
        if all other members are completed/accepted:
            passed.append("joint_group_satisfied")
        else:
            failed.append("joint_group_incomplete")

    # 6. Required proofs
    for each proof_type in node.required_proof_types:
        if proof_type in context.available_proofs:
            passed.append("proof_available:" + proof_type)
        else:
            failed.append("proof_missing:" + proof_type)

    # 7. Required acceptance
    if node.required_acceptance_state is set:
        check against node status or external accepted set

    # 8. Status transition validity
    if context.new_status is provided:
        if new_status not in VALID_STATUSES:
            failed.append("invalid_status")
        elif node.status == "blocked" AND length(failed) > 0:
            failed.append("cannot_transition_while_blocked")
        else:
            passed.append("status_transition_ok")

    valid = (length(failed) == 0)
    return { valid, passed, failed }
```

Execution order: nodes with empty `depends_on` may execute immediately.
Nodes with dependencies execute only after all dependencies are
completed/accepted. Joint completion groups must all reach the
required state before any member's consequence unlocks.
