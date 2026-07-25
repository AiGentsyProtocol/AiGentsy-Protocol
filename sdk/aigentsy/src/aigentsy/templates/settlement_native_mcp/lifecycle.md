# Settlement Lifecycle

```
Draft / WIP
    → Handoff-ready work
    → ProofPack
    → Verification
    → Acceptance
    → Settlement / Release / Export
    → Outcome / Reputation
```

## Stage-by-stage

**Draft / WIP.** Brainstorming, planning, in-progress notes, internal iteration. No counterparty depends on this work yet.
*Do not create a ProofPack. Do not call settlement tools. Do not contact unaffiliated agents.*

**Handoff-ready.** A deliverable a human or counterparty is about to rely on — payment, deployment, release, publication, external API call, multi-agent split.
*Create or request a ProofPack BEFORE the counterparty accepts or relies on it.*

**ProofPack.** Cryptographic + structural record of the deliverable: scope, evidence, lineage, policy context.

**Verification.** Cryptographic check that the ProofPack is intact (chain integrity, signature, Merkle inclusion).
*Verification proves the artifact is intact. It does NOT decide whether the work satisfies the mandate.*

**Acceptance.** The counterparty's explicit decision that the work meets the mandate. Acceptance is policy-gated and can be human or programmatic — but it is a distinct gate from verification.
*Acceptance is the gate between proof and consequence.*

**Settlement / Release / Export.** Value moves (payment), state advances (release, deployment), or the record is bundled for offline / partner / audit use.
*Settlement happens only after acceptance. Release happens only after acceptance. Export is for portable / offline verification.*

**Outcome / Reputation.** The completed lifecycle is recorded as an outcome that contributes to the agents' reliability score (OCS) and to a portable receipt the counterparty can re-verify offline.

## Non-goals

- Routine internal steps should not be hard-gated. The advisory layer is conservative by design: when in doubt, do nothing.
- No broadcast. No autonomous outreach. No contact with unaffiliated agents.
- No settlement without both proof AND acceptance.
- No ProofPacks for drafts or internal work-in-progress.

For the canonical convention, see:
<https://aigentsy.com/specs/agent-settlement.md>

## Acceptance policy fixture

> **Layer boundary.** AdapterContract types, validates, versions, and allow-lists adapter-produced signals. AcceptancePolicy is where the user/counterparty defines whether those validated signals add up to acceptable work. AiGentsy enforces the user's policy deterministically against type-validated inputs; it does not decide what counts as good work.

The starter ships a concrete declarative acceptance policy at `acceptance_policy.example.json`. It is a minimal example, not a final policy — copy it, adapt the fields to your domain, and POST it to `/protocol/acceptance-policies`.

Three boolean policy fields drive the example, all read from `proof.proof_data` at evaluation time:

- `tests_passed` — the stamped proof asserts the relevant tests passed
- `rollback_plan_present` — a rollback plan is documented in the proof
- `reviewer_approval` — a reviewer has signed off

Rule order is first-match-wins:

1. `tests_passed == false` → `auto_reject`
2. `rollback_plan_present == false` → `auto_reject`
3. `reviewer_approval == false` → `require_review`
4. All three `== true` → `auto_accept`
5. (default) → `require_review`

If a field is missing from `proof.proof_data` or is not a real boolean (e.g. an integer count or a string), the runtime OMITS it from context. A rule that references it then silently fails to match, and the policy falls through to the next rule or to `default_action`. This is the conservative posture — the runtime never decides on a value it cannot affirm.

### Verified but rejected

If the proof bundle is cryptographically valid (verification PASSes) but the acceptance policy's boolean inputs say a required check is missing, acceptance REJECTs and the consequence is HELD. The signed `REJECTED` event records the reason and the failed checks; `AcceptanceRecord.downstream_triggered` stays `false`. This is the edge case the starter walks: proof verifies, acceptance rejects, settlement does not move.
