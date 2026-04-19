# Mandate Graph — Specification v1

**Status:** v1 (ed25519 signed, offline-verifiable)
**Module:** `protocol.mandate_graph`
**Embedding path:** ProofPack `evidence.mandate`

## 1. Purpose

Mandate Graph v1 is the authority layer for AiGentsy Stack. It proves
which agent was authorized to do which work, under what scope, under
what constraints, and with what downstream consequence rights.

Three primitives now coexist:

- **HoverStack** — how computation was governed.
- **Mandate Graph** — who was authorized to act.
- **ProofPack / GEP** — that work was completed, accepted, and governed.

## 2. Non-Claims

- Does NOT prove the work was completed correctly (that's ProofPack).
- Does NOT prove the compute path was governed (that's GEP).
- Does NOT implement distributed revocation infrastructure (v1 is
  portable revocation state only).
- Does NOT require blockchain or network for verification.

## 3. Schema

```
spec_version             str    "mandate_graph/v1"
mandate_id               str    "mnd_<16-hex>"
issuer                   str    who grants authority
subject_agent            str    who receives authority
parent_mandate_id        str?   for delegation chains
delegation_depth         int    0 = root mandate
issued_at                str    ISO-8601
expires_at               str    ISO-8601 or empty
revoked_at               str    ISO-8601 or empty (= not revoked)
scope                    dict   arbitrary scope constraints
allowed_actions          [str]  e.g. ["proof_create", "settlement_request"]
forbidden_actions        [str]  explicit denials
work_class               [str]  e.g. ["contract_review", "clinical_qa"]
delegation_allowed       bool
max_delegation_depth     int    0 = no further delegation
consequence_rights       [str]  e.g. ["settlement_request", "release"]
proof_requirements       [str]  e.g. ["completion_photo"]
acceptance_requirements  [str]  e.g. ["human_review"]
policy_version           str
algorithm                str    "ed25519" | "hmac-sha256"
public_key               str    hex ed25519 public key (empty for HMAC)
mandate_hash             str    SHA-256 over canonical content
signature                str    ed25519 or HMAC signature
```

## 4. Graph Model

v1 supports a simple parent-child chain:

```
Root Mandate (issuer: platform, subject: agent_A)
  └─ Delegated Mandate (issuer: agent_A, subject: agent_B)
       └─ Sub-delegated Mandate (issuer: agent_B, subject: agent_C)
```

Constraints can only narrow during delegation:
- Child `allowed_actions` must be a subset of parent's.
- Child `work_class` must be a subset of parent's.
- `delegation_depth` increments per hop.
- Delegation stops when `delegation_depth >= max_delegation_depth`.

## 5. Signing

Same rules as GEP v1.1: ed25519 preferred, HMAC-SHA256 fallback.
Canonical serialization: sort_keys, ensure_ascii, 6-decimal floats.
`mandate_hash` and `signature` excluded from hash input.

## 6. Validity Evaluation

`evaluate_mandate(mandate, requested_action=..., ...)` checks:

1. Signature valid
2. Not expired
3. Not revoked
4. Subject matches
5. Action within allowed_actions and not in forbidden_actions
6. Work class permitted
7. Consequence right authorized

Returns `MandateEvaluation(valid, checks_passed, checks_failed, reason)`.
Deterministic and auditable.

## 7. ProofPack Embedding

```
proof.evidence.mandate = { ...mandate dict... }
```

Peer to `evidence.hoverstamp` and `evidence.governance_attestation`.
A ProofPack MAY carry any combination of the three. Absence of mandate
is the normal state for unconstrained work.

## 8. Consequence Rights

A mandate can express what downstream actions the agent is authorized
to request: `settlement_request`, `release`, `access_grant`,
`task_delegation`, `state_change`. These are advisory in v1 — the
acceptance/settlement layer checks them if configured to do so.

## 9. Evaluation Algorithm — `evaluate_mandate()`

Deterministic, auditable. Returns a list of passed and failed checks.
A mandate is valid if and only if all 7 checks pass (failed list is empty).

```
function evaluate_mandate(mandate, context):
    passed = []
    failed = []

    # 1. Signature integrity
    if verify_signature(mandate):
        passed.append("signature_valid")
    else:
        failed.append("signature_invalid")

    # 2. Expiry check
    if mandate.expires_at AND mandate.expires_at < now:
        failed.append("expired")
    else:
        passed.append("not_expired")

    # 3. Revocation check
    if mandate.revoked_at is set:
        failed.append("revoked")
    else:
        passed.append("not_revoked")

    # 4. Subject agent match
    if context.subject_agent is provided:
        if mandate.subject_agent == context.subject_agent:
            passed.append("subject_matches")
        else:
            failed.append("subject_mismatch")
    else:
        passed.append("subject_not_checked")

    # 5. Action within scope
    if context.requested_action is provided:
        if requested_action in mandate.forbidden_actions:
            failed.append("action_forbidden")
        elif mandate.allowed_actions is non-empty AND
             requested_action NOT in mandate.allowed_actions:
            failed.append("action_not_allowed")
        else:
            passed.append("action_allowed")
    else:
        passed.append("action_not_checked")

    # 6. Work class
    if context.requested_work_class is provided:
        if mandate.work_class is non-empty AND
           requested_work_class NOT in mandate.work_class:
            failed.append("work_class_not_permitted")
        else:
            passed.append("work_class_ok")
    else:
        passed.append("work_class_not_checked")

    # 7. Consequence rights
    if context.requested_consequence is provided:
        if mandate.consequence_rights is non-empty AND
           requested_consequence NOT in mandate.consequence_rights:
            failed.append("consequence_not_authorized")
        else:
            passed.append("consequence_authorized")
    else:
        passed.append("consequence_not_checked")

    valid = (length(failed) == 0)
    return { valid, passed, failed }
```

Delegation chain narrowing: a child mandate's allowed_actions, work_class,
and consequence_rights MUST be subsets of its parent's. Verification
traverses the chain upward; if any ancestor fails, the descendant fails.
