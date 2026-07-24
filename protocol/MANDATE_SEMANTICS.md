<!-- BEGIN PUBLIC DISTRIBUTION PROVENANCE -->
> **Public distribution mirror.** Existing mandate semantics — **no new authority**.
> Implementation source: `protocol/MANDATE_SEMANTICS.md` @ `c05759b5eb34abad82ea530e85fa0a2e56dcd84b`.
> The content below the provenance block is an exact reviewed distribution copy; behavioral
> authority remains with the implementation source and its tests. `mandate_id` remains
> caller-attributed and does not establish verified legal, employer, tenant, role, or
> delegation authority. Report drift via this repository's issue tracker.
<!-- END PUBLIC DISTRIBUTION PROVENANCE -->

# Mandate Semantics (as-built)

This documents the mandate-related interface that **exists today** in the AiGentsy
runtime, so an integrator can use it without inferring semantics. It describes
current behavior only — it does **not** define a new mandate language, authority,
or validation regime. For the signed, delegatable authority artifact see the
companion spec [`MANDATE_GRAPH_V1.md`](./MANDATE_GRAPH_V1.md); this file does not
duplicate it.

There are **three distinct mandate mechanisms**. They are not a single object:

| Mechanism | Module | Identity prefix | Signed? | Role today |
|---|---|---|---|---|
| **BuyerMandate** | `protocol/buyer_mandate.py` | `mnd_` | No | Flat buyer spending permission used by auto-GO / exact-consequence amount authority. |
| **ProgrammableMandate** | `protocol/programmable_mandate.py` | `pmnd_` | No (policy hash only) | First-match rule policy over deal attributes; returns an action. |
| **Mandate Graph v1** | `protocol/mandate_graph.py` | `mnd_` (16-hex) | Yes (Ed25519/HMAC) | Portable, offline-verifiable, delegatable authority artifact embedded in a ProofPack. Separate from the deal-flow paths above. |

---

## 1. BuyerMandate — field reference

Source: `protocol/buyer_mandate.py` (dataclass `BuyerMandate`; request model `CreateMandateRequest`).

| Field | Type | Default | Notes |
|---|---|---|---|
| `mandate_id` | str | generated `mnd_<uuid12>` | Identifier. |
| `buyer_id` | str | — (required) | Buyer agent id. **No** organization/tenant field. |
| `status` | str | `ACTIVE` | Enum: `ACTIVE` \| `PAUSED` \| `REVOKED`. |
| `created_at` / `updated_at` | str | ISO-8601 now | Timestamps. |
| `stripe_customer_id` / `stripe_payment_method_id` | str | `""` | Payment context (spend-oriented). |
| `max_amount_per_deal_usd` | float | `500.0` | Per-deal cap (`gt=0`). Enforced at auto-GO and exact-consequence time. |
| `max_amount_per_day_usd` | float | `0.0` | `0` = unlimited (not enforced in current code). |
| `allowed_verticals` | List[str] | `["marketing","saas","ecommerce"]` | Vertical allowlist checked at auto-GO time. |
| `confidence_threshold` | float | `0.85` | Min proof confidence (`ge=0, le=1`). |
| `require_proof_view_above_usd` | float | `0.0` | `ge=0`. |
| `allow_new_agent` / `allow_new_sku` | bool | `False` | Auto-GO permissions for unseen seller/SKU. |
| `policy_version` | str | `""` | Informational tag; **not** enforced. |
| `require_governed_commercial_proof` | bool | `False` | Phase 8D: expressive **intent only** — generates a PolicySuggestion; enforcement stays with AcceptancePolicy after a seller adopts it. |

BuyerMandate is **not signed**. It is persisted as JSONL and emits
`MANDATE_CREATED` / `MANDATE_ACTIVATED` / `MANDATE_REVOKED` events (`source="buyer_mandate"`
is a label, not a platform attestation of authority).

## 2. ProgrammableMandate — field reference

Source: `protocol/programmable_mandate.py`.

| Field | Type | Default | Notes |
|---|---|---|---|
| `mandate_id` | str | generated `pmnd_<uuid12>` | Identifier. |
| `buyer_id` | str | — (required) | Buyer agent id. No org/tenant field. |
| `rules` | List[Dict] | `[]` | First-match rule list (see below). |
| `default_action` | str | `"reject"` | Action when no rule matches. Enum = `ALLOWED_ACTIONS`. |
| `max_amount_per_deal_usd` | float | `500.0` | Hard cap checked **before** rule evaluation (`gt=0`). |
| `max_amount_per_day_usd` | float | `0.0` | Not enforced in current code. |
| `status` | str | `ACTIVE` | `ACTIVE` \| `PAUSED` \| `REVOKED`. |
| `policy_hash` | str | computed SHA-256 | Identity of `rules + default_action`; **not** a signature. |
| `created_at` / `updated_at` | str | ISO-8601 now | Timestamps. |

**Rule shape** (each entry in `rules`): `{ "conditions": [ {field, op, value}, ... ], "action": <action> }`.
All conditions in a rule must match (AND).

- `field` ∈ `ALLOWED_RULE_FIELDS` = `seller_ocs`, `seller_tier`, `seller_dispute_rate`,
  `seller_total_settlements`, `amount_usd`, `vertical`, `proof_type`, `sku_id`,
  `verifier_confidence`, `risk_flag_count`, `seller_is_new`, `sku_is_new`,
  `previous_deals_with_seller`.
- `op` ∈ `ALLOWED_OPS` = `>=`, `<=`, `==`, `!=`, `>`, `<`, `in`, `not_in`.
- `action` ∈ `ALLOWED_ACTIONS` = `auto_approve`, `require_human`, `reject`, `require_staking`.

**Evaluation (`ProgrammableMandate.evaluate`)**: (1) if `amount_usd` exceeds
`max_amount_per_deal_usd` → `reject` (`rule_index = -1`); (2) rules are evaluated
in list order and the **first fully-matching rule wins**; (3) if no rule matches →
`default_action`. `validate_rules(rules)` returns a list of error strings (empty =
valid): a rule must have ≥1 condition, an allowed `action`, and each condition
must use an allowed `field`, an allowed `op`, and a non-null `value`.

## 3. Mandate Graph v1 — see the companion spec

The signed, delegatable authority artifact (fields `issuer`, `subject_agent`,
`parent_mandate_id`, `delegation_depth`, `expires_at`, `revoked_at`,
`allowed_actions`, `forbidden_actions`, `work_class`, `consequence_rights`,
`signature`, …) is defined and verified in
[`MANDATE_GRAPH_V1.md`](./MANDATE_GRAPH_V1.md). Unlike BuyerMandate /
ProgrammableMandate, it **is** signed (Ed25519 primary, HMAC-SHA256 fallback),
offline-verifiable, and embedded in a ProofPack under `proof.evidence.mandate`.
It is **not** used by the auto-GO or exact-consequence deal-flow paths — it is a
portable authority artifact, not a runtime control-flow authority.

---

## 4. Authority boundary (what a mandate does and does NOT prove)

These statements are source-backed for the deal-flow mechanisms (BuyerMandate /
ProgrammableMandate). The Mandate Graph adds cryptographic signing per its spec.

- **`mandate_id` is a caller-supplied / caller-attributed reference.** In the deal
  flow it is written into the event chain by the caller at auto-GO time
  (`AUTO_GO_APPROVED` / `AUTO_GO_DECIDED` payload) and later resolved from the local
  mandate store (`_resolve_mandate_for_deal` in `acceptance_gate.py`). It is **not**
  verified against an issuer, employer, or identity. A `mandate_id` alone does not
  prove legal authority or organizational delegation.
- **Acceptance is the decision authority.** Whether work may proceed to a
  consequence is decided by the Acceptance gate, not by a mandate reference. The
  mandate contributes an **amount / policy** authority only: at exact-consequence
  time, if the concrete gross exceeds `max_amount_per_deal_usd` the decision is
  `held` (recoverable), not `rejected`; an unresolved or non-`ACTIVE` mandate →
  `held`. (`authorize_exact_consequence` in `acceptance_gate.py`.)
- **Actor authentication is not tenancy.** Authenticating an actor (API key →
  agent record) establishes that actor's pseudonymous identity. It does **not**
  automatically establish an employer, principal, role, organization, or tenant.
  There is no organization/tenant field on BuyerMandate or ProgrammableMandate.
- **Exact authorization records a reference, not a proof of authority.** The
  `CONSEQUENCE_AUTHORIZED` event carries `mandate_ref` in its `refs` for the audit
  trail; the decision is made on the resolved mandate object, and `mandate_ref` is
  **not** part of the consequence-identity hash.
- **ProofPack / event trail.** In the deal flow, mandate information appears as a
  **referenced** `mandate_id` inside signed events (the event is signed; the
  `mandate_id` is payload data, not itself signed). Only the Mandate Graph artifact
  carries its own signature.
- **Absent by design (deal-flow mandates):** no organization/tenant identity, no
  delegation chain, no role/scope, no expiry, no revocation timestamp, and no
  signature **on** BuyerMandate / ProgrammableMandate. (Delegation, expiry,
  revocation, and signatures exist only on the Mandate Graph artifact — see its
  spec.) Do not represent a deal-flow mandate as a verified power of attorney,
  corporate authorization, employment relationship, or legal delegation.

## 5. Missing or malformed mandate input

- **No `mandate_id` on the deal** (no mandate-bearing event) → `_resolve_mandate_for_deal`
  returns no mandate; exact-consequence authorization is `held` (fail-closed), not
  auto-approved.
- **`mandate_id` present but unresolved** (not in the store) → treated as no mandate
  → `held`.
- **Mandate not `ACTIVE`** (`PAUSED` / `REVOKED`) → `held`.
- **Malformed ProgrammableMandate rules** → `validate_rules` returns error strings;
  a rule with no conditions, an unknown `action`, an unknown `field`/`op`, or a
  null `value` is rejected at validation.

---

## 6. Examples (current field names and accepted values)

### 6a. Consequence-neutral — ProgrammableMandate governing auto-approval

This governs whether **any** consequence is auto-approved vs escalated to a human,
based on proof confidence and risk — independent of payment. It uses only allowed
fields/ops/actions and passes `validate_rules`:

```json
{
  "mandate_id": "pmnd_example000",
  "buyer_id": "a2a_operator",
  "default_action": "require_human",
  "max_amount_per_deal_usd": 500.0,
  "rules": [
    {
      "conditions": [
        { "field": "verifier_confidence", "op": ">=", "value": 0.9 },
        { "field": "risk_flag_count", "op": "==", "value": 0 }
      ],
      "action": "auto_approve"
    },
    {
      "conditions": [
        { "field": "risk_flag_count", "op": ">=", "value": 1 }
      ],
      "action": "require_human"
    }
  ]
}
```

Meaning: high-confidence, zero-risk work is auto-approved; anything with a risk
flag requires a human; everything else falls to `default_action = require_human`.
The `max_amount_per_deal_usd` cap simply does not bind when the consequence carries
no monetary amount. For a genuinely non-payment consequence, remember that
**Acceptance** (not the mandate) is the decision authority, and the
performer-signed **Outcome Receipt** records that the consequence occurred.

### 6b. Signed, delegatable authority — Mandate Graph

For consequence-neutral authority that is itself signed and delegatable
(`allowed_actions`, `work_class`, `consequence_rights` such as `release`), use the
Mandate Graph artifact — see [`MANDATE_GRAPH_V1.md`](./MANDATE_GRAPH_V1.md).

### 6c. Payment (secondary reference) — BuyerMandate

Payment is one reference consequence, not the architecture. A BuyerMandate caps
buyer spend and constrains verticals:

```json
{
  "buyer_id": "a2a_buyer",
  "max_amount_per_deal_usd": 250.0,
  "allowed_verticals": ["saas", "marketing"],
  "confidence_threshold": 0.85,
  "allow_new_agent": false
}
```
