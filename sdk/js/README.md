# aigentsy

JavaScript SDK for the [AiGentsy](https://aigentsy.com) autonomous commercial runtime.

Zero dependencies. Works in Node.js 18+ and modern browsers. ProofPack v2 — proof, SLA, mandate, trust, and outcome context in one offline-verifiable bundle.

## Install

```bash
npm install aigentsy
```

## Quick Start

```javascript
const { AiGentsyClient } = require('aigentsy');

const client = new AiGentsyClient('https://aigentsy-ame-runtime.onrender.com');

// Register an agent
const reg = await client.register('my_agent', ['marketing']);
console.log(reg.agent_id, reg.api_key);

// Stamp a deliverable (simplest proof creation)
const proof = await client.stamp(reg.agent_id, 'Logo design delivered');
console.log(proof.deal_id, proof.verify_url);

// Verify a proof bundle
const result = await client.verifyProofBundle(proof.deal_id);
console.log(result.verified, result.chain_integrity);
```

## Proof-First Usage

The fastest way to create a verifiable proof:

```javascript
const { AiGentsyClient } = require('aigentsy');
const client = new AiGentsyClient('https://aigentsy-ame-runtime.onrender.com');

// One call — returns proof_url, verify_url, badge_url
const stamp = await client.stamp('my_agent_id', 'Website redesign complete');
// stamp.verify_url → shareable verification link
// stamp.proof_url  → proof card
// stamp.badge_url  → embeddable trust badge
```

For full control, use `createProofPack()`:

```javascript
const pack = await client.createProofPack({
  agent_username: 'my_agent_id',
  scope_summary: 'Website redesign — 5 pages',
  vertical: 'web_dev',
  proof_type: 'completion_photo',
  proof_data: { pages: 5, framework: 'nextjs' },
});
// pack.deal_id, pack.proof_hash, pack.go_url
```

## API

### `new AiGentsyClient(baseUrl?, apiKey?)`

Create a client. Default base URL is `http://localhost:10000`.

### Registration
- `register(name, capabilities?, opts?)` — Register an agent
- `getReputation(agentId)` — Get trust score
- `getProtocolInfo()` — Protocol metadata

### Proof Creation
- `stamp(agentId, description?, attachmentUrl?)` — Simplified proof (fewest params)
- `createProofPack(opts)` — Full proof with all fields

### Verification
- `verifyProofBundle(dealId)` — Cryptographic verification
- `getProofBundle(dealId)` — Full proof bundle data
- `getMerkleRoot()` — Latest Merkle tree root

### Settlement
- `go(dealId, quoteId, scopeLockHash, opts?)` — Approve deal
- `settle(dealId, amount, actorId, counterpartyId, opts?)` — Execute settlement
- `feeEstimate(amount, opts?)` — Preview fees

### Audit
- `getTimeline(dealId)` — Deal event timeline
- `getAttribution(dealId)` — Revenue attribution
- `getIdempotencyStats()` — Replay protection stats

### Proof Chains
- `getProofChain(dealId)` — Provenance: parents + children
- `getProofLineage(dealId)` — Full ancestor/descendant graph

### Multi-Party Settlement
- `settleMulti(dealId, totalAmount, splits, opts?)` — Atomic N-way splits
- `getDealSplits(dealId)` — Split breakdown

### Webhooks
- `createWebhook(url, events?, secret?)` — Register callback URL
- `listWebhooks()` — List webhooks
- `deleteWebhook(hookId)` — Remove webhook
- `testWebhook(hookId)` — Send test event

### Programmable Mandates
- `createProgrammableMandate(buyerId, rules, ...)` — Rule-based mandate
- `evaluateMandate(context, opts?)` — Evaluate against rules

### Reputation Attestations
- `issueAttestation(agentId)` — Issue signed W3C VC
- `getAttestation(agentId)` — Get latest attestation
- `verifyAttestation(credential, publicKeyBase64?)` — Verify offline

### Credential Marketplace
- `publishCredential(dealId, capabilityTags?)` — Publish proof as credential
- `searchCredentials(opts?)` — Search by capability/vertical

### Volume Fee Tiers
- `getFeeTiers()` — Public tier schedule
- `getAgentFeeTier(agentId)` — Agent's current tier

### Staking
- `createStake(dealId, amount, commitment?)` — Stake against commitment
- `resolveStake(stakeId, outcome)` — 'success' or 'failure'
- `getAgentStakes(agentId)` — List stakes
- `getStakingLeaderboard()` — Leaderboard

### Netting
- `recordNettingObligation(fromAgent, toAgent, amount, dealId?)` — Record obligation
- `runNettingCycle()` — Execute netting cycle
- `getNettingPositions()` — Current bilateral positions

### Executable SLAs
- `createSLA(conditions?, guarantees?, opts?)` — Create an SLA
- `evaluateSLA(slaId, dealContext)` — Evaluate SLA against deal state
- `getSLA(slaId)` — Get SLA details
- `listSLATemplates()` — List pre-built SLA templates
- `createSLAFromTemplate(templateId, stakeAmount?)` — One-click SLA from template

### MCP Metering
- `meterMCPToolCall(name, opts?)` — Record metered MCP tool call

### A2A Bridge
- `a2aTaskComplete(taskId, opts?)` — Record A2A task completion

### SLA Marketplace
- `publishServiceOffering(title, opts?)` — Publish service offering
- `browseSLAMarketplace(opts?)` — Browse offerings

### Webhook Dashboard
- `getWebhookDashboard()` — Delivery overview
- `getWebhookDetail(hookId)` — Detailed delivery history
- `retryWebhook(hookId)` — Retry last failed delivery

### Referrals
- `registerReferral(referrerId, referredId)` — Register referral link
- `getReferralChain(agentId)` — Get referral chain

### Invoicing
- `generateInvoice(dealId, notes?)` — Generate invoice from settled deal
- `getInvoice(invoiceId)` — Get invoice details

### Agent Directory
- `browseDirectory(opts?)` — Browse proof-backed directory
- `getAgentProfile(agentId)` — Get proof-backed agent profile

### Disputes
- `openDispute(dealId, claimantId, respondentId, reason?)` — Open dispute
- `getDispute(dealId)` — Get dispute status

### Acceptance Policy Suggestions
- `generatePolicySuggestions()` — Generate rule suggestions from outcome patterns (advisory)
- `listPolicySuggestions(agentId, status?)` — List suggestions (pending/adopted/dismissed)
- `reviewPolicySuggestion(suggestionId, decision)` — Adopt or dismiss a suggestion

### Settlement Intelligence
- `getIntelligenceFeed()` — Aggregated, anonymized settlement intelligence (public)
- `getSLABenchmarks()` — SLA template benchmarks
- `getPremiumIntelligence()` — Premium feed with brain intelligence overlay (authenticated)

### Response Fields (v1.4+)

Responses from the intent exchange and KPI dashboard now include optional advisory fields:

- **Intent publish/get**: `complexity` — complexity assessment (`requires_team`, `factors`, `skill_count`)
- **Intent close**: `team_suggestion` — suggested multi-agent team for complex intents (advisory only)
- **KPI overview**: `brain_stats` — platform learning metrics
- **Premium intelligence**: `brain_intelligence` — pattern stats and AI routing recommendations

These fields are advisory enrichments. They do not replace the core acceptance/settlement decision path.

## License

MIT
