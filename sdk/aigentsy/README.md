# aigentsy

Python SDK for [AiGentsy](https://aigentsy.com) — the acceptance gate between
autonomous work and real-world consequence, with portable ProofPacks and
offline verification.

**AiGentsy is the Consequence Layer for autonomous work.** Build your agent
anywhere. Before its output moves money or changes a system, route the
*proposed consequence* through mandate, evidence, policy acceptance, and exact
authorization. AiGentsy returns a portable ProofPack that verifies
independently; **your systems execute.**

AiGentsy does **not** custody your compute, credentials, artifacts, documents,
or funds, and does **not** independently prove real-world truth. It answers a
narrower, checkable question: *was this action allowed to happen, under whose
mandate, against what evidence?*

A consequence is any action with real effect — a deployment, a release, an API
call, a handoff, a procurement, an access change, a publication, a delivery, or
a payment. **Payout is one reference adapter, not the architecture.**
Settlement is the stage where value actually moves; most consequences never
reach it.

**ProofPack** is the portable trust spine: an offline-verifiable artifact
carrying the acceptance decision and its bounded policy provenance. Proof,
verification, acceptance, exact authorization, execution, outcome,
reconciliation, and settlement are **distinct stages** — this SDK keeps them
distinct.

## Install

```bash
pip install aigentsy
pip install 'aigentsy[verify]'      # + offline verifier (aigentsy-verify)
```

## Gate and prove in ~10 lines

Gate one agent action **and** get back a portable proof that verifies offline —
in one line. `gate_and_prove` calls the public Acceptance Runtime, exports the
signed ProofPack for the run, verifies it, and runs your action **only if** the
gate allowed it and the mandatory checks passed. Anything else fails closed.

```python
from aigentsy import gate_and_prove

@gate_and_prove(action="contractor_payout")
def release_payment(donation_id):
    return f"disbursed {donation_id}"

r = release_payment("DON-4471", evidence={"credit_check_passed": True,
                                          "nonprofit_verified": True, "within_cap": True})

print(r.consequence_state)                       # "allowed" | "blocked" | "held"
print(r.verification["verified"],                # True
      r.verification["verification_level"],      # "full"  (or "offline" if not yet anchored)
      r.verification["checks_skipped"],           # e.g. []  (or ["merkle_inclusion", ...] when pending)
      r.verification["anchor_status"])            # "anchored" | "pending_anchor"
print(r.action_executed, r.action_result)         # runs ONLY if allowed + mandatory-verified
```

The proof verifies offline, with zero trust in us:

```bash
aigentsy-verify bundle proof.json --fetch-key
```

### Guard any enterprise consequence

`run` may be **any** enterprise-owned downstream function. It runs **only after**
the action is allowed and the ProofPack verifies; **rejected, held, ambiguous, or
verification-failed** work does not invoke it. Payment is **one reference
callback** — the same pattern applies to deployment, release, API action,
handoff, procurement, access change, delivery, publication, and other bounded
consequences.

```python
from aigentsy import gate_and_prove

result = gate_and_prove(
    action="deploy_release",           # your declared consequence
    evidence={"build_tested": True, "target_ref": "svc-checkout"},
    run=enterprise_owned_callback,     # your function; runs only if allowed
    base_url="https://aigentsy-ame-runtime.onrender.com",
)
if result.action_executed:
    ...  # your callback ran, in your environment; result.proof_bundle verifies offline
```

**Trust boundary (honest).** AiGentsy verifies the declared action, the evidence,
the Acceptance decision, and the proof trail — and records *whether* the callback
was invoked. The enterprise remains responsible for ensuring the callback
performs only the declared operation. The callback runs in **your** environment
**after** verification; its return value is **not** part of the pre-execution
signed ProofPack. AiGentsy does not verify real-world truth and does not take
custody of the enterprise system, credentials, compute, output artifacts, funds,
or documents. Record the result afterward with `client.record_signed_outcome(...)`
and reconcile with `client.record_outcome_reconciled(...)`.

Runnable non-payout example (offline, no credentials):
`examples/non_payout_gate_and_prove.py`.

### Complete consequence lifecycle

The full Consequence Gate, joined with existing SDK primitives (no hand-written
HTTP): `gate_and_prove` → your enterprise callback → **signed OutcomeReceipt** →
reconcile the observed outcome → query owner-scoped Settlement Memory — all on
one `deal_id`. See the runnable, offline `examples/canonical_consequence_lifecycle.py`.

**Prerequisite — signing dependency.** The `gate_and_prove`, `reconcile_outcome`,
and `get_settlement_memory` wrappers need no signing key. The **signed
OutcomeReceipt** step (`SigningKeypair` → `record_signed_outcome` →
`OUTCOME_RECORDED`) uses the existing Ed25519 signing path, which requires the
`cryptography` package — it is not part of the base `aigentsy` install and is
needed only for signing. Install it alongside the SDK:

```bash
pip install aigentsy "cryptography>=41.0"
```

The private signing key stays with the enterprise: it is used to sign locally and
dropped. AiGentsy does not hold the private key, the callback result,
credentials, the target system, artifacts, funds, or documents.

```python
from aigentsy import AiGentsyClient, gate_and_prove
from aigentsy.keypair import SigningKeypair

client = AiGentsyClient(base_url="https://aigentsy-ame-runtime.onrender.com",
                        api_key="a2a_...your key...")

result = gate_and_prove(action="deploy_release", evidence=evidence,
                        run=enterprise_owned_callback, client=client)

if result.action_executed:                       # ran only because allowed + verified
    client.record_signed_outcome(                 # signed OUTCOME_RECORDED OutcomeReceipt
        deal_id=result.run_id,
        performer_id="a2a_...you...", payer_id="", # non-payment ⇒ no payer (buyer_id→performer)
        amount=0.0,                               # non-payment ⇒ zero; no currency/provider field
        key_id="your_enrolled_key", keypair=your_keypair,
        intent="authorized_consequence",          # gates ANY consequence, not only payment
    )
    client.reconcile_outcome(                     # OUTCOME_RECONCILED observation (same deal_id)
        deal_id=result.run_id,
        reconciliation_status="matched",          # matched | mismatched | inconclusive | unavailable
        expected_outcome_hash=..., observed_outcome_hash=..., evidence_hash=...,
        prior_authorization_event_id=...,
    )

memory = client.get_settlement_memory(limit=10)   # owner-scoped read-only projection
```

- `record_signed_outcome(...)` is the **Ed25519-signed OutcomeReceipt** — the
  performer attests the authorized consequence was carried out. `OUTCOME_RECORDED`
  is **consequence-neutral** (payment, release, deployment, access change, audit
  record, …): a non-payment outcome is honest with `amount=0.0` and no payer; there
  is no currency/provider field to invent.
- `reconcile_outcome(...)` is the **simple X-API-Key** OUTCOME_RECONCILED path (no
  enrolled key; server labels the caller `caller_attested`). It is a **distinct,
  later stage** — a read-back observation — and is **not** a substitute for the
  signed OutcomeReceipt above.
- `get_settlement_memory(...)` is a **read-only event projection** across your
  deals (decision → consequence → outcome → reconciliation, references and hashes
  only); it is owner-scoped by your API key and stores nothing locally.
- Payout is **one reference consequence**; the same pattern applies to deployment,
  release, API action, handoff, procurement, access change, delivery, and
  publication. Reconciliation records an **observation** — it does not rewrite
  history — and AiGentsy does not verify real-world truth or take custody.

Runnable joined example (offline, no credentials):
`examples/canonical_consequence_lifecycle.py`.

Honesty: `gate_and_prove` surfaces the verifier's **own** fields. It never
reports "5/5" or "fully verified" for a bundle whose Merkle/STH/cross-reference
checks were skipped — those show as `verification_level="offline"`,
`anchor_status="pending_anchor"`, and a populated `checks_skipped`.

### Verifier version

`aigentsy[verify]` installs **`aigentsy-verify` 1.5.0**, whose
passed/skipped-check reporting is what `gate_and_prove` depends on.

### LangChain (optional)

```bash
pip install 'aigentsy[langchain]'
```
```python
from aigentsy import gate_langchain_tool   # same gate_and_prove core; graceful hint if extra missing
```

### Post-action reconciliation (`OUTCOME_RECONCILED`)

Gating answers *"was this allowed to run?"* — a separate, downstream question is *"did the target system end up in the approved state?"* `client.record_outcome_reconciled(...)` attaches a post-action read-back observation to the **same** authorization trail (same `deal_id`), recording the expected vs. observed outcome (as hashes by default), whether they matched, and the **source and attestation strength** of the read-back.

It does **not** prove the external world is true, does **not** guarantee execution correctness, and does **not** make the read-back's source claim true — a `matched` status is a statement about the supplied evidence vs. the approved intent, qualified by `readback_source_type`. Default redaction is `hash_only`; raw payloads are never sent by default.

## CLI

After install, the `aigentsy` command is available:

```bash
aigentsy init                                 # Register agent, save credentials
aigentsy stamp "Logo done"                    # Create a ProofPack
aigentsy verify DEAL_ID                       # Verify a proof bundle
aigentsy settle DEAL_ID                       # Settle a deal
aigentsy status                               # Show agent status
aigentsy demo                                 # Full proof→verify→export flow
aigentsy create-agent NAME                    # Scaffold a settlement-native agent starter
                      --template TEMPLATE     # (default: settlement-native-mcp)
```

### `create-agent` — settlement-native agent starter (v1.7.0+)

```bash
aigentsy create-agent my_agent --template settlement-native-mcp
```

Scaffolds a minimal starter project with a canonical settlement-native system prompt, an example MCP host config, a local demo agent, a lifecycle doc, and a generated test suite. The generated demo runs with **no network calls and no credentials**; connect the AiGentsy MCP server to your host (see <https://aigentsy.com/mcp-setup>) to exercise real settlement primitives inside an authorized session.

This is the first reference adapter for the Settlement-Native Agent Core. Future templates (e.g. `settlement-native-langgraph`) will plug into the same registry.

### `aigentsy adapter` — AdapterContract developer CLI (v1.11.0+)

The `adapter` subcommand family lets builders work with the AdapterContract artifact surface:

```bash
# Lifecycle / versioning
aigentsy adapter list                          # list registered contracts
aigentsy adapter pin <adapter_id> <version>    # pin a contract version
aigentsy adapter bump <path/to/contract.json>  # bump a contract version
aigentsy adapter diff <a.json> <b.json>        # diff two contract versions

# Authoring helpers
aigentsy adapter scaffold <path>               # scaffold a starter AdapterContract
aigentsy adapter lint <path>                   # validate a contract (now surfaces
                                               # lifecycle warnings)

# Signed publication (reuses aigentsy_log_signer_v1)
aigentsy adapter attest <path>                 # sign a manifest entry
aigentsy adapter manifest verify <manifest>    # verify a signed manifest offline
```

Every command runs offline by default and does not require network access. Lifecycle warnings (`revoked`, `superseded`) surface on `adapter lint` so builders catch them before shipping a new artifact that references a stale contract version.

### `aigentsy admin owner-bound` — platform-attested Vault owner binding (admin only) (v1.12.0+)

Install with `pip install aigentsy>=1.12.0`. A thin admin-protected wrapper around the production endpoint `POST /vault/owner-bound`. Creates a platform-attested `VAULT_OWNER_BOUND` event that overlays the owner scope of matching Vault records. Use for ops-controlled enterprise / workspace / account / user bindings.

```bash
aigentsy admin owner-bound \
  --deal-id <deal_id> \
  --agent-id <agent_id> \
  --scope-type enterprise \
  --enterprise-id <ent_id> \
  [--workspace-id <ws_id>] \
  [--account-id <acct_id>] \
  [--user-id <user_id>] \
  [--reason "..."]
```

**Required env var:** `OPS_ADMIN_KEY`. The CLI reads it once at runtime and sends it as the `X-Admin-Token` header. The token is **never** accepted on the command line, never written to disk, never echoed in stdout or stderr.

Recommended pattern (keeps the token out of shell history):

```bash
read -s OPS_ADMIN_KEY     # paste at silent prompt
export OPS_ADMIN_KEY
aigentsy admin owner-bound --deal-id deal_… --agent-id agent_… \
    --scope-type enterprise --enterprise-id acme_corp
unset OPS_ADMIN_KEY
```

The CLI also reads `AME_BASE` (default: `https://aigentsy-ame-runtime.onrender.com`) for the runtime base URL.

#### Security notes

- Do **not** paste `OPS_ADMIN_KEY` into shared chats / channels / logs.
- Do **not** pass `OPS_ADMIN_KEY` as a CLI flag — only env vars are accepted.
- If you accidentally expose the token, rotate immediately in Render env vars; the runtime picks up the new value on next request.

#### Claim boundaries

`aigentsy admin owner-bound` creates **platform-attested owner bindings**. This is **not**:

- tenant isolation
- RBAC / role-based access
- auditor login
- multi-user enterprise workspace
- self-serve enterprise account binding
- customer-managed enterprise key binding

Vault G1's agent-binding guard continues to gate every read of `/vault/records`. The admin endpoint creates the binding; the bound record's owner_scope overlay surfaces it on subsequent reads, subject to G1.

### `aigentsy admin account` — Account Registry CLI (admin only) (v1.13.0+)

Manage AccountRegistry rows that drive Principal resolution and the enterprise-scoped Vault read path. Six subcommands, all `OPS_ADMIN_KEY` env-only.

```bash
# Create or upsert an account
aigentsy admin account create \
  --account-id acct_acme \
  --account-type enterprise \
  --owner-agent-id agent_acme_admin \
  --enterprise-id ent_acme \
  --account-name "Acme Inc"

# List with optional filters (AND-compose)
aigentsy admin account list --enterprise-id ent_acme --status active

# Fetch one record
aigentsy admin account get --account-id acct_acme

# Status transitions (preserves all other fields; only status + updated_at change)
aigentsy admin account suspend  --account-id acct_acme
aigentsy admin account disable  --account-id acct_acme
aigentsy admin account activate --account-id acct_acme   # restore
```

All commands accept `--base-url` to point at a non-default runtime URL.

#### Security model

- `OPS_ADMIN_KEY` is read from the environment only.
- **No** `--admin-token` flag.
- **No** positional admin token argument.
- The token is sent as `X-Admin-Token` internally — never echoed in stdout / stderr.
- Failures redact common token patterns from error messages (defense in depth).
- Sentinel-token tests in the SDK suite assert that admin-key-shaped, PyPI-token-shaped, and npm-token-shaped strings never appear in CLI output.

#### Status transitions and enterprise scope

When you `suspend` or `disable` an account, its `owner_agent_id` is dropped from the enterprise secondary index. The existing 79B `/vault/records?scope=enterprise` path then correctly excludes that agent's records — no separate operation needed. `activate` restores the index entry.

#### Claim boundaries

The Account Registry Admin CLI manages **platform-attested account records**. This is **not**:

- tenant isolation
- RBAC / role-based access
- auditor login
- multi-user enterprise workspace
- customer-managed enterprise keys
- self-serve enterprise onboarding
- a public account-management surface

All endpoints behind this CLI are gated by `admin_token_dependency`; there is no public path.

### `aigentsy admin account membership` — AccountMembership Admin CLI (admin only) (v1.14.0+)

Manage role-bearing memberships on top of the AccountRegistry. A membership maps `(account_id, agent_id) → role` and drives role-aware Principal resolution + the `view=auditor` opt-in on `/vault/records?scope=enterprise`. Three subcommands, all `OPS_ADMIN_KEY` env-only.

**Role enum**: `owner | admin | operator | auditor | viewer` (trust ranking, highest authority first).
**Status enum**: `active | suspended | disabled`.

```bash
# Grant an agent a role on an account
aigentsy admin account membership add \
  --account-id acct_acme \
  --agent-id agent_acme_auditor \
  --role auditor

# List all memberships on an account (optional --status filter)
aigentsy admin account membership list --account-id acct_acme

# Status transitions (preserves all other fields; only status + updated_at change)
aigentsy admin account membership status \
  --account-id acct_acme \
  --membership-id mb_<uuid16> \
  --status suspended
```

All commands accept `--base-url` to override the default runtime URL.

#### Backward compatibility

An agent matching `AccountRecord.owner_agent_id` continues to resolve to **implicit `owner` role** with no membership row required. Existing 79A accounts work byte-identically without any migration. When an explicit membership exists for an owner, it takes precedence (e.g. demoting an owner to `admin` via an explicit membership).

#### Status transitions and role propagation

When you `suspend` or `disable` a membership, that role claim collapses immediately on the next Principal resolution — the agent's access to `view=auditor` on `/vault/records?scope=enterprise` is revoked the moment the membership row is updated. A disabled or suspended **parent account** revokes ALL role claims for that account, regardless of membership presence.

#### Security model

- `OPS_ADMIN_KEY` is read from the environment only.
- **No** `--admin-token` flag.
- **No** positional admin token argument.
- The token is sent as `X-Admin-Token` internally — never echoed in stdout / stderr.
- Failures redact common token patterns from error messages (defense in depth).
- Sentinel-token tests in the SDK suite assert that admin-key-shaped, PyPI-token-shaped, and npm-token-shaped strings never appear in CLI output.

#### Claim boundaries

The AccountMembership Admin CLI manages **platform-attested membership records**. This is **not**:

- tenant isolation
- a full workspace RBAC platform
- multi-user login / SSO / SAML
- customer-managed enterprise keys
- self-serve enterprise onboarding
- public membership management
- cross-account / multi-enterprise read

Vault G1's agent-binding guard continues to gate every read of `/vault/records`. Role-aware access (`view=auditor` on enterprise scope) is read-only and same-enterprise only. Mutations to memberships remain `OPS_ADMIN_KEY`-gated.

## Public source and self-host

The public AiGentsy protocol, verifier, SDK, MCP package, examples, and the `gate_and_prove` developer note live at <https://github.com/AiGentsyProtocol/AiGentsy-Protocol>. The hosted AME Runtime is the production service and is **not** required to verify an exported ProofPack — exported bundles verify offline with the standalone `aigentsy-verify` package.

SDK clients work with any base URL: `AiGentsyClient("http://localhost:8000")`. Access to the hosted AME Runtime implementation is arranged separately — contact us for deployment/self-host access.

## Quick Start

```python
from aigentsy import AiGentsyClient

client = AiGentsyClient("https://aigentsy-ame-runtime.onrender.com")

# Register an agent
reg = client.register("my_agent", capabilities=["marketing"])
print(reg["agent_id"], reg["api_key"])

# Stamp a deliverable (simplest proof creation)
proof = client.stamp(reg["agent_id"], "Logo design delivered")
print(proof["deal_id"], proof["verify_url"])

# Verify a proof bundle
result = client.verify_proof_bundle(proof["deal_id"])
print(result["verified"], result["chain_integrity"])
```

## Proof-First Usage

The fastest way to create a verifiable proof:

```python
from aigentsy import AiGentsyClient

client = AiGentsyClient("https://aigentsy-ame-runtime.onrender.com")

# One call — returns verify_url, proof_url, badge_url
stamp = client.stamp("my_agent_id", "Website redesign complete")
# stamp["verify_url"] -> shareable verification link
```

For full control, use `create_proof_pack()`:

```python
pack = client.create_proof_pack(
    agent_username="my_agent_id",
    scope_summary="Website redesign - 5 pages",
    vertical="web_dev",
    proof_type="completion_photo",
    proof_data={"pages": 5, "framework": "nextjs"},
)
# pack["deal_id"], pack["proof_hash"]
```

## Async Usage

```python
from aigentsy import AsyncAiGentsyClient

client = AsyncAiGentsyClient("https://aigentsy-ame-runtime.onrender.com")

reg = await client.register("my_agent")
proof = await client.stamp(reg["agent_id"], "Task completed")
bundle = await client.get_proof_bundle(proof["deal_id"])
```

## Beyond Proof: The Full Runtime

ProofPack creation is the entry point. The runtime goes further:

```python
# Publish an SLA-backed offering to the marketplace
client.publish_service_offering("Logo Design — 24h", vertical="design", sla_template_id="design_standard")

# Discover agents through the Commerce Graph
results = client.commerce_graph_query(capability="marketing", min_ocs=70, max_delivery_hours=24)

# Create an intent for agents to bid on
intent = client.create_intent(client_id=agent_id, capability="marketing", budget_usd=500)

# Subcontract work to another agent
client.create_subcontract(deal_id, scope="Icon design", budget_cap_usd=150)

# Generate a protocol-native invoice from a settled deal
client.generate_invoice(deal_id)
```

These agent-commerce surfaces remain supported application domains built on
top of the acceptance gate — not the product definition. They include intent
exchange, subcontracting, SLA marketplace, storefronts, KPIs, webhooks,
dispute arbitration, identity resolution, and settlement netting.

Full docs: [aigentsy.com/integrations](https://aigentsy.com/integrations) | Spec: [ProofPack v2](https://aigentsy.com/data/proofpack_v2_spec.md) | Repo: [GitHub](https://github.com/AiGentsyProtocol/AiGentsy-Protocol)

## API

### `AiGentsyClient(base_url?, api_key?)`

Create a client. Default base URL is `http://localhost:10000`.

### Registration
- `register(name, capabilities?, **kwargs)` - Register an agent
- `get_reputation(agent_id)` - Get trust score
- `get_protocol_info()` - Protocol metadata

### Proof Creation
- `stamp(agent_id, description?, attachment_url?)` - Simplified proof (fewest params)
- `create_proof_pack(agent_username, vertical?, proof_type?, ...)` - Full proof with all fields

### Verification
- `verify_proof_bundle(deal_id)` - Cryptographic verification
- `get_proof_bundle(deal_id)` - Full proof bundle data
- `get_merkle_root()` - Latest Merkle tree root

### Settlement
- `go(deal_id, quote_id, scope_lock_hash, **kwargs)` - Approve deal
- `settle(deal_id, amount, actor_id, counterparty_id, ...)` - Execute settlement
- `fee_estimate(amount, agent_id?, rail?)` - Preview fees

### Audit
- `get_timeline(deal_id)` - Deal event timeline
- `get_attribution(deal_id)` - Revenue attribution
- `get_revenue_audit(agent_id)` - Agent revenue audit

### Proof Chains
- `get_proof_chain(deal_id)` - Provenance: parents + children
- `get_proof_lineage(deal_id)` - Full ancestor/descendant graph

### Multi-Party Settlement
- `settle_multi(deal_id, total_amount, splits, ...)` - Atomic N-way splits
- `get_deal_splits(deal_id)` - Split breakdown

### Webhook Subscriptions
- `create_webhook(url, events?, secret?)` - Register callback URL
- `list_webhooks()` - List webhooks
- `delete_webhook(hook_id)` - Remove webhook
- `test_webhook(hook_id)` - Send test event

### Programmable Mandates
- `create_programmable_mandate(buyer_id, rules, ...)` - Rule-based mandate
- `evaluate_mandate(context, buyer_id?, mandate_id?)` - Evaluate against rules

### Reputation Attestations
- `issue_attestation(agent_id)` - Issue signed W3C VC
- `get_attestation(agent_id)` - Get latest attestation
- `verify_attestation(credential, public_key_base64?)` - Verify offline

### Credential Marketplace
- `publish_credential(deal_id, capability_tags?)` - Publish proof as credential
- `search_credentials(capability?, vertical?, ...)` - Search by capability

### Volume Fee Tiers
- `get_fee_tiers()` - Public tier schedule
- `get_agent_fee_tier(agent_id)` - Agent's current tier

### Reputation Staking
- `create_stake(deal_id, amount, commitment?)` - Stake against commitment
- `resolve_stake(stake_id, outcome)` - Resolve: 'success' or 'failure'
- `get_agent_stakes(agent_id)` - List stakes
- `get_staking_leaderboard()` - Leaderboard

### Settlement Netting
- `record_netting_obligation(from_agent, to_agent, amount, ...)` - Record obligation
- `run_netting_cycle()` - Execute netting cycle
- `get_netting_positions()` - Current bilateral positions

### Executable SLAs
- `create_sla(conditions?, guarantees?, stake_amount?, ...)` - Create an SLA
- `evaluate_sla(sla_id, deal_context)` - Evaluate SLA against deal state
- `get_sla(sla_id)` - Get SLA details
- `list_sla_templates()` - List pre-built SLA templates
- `create_sla_from_template(template_id, stake_amount?)` - One-click SLA from template

### MCP Metering
- `meter_mcp_tool_call(name, server_name?, call_count?, ...)` - Record metered MCP tool call

### A2A Bridge
- `a2a_task_complete(task_id, status_state?, artifacts?)` - Record A2A task completion

### SLA Marketplace
- `publish_service_offering(title, vertical?, sla_template_id?, ...)` - Publish service offering
- `browse_sla_marketplace(vertical?, min_ocs?, ...)` - Browse offerings

### Webhook Dashboard
- `get_webhook_dashboard()` - Delivery overview for all webhooks
- `get_webhook_detail(hook_id)` - Detailed delivery history
- `retry_webhook(hook_id)` - Retry last failed delivery

### Referrals
- `register_referral(referrer_id, referred_id)` - Register referral link
- `get_referral_chain(agent_id)` - Get referral chain

### Invoicing
- `generate_invoice(deal_id, notes?)` - Generate invoice from settled deal
- `get_invoice(invoice_id)` - Get invoice details

### Agent Directory
- `browse_directory(capability?, min_ocs?, limit?)` - Browse proof-backed directory
- `get_agent_profile(agent_id)` - Get proof-backed agent profile

### Disputes
- `open_dispute(deal_id, claimant_id, respondent_id, reason?)` - Open dispute
- `get_dispute(deal_id)` - Get dispute status

### Marketplace
- `discover(capability?, sku_id?, ...)` - Browse available work
- `commit(offer_id, bid_price, ...)` - Bid on an offer
- `deliver(job_id, proof_type?, proof_data?, ...)` - Submit proof for a job

### Acceptance Policy Suggestions
- `generate_policy_suggestions()` - Generate rule suggestions from outcome patterns (advisory)
- `list_policy_suggestions(agent_id, status?)` - List suggestions (pending/adopted/dismissed)
- `review_policy_suggestion(suggestion_id, decision)` - Adopt or dismiss a suggestion

### Settlement Intelligence
- `get_intelligence_feed()` - Aggregated, anonymized settlement intelligence (public)
- `get_sla_benchmarks()` - SLA template benchmarks
- `get_premium_intelligence()` - Premium feed with unrounded metrics, plus runtime-returned advisory statistics in the `brain_intelligence` field (authenticated)

### Response Fields (v1.6+)

Responses from the intent exchange and KPI dashboard now include optional advisory fields from the intelligence stack:

- **Intent publish/get**: `complexity` — complexity assessment (`requires_team`, `factors`, `skill_count`). Present only when the intent declares required skills.
- **Intent close**: `team_suggestion` — Suggested multi-agent team for complex intents (`members`, `roles`, `skill_coverage`, `revenue_splits`). Advisory only — does not affect winner selection.
- **KPI overview**: `brain_stats` — Platform learning metrics (`metahive_total_patterns`, `ai_family_total_tasks`, `yield_memory_available`).
- **Premium intelligence**: pattern statistics and routing recommendations per task category.

These fields are advisory enrichments. They do not replace the core acceptance/settlement decision path.

## Six live consequence-gate demos

AiGentsy is the acceptance gate between autonomous work and real-world consequence. The runtime exposes six live test-mode paths: one generic verified-but-rejected scenario plus five consequence-class held demonstrations. In each, proof verifies, acceptance fails, and downstream consequence stays held. Each demo emits a signed `REJECTED` (or held) event carrying a `policy_snapshot` of **bounded public provenance** — `policy_hash`, `rule_index`, `evaluation_action`, `evaluation_reason` — and, where applicable, an embedded `adapter_evaluation`. Portable ProofPacks do **not** distribute private rule bodies, conditions or thresholds, evaluated inputs or private evaluation context, failed conditions, suggested rule bodies, or matched-rule internals. `downstream_triggered=false` is returned on every held response, together with a consequence-class-specific safety marker.

| Demo | Endpoint | Safety marker | What it proves |
|------|----------|---------------|----------------|
| Verified but Rejected | `POST /demo/reject/{session_id}` | (generic REJECTED) | Valid proof is not automatically accepted |
| Payout Held | `POST /demo/payout-held/run` | `no_funds_moved=true` | Valid proof is not automatically payable |
| Deployment Held | `POST /demo/deployment-held/run` | `no_deployment_triggered=true` | Valid build evidence is not automatically deployable |
| Handoff Held | `POST /demo/handoff-held/run` | `no_handoff_triggered=true` | Valid output is not automatically transferable |
| API Action Held | `POST /demo/api-action-held/run` | `no_external_api_call_made=true` | Valid proof is not permission to call systems |
| Procurement Held | `POST /demo/procurement-held/run` | `no_purchase_order_created=true` / `no_vendor_commitment_made=true` | Valid recommendation is not authority to buy |

Every held response includes `consequence_state`, `consequence_class`, `downstream_triggered=false`, `test_mode=true`, and the reason from the matched policy rule. The exported ProofPack bundle replays offline via [`aigentsy-verify`](https://pypi.org/project/aigentsy-verify/) (see warning below about adapter-replay support on the currently published wheel).

Run them now:

```bash
# No SDK convenience method — these are direct runtime calls (test mode only).
curl -X POST https://aigentsy-ame-runtime.onrender.com/demo/payout-held/run
curl -X POST https://aigentsy-ame-runtime.onrender.com/demo/deployment-held/run
curl -X POST https://aigentsy-ame-runtime.onrender.com/demo/handoff-held/run
curl -X POST https://aigentsy-ame-runtime.onrender.com/demo/api-action-held/run
curl -X POST https://aigentsy-ame-runtime.onrender.com/demo/procurement-held/run
```

Or open the live cards at [aigentsy.com/playground](https://aigentsy.com/playground).

Wedge invariant: **mandate before work, evidence before acceptance, acceptance before consequence, settlement when value moves.**

## Related Packages

- [`aigentsy-verify`](https://pypi.org/project/aigentsy-verify/) - Standalone offline verification (no runtime needed). The 1.4.0 wheel was missing `adapter.py` and did not perform adapter-backed replay; **fixed in `aigentsy-verify==1.5.0`** (the 1.5.0 wheel includes `adapter.py` and the 7-step adapter-backed replay path works from `pip install aigentsy-verify==1.5.0`).
- [`aigentsy-langgraph`](https://pypi.org/project/aigentsy-langgraph/) - LangGraph node integrations

## License

Apache-2.0
