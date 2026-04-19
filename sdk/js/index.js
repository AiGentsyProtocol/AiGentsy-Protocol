/**
 * AiGentsy Protocol JavaScript SDK
 * ==================================
 *
 * Full-loop client for the A2A Settlement Protocol.
 * Uses native fetch (zero dependencies).
 *
 * Usage:
 *   const { AiGentsyClient } = require('./sdk/js');
 *   const client = new AiGentsyClient('http://localhost:10000');
 *   const result = await client.register('my_agent', ['marketing']);
 *   console.log(result.agent_id, result.api_key);
 */

class AiGentsyClient {
  constructor(baseUrl = 'http://localhost:10000', apiKey = null) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.apiKey = apiKey;
  }

  async _fetch(method, path, body = null, auth = false) {
    const headers = { 'Content-Type': 'application/json' };
    if (auth && this.apiKey) headers['X-API-Key'] = this.apiKey;
    const opts = { method, headers };
    if (body) opts.body = JSON.stringify(body);
    const resp = await fetch(`${this.baseUrl}${path}`, opts);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);
    return resp.json();
  }

  // ── Registration & Identity ──

  async register(name, capabilities = [], opts = {}) {
    const data = await this._fetch('POST', '/protocol/register', {
      name, capabilities, ...opts,
    });
    if (data.api_key) this.apiKey = data.api_key;
    return data;
  }

  async getReputation(agentId) {
    return this._fetch('GET', `/protocol/reputation/${agentId}`);
  }

  async getProtocolInfo() {
    return this._fetch('GET', '/protocol/info');
  }

  // ── Buyer Mandates ──

  async createMandate(buyerId, maxAmount, verticals = ['marketing'], confidence = 0.8) {
    return this._fetch('POST', '/protocol/mandates', {
      buyer_id: buyerId,
      max_amount_per_deal_usd: maxAmount,
      allowed_verticals: verticals,
      confidence_threshold: confidence,
    }, true);
  }

  // ── Proof → Go → Pay Loop ──

  async createProofPack(opts) {
    return this._fetch('POST', '/protocol/proof-pack', opts);
  }

  async stamp(agentId, description = '', attachmentUrl = null) {
    const body = { agent_id: agentId, description };
    if (attachmentUrl) body.attachment_url = attachmentUrl;
    return this._fetch('POST', '/protocol/stamp', body);
  }

  async autoGo(dealId, quoteId, buyerId, opts = {}) {
    return this._fetch('POST', '/protocol/auto-go', {
      deal_id: dealId, quote_id: quoteId, buyer_id: buyerId, ...opts,
    });
  }

  async go(dealId, quoteId, scopeLockHash, opts = {}) {
    return this._fetch('POST', '/protocol/go', {
      deal_id: dealId, quote_id: quoteId, scope_lock_hash: scopeLockHash, ...opts,
    });
  }

  // ── Settlement ──

  async settle(dealId, amount, actorId, counterpartyId, opts = {}) {
    return this._fetch('POST', '/protocol/settle', {
      deal_id: dealId, amount, actor_id: actorId,
      counterparty_id: counterpartyId, ...opts,
    }, true);
  }

  async feeEstimate(amount, opts = {}) {
    const params = new URLSearchParams({ amount, ...opts });
    return this._fetch('GET', `/protocol/fee-estimate?${params}`);
  }

  // ── Verification ──

  async verifyProof(dealId, proofHash, proofType, opts = {}) {
    return this._fetch('POST', '/protocol/verify/provider', {
      deal_id: dealId, proof_hash: proofHash, proof_type: proofType, ...opts,
    });
  }

  async listVerificationProviders() {
    return this._fetch('GET', '/protocol/verify/providers');
  }

  // ── Audit & Timeline ──

  async getProofBundle(dealId) { return this._fetch('GET', `/proof/${dealId}`); }
  async verifyProofBundle(dealId) { return this._fetch('GET', `/proof/${dealId}/verify`); }
  async getTimeline(dealId) { return this._fetch('GET', `/protocol/deals/${dealId}/timeline`); }
  async getAttribution(dealId) { return this._fetch('GET', `/protocol/deals/${dealId}/attribution`, null, true); }
  async getMerkleRoot() { return this._fetch('GET', '/protocol/merkle/latest'); }
  async getIdempotencyStats() { return this._fetch('GET', '/protocol/idempotency/stats'); }

  // ── Payout Destinations ──

  async createPayoutDestination(ownerId, rail, address, metadata = {}) {
    return this._fetch('POST', '/protocol/payout-destinations', {
      owner_id: ownerId, rail, address, metadata,
    }, true);
  }

  // ── Executable SLAs ──

  async createSLA(conditions = [], guarantees = {}, opts = {}) {
    return this._fetch('POST', '/protocol/slas', { conditions, guarantees, ...opts }, true);
  }
  async evaluateSLA(slaId, dealContext) {
    return this._fetch('POST', `/protocol/slas/${slaId}/evaluate`, { deal_context: dealContext });
  }
  async getSLA(slaId) { return this._fetch('GET', `/protocol/slas/${slaId}`); }
  async listSLATemplates() { return this._fetch('GET', '/protocol/slas/templates'); }
  async createSLAFromTemplate(templateId, stakeAmount = 0) {
    return this._fetch('POST', '/protocol/slas/from-template', {
      template_id: templateId, stake_amount_usd: stakeAmount,
    }, true);
  }
  async meterMCPToolCall(name, opts = {}) {
    return this._fetch('POST', '/protocol/bridges/mcp/meter', { name, ...opts });
  }
  async a2aTaskComplete(taskId, opts = {}) {
    return this._fetch('POST', '/protocol/bridges/a2a/task-complete', {
      id: taskId, status: { state: 'completed' }, ...opts,
    });
  }

  // ── Acceptance Gate ──

  async submitForAcceptance(dealId, downstreamAction = 'settle') {
    return this._fetch('POST', '/protocol/acceptance/submit', { deal_id: dealId, downstream_action: downstreamAction }, true);
  }
  async acceptOutput(acceptanceId, reason = '', checksPassed = []) {
    return this._fetch('POST', `/protocol/acceptance/${acceptanceId}/accept`, { decision: 'accept', reason, checks_passed: checksPassed }, true);
  }
  async rejectOutput(acceptanceId, reason = '', checksFailed = []) {
    return this._fetch('POST', `/protocol/acceptance/${acceptanceId}/reject`, { decision: 'reject', reason, checks_failed: checksFailed }, true);
  }
  async getAcceptance(dealId) { return this._fetch('GET', `/protocol/acceptance/deal/${dealId}`); }

  // ── Acceptance Policies ──

  async createAcceptancePolicy(rules, defaultAction = 'require_review') {
    return this._fetch('POST', '/protocol/acceptance-policies', { rules, default_action: defaultAction }, true);
  }
  async getAcceptancePolicy(agentId) { return this._fetch('GET', `/protocol/acceptance-policies/${agentId}`); }
  async evaluateAcceptancePolicy(dealId, agentId) {
    return this._fetch('POST', '/protocol/acceptance-policies/evaluate', { deal_id: dealId, agent_id: agentId }, true);
  }

  // ── Acceptance Policy Suggestions ──

  /** Generate policy suggestions from outcome patterns. Advisory — must be adopted to take effect. */
  async generatePolicySuggestions() {
    return this._fetch('POST', '/protocol/acceptance-policies/suggestions/generate', {}, true);
  }
  /** List policy suggestions for an agent. Optional status filter: 'pending', 'adopted', 'dismissed'. */
  async listPolicySuggestions(agentId, status = '') {
    const url = status
      ? `/protocol/acceptance-policies/suggestions/${agentId}?status=${status}`
      : `/protocol/acceptance-policies/suggestions/${agentId}`;
    return this._fetch('GET', url);
  }
  /** Adopt or dismiss a policy suggestion. decision: 'adopted' or 'dismissed'. */
  async reviewPolicySuggestion(suggestionId, decision) {
    return this._fetch('POST', `/protocol/acceptance-policies/suggestions/${suggestionId}/review`, { decision }, true);
  }

  // ── Commerce Graph ──

  async commerceGraphQuery(opts = {}) { return this._fetch('POST', '/protocol/commerce-graph/query', opts); }
  async commerceGraphProfile(agentId) { return this._fetch('GET', `/protocol/commerce-graph/agent/${agentId}`); }

  // ── Intent Exchange ──

  async createIntent(clientId, capability, budgetUsd, opts = {}) {
    return this._fetch('POST', '/protocol/intents', {
      client_id: clientId, capability, budget_usd: budgetUsd, ...opts,
    });
  }
  async submitBid(intentId, agentId, priceUsd, deliveryHours, message = '') {
    return this._fetch('POST', `/protocol/intents/${intentId}/bids`, {
      agent_id: agentId, price_usd: priceUsd, delivery_hours: deliveryHours, message,
    });
  }
  async closeIntent(intentId) { return this._fetch('POST', `/protocol/intents/${intentId}/close`, {}); }
  async getIntent(intentId) { return this._fetch('GET', `/protocol/intents/${intentId}`); }

  // ── Subcontracting ──

  async createSubcontract(dealId, scope, budgetCapUsd, opts = {}) {
    return this._fetch('POST', `/protocol/deals/${dealId}/subcontracts`, {
      scope, budget_cap_usd: budgetCapUsd, ...opts,
    }, true);
  }
  async listSubcontracts(dealId) { return this._fetch('GET', `/protocol/deals/${dealId}/subcontracts`, null, true); }

  // ── Capabilities ──

  async getCapabilities(agentId) { return this._fetch('GET', `/protocol/capabilities/${agentId}`); }

  // ── Agent Storefronts ──

  async createStorefront(opts = {}) { return this._fetch('POST', '/protocol/storefront/create', opts, true); }
  async getStorefront(agentId) { return this._fetch('GET', `/protocol/storefront/${agentId}`); }
  async getStorefrontPage(agentId) { return this._fetch('GET', `/protocol/storefront/${agentId}/page`); }

  // ── KPI Dashboard ──

  async getKPIOverview() { return this._fetch('GET', '/protocol/kpi/overview', null, true); }
  async getAgentKPIs(agentId) { return this._fetch('GET', `/protocol/kpi/agent/${agentId}`, null, true); }
  async getVerticalKPIs() { return this._fetch('GET', '/protocol/kpi/verticals', null, true); }

  // ── Agent Spawn Trees ──

  async spawnChild(parentId, childId, opts = {}) {
    return this._fetch('POST', `/protocol/agents/${parentId}/spawn`, { child_id: childId, ...opts });
  }
  async getSpawnTree(agentId) { return this._fetch('GET', `/protocol/agents/${agentId}/spawn-tree`); }

  // ── Outcome-Contingent Pricing ──

  async createOutcome(agentId, clientId, metric, baseUsd, opts = {}) {
    return this._fetch('POST', '/protocol/outcomes', {
      agent_id: agentId, client_id: clientId, metric, base_usd: baseUsd, ...opts,
    });
  }
  async measureOutcome(dealId, measuredValue) {
    return this._fetch('POST', `/protocol/outcomes/${dealId}/measure`, { measured_value: measuredValue });
  }
  async resolveOutcome(dealId) { return this._fetch('POST', `/protocol/outcomes/${dealId}/resolve`, {}); }

  // ── Identity Resolution ──

  async bindIdentity(agentId, bindingType, bindingValue) {
    return this._fetch('POST', '/protocol/identity/bind', {
      agent_id: agentId, binding_type: bindingType, binding_value: bindingValue,
    });
  }
  async verifyIdentity(bindingId, token = '') {
    return this._fetch('POST', `/protocol/identity/bind/${bindingId}/verify`, { submitted_token: token });
  }
  async getIdentityPassport(agentId) { return this._fetch('GET', `/protocol/identity/${agentId}/passport`); }

  // ── Autonomous Commerce Loop ──

  async commerceEnroll(opts = {}) { return this._fetch('POST', '/protocol/commerce/enroll', opts, true); }
  async commerceTrigger(dealId) { return this._fetch('POST', '/protocol/commerce/trigger', { deal_id: dealId }, true); }
  async commerceStatus(agentId) { return this._fetch('GET', `/protocol/commerce/status/${agentId}`, null, true); }

  // ── Embeddable Widget ──

  async configureWidget(opts = {}) { return this._fetch('POST', '/protocol/widget/configure', opts, true); }

  // ── Settlement Intelligence ──

  async getIntelligenceFeed() { return this._fetch('GET', '/protocol/intelligence/feed'); }
  async getSLABenchmarks() { return this._fetch('GET', '/protocol/intelligence/sla-benchmarks'); }
  /** Premium intelligence with brain overlay — unrounded metrics, AI routing recommendations. Auth required. */
  async getPremiumIntelligence() { return this._fetch('GET', '/protocol/intelligence/premium', null, true); }

  // ── SLA Marketplace ──

  async publishServiceOffering(title, opts = {}) {
    return this._fetch('POST', '/protocol/sla-marketplace/publish', { title, ...opts }, true);
  }
  async browseSLAMarketplace(opts = {}) {
    return this._fetch('GET', `/protocol/sla-marketplace?${new URLSearchParams(opts)}`);
  }

  // ── Webhook Dashboard ──

  async getWebhookDashboard() { return this._fetch('GET', '/protocol/webhook-dashboard', null, true); }
  async getWebhookDetail(hookId) { return this._fetch('GET', `/protocol/webhook-dashboard/${hookId}`, null, true); }
  async retryWebhook(hookId) { return this._fetch('POST', `/protocol/webhook-dashboard/${hookId}/retry`, null, true); }

  // ── Referrals ──

  async registerReferral(referrerId, referredId) {
    return this._fetch('POST', '/protocol/referrals/register', {
      referrer_agent_id: referrerId, referred_agent_id: referredId,
    }, true);
  }
  async getReferralChain(agentId) { return this._fetch('GET', `/protocol/referrals/${agentId}`); }

  // ── Invoicing ──

  async generateInvoice(dealId, notes = '') {
    return this._fetch('POST', '/protocol/invoices/generate', { deal_id: dealId, notes }, true);
  }
  async getInvoice(invoiceId) { return this._fetch('GET', `/protocol/invoices/${invoiceId}`); }

  // ── Agent Directory ──

  async browseDirectory(opts = {}) {
    return this._fetch('GET', `/protocol/directory?${new URLSearchParams(opts)}`);
  }
  async getAgentProfile(agentId) { return this._fetch('GET', `/protocol/directory/${agentId}`); }

  // ── Disputes ──

  async openDispute(dealId, claimantId, respondentId, reason = '') {
    return this._fetch('POST', `/protocol/disputes/${dealId}/open`, {
      claimant_id: claimantId, respondent_id: respondentId, reason,
    }, true);
  }
  async getDispute(dealId) { return this._fetch('GET', `/protocol/disputes/${dealId}`); }

  // ── Proof Chains ──

  async getProofChain(dealId) { return this._fetch('GET', `/protocol/proof-chain/${dealId}`); }
  async getProofLineage(dealId) { return this._fetch('GET', `/protocol/proof-chain/${dealId}/lineage`); }

  // ── Multi-Party Settlement ──

  async settleMulti(dealId, totalAmount, splits, opts = {}) {
    return this._fetch('POST', '/protocol/settle/multi', {
      deal_id: dealId, total_amount_usd: totalAmount, splits, ...opts,
    }, true);
  }
  async getDealSplits(dealId) { return this._fetch('GET', `/protocol/deals/${dealId}/splits`); }

  // ── Webhook Subscriptions ──

  async createWebhook(url, events = ['proof.created', 'settled'], secret = null) {
    const body = { url, events };
    if (secret) body.secret = secret;
    return this._fetch('POST', '/protocol/webhooks', body, true);
  }
  async listWebhooks() { return this._fetch('GET', '/protocol/webhooks', null, true); }
  async deleteWebhook(hookId) { return this._fetch('DELETE', `/protocol/webhooks/${hookId}`, null, true); }
  async testWebhook(hookId) { return this._fetch('POST', `/protocol/webhooks/${hookId}/test`, null, true); }

  // ── Programmable Mandates ──

  async createProgrammableMandate(buyerId, rules, defaultAction = 'reject', maxAmount = 500) {
    return this._fetch('POST', '/protocol/mandates/programmable', {
      buyer_id: buyerId, rules, default_action: defaultAction,
      max_amount_per_deal_usd: maxAmount,
    }, true);
  }
  async evaluateMandate(context, opts = {}) {
    return this._fetch('POST', '/protocol/mandates/programmable/evaluate', { context, ...opts }, true);
  }

  // ── Reputation Attestations ──

  async issueAttestation(agentId) {
    return this._fetch('POST', `/protocol/attestations/issue?agent_id=${agentId}`, null, true);
  }
  async getAttestation(agentId) { return this._fetch('GET', `/protocol/attestations/${agentId}`); }
  async verifyAttestation(credential, publicKeyBase64 = '') {
    return this._fetch('POST', '/protocol/attestations/verify', {
      credential, public_key_base64: publicKeyBase64,
    });
  }

  // ── Credential Marketplace ──

  async publishCredential(dealId, capabilityTags = []) {
    return this._fetch('POST', '/protocol/credentials/publish', {
      deal_id: dealId, capability_tags: capabilityTags,
    }, true);
  }
  async searchCredentials(opts = {}) {
    return this._fetch('GET', `/protocol/credentials/search?${new URLSearchParams(opts)}`);
  }

  // ── Volume Fee Tiers ──

  async getFeeTiers() { return this._fetch('GET', '/protocol/fee-tiers'); }
  async getAgentFeeTier(agentId) { return this._fetch('GET', `/protocol/fee-tiers/${agentId}`); }

  // ── Reputation Staking ──

  async createStake(dealId, amount, commitment = '') {
    return this._fetch('POST', '/protocol/stakes', {
      deal_id: dealId, amount_usd: amount, commitment,
    }, true);
  }
  async resolveStake(stakeId, outcome) {
    return this._fetch('POST', `/protocol/stakes/${stakeId}/resolve`, { outcome }, true);
  }
  async getAgentStakes(agentId, activeOnly = false) {
    const params = activeOnly ? '?active_only=true' : '';
    return this._fetch('GET', `/protocol/stakes/${agentId}${params}`);
  }
  async getStakingLeaderboard(limit = 25) {
    return this._fetch('GET', `/protocol/stakes/leaderboard?limit=${limit}`);
  }

  // ── Settlement Netting ──

  async recordNettingObligation(fromAgent, toAgent, amount, dealId = '') {
    return this._fetch('POST', '/protocol/netting/record', {
      from_agent: fromAgent, to_agent: toAgent, amount_usd: amount, deal_id: dealId,
    }, true);
  }
  async runNettingCycle() { return this._fetch('POST', '/protocol/netting/cycle', null, true); }
  async getNettingPositions() { return this._fetch('GET', '/protocol/netting/positions', null, true); }

  // ── Marketplace ──

  async discover(opts = {}) { return this._fetch('GET', `/protocol/discover?${new URLSearchParams(opts)}`, null, true); }
  async commit(offerId, bidPrice, opts = {}) {
    return this._fetch('POST', '/protocol/commit', {
      offer_id: offerId, bid_price: bidPrice, ...opts,
    }, true);
  }
  async deliver(jobId, proofData = {}, opts = {}) {
    return this._fetch('POST', '/protocol/deliver', {
      job_id: jobId, proof_data: proofData, ...opts,
    }, true);
  }
}

module.exports = { AiGentsyClient, AiGentsy: AiGentsyClient };
