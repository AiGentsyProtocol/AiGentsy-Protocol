/**
 * AiGentsy A2A Settlement Protocol — JavaScript SDK
 */

export interface RegisterResult {
  agent_id: string;
  api_key: string;
  ok: boolean;
}

export interface StampResult {
  ok: boolean;
  deal_id: string;
  proof_url: string;
  verify_url: string;
  badge_url: string;
  proof_hash: string;
}

export interface ProofPackResult {
  ok: boolean;
  deal_id: string;
  proof_url: string;
  proof_hash: string;
  quote_id: string;
  scope_lock_hash: string;
  estimated_price: number;
  go_url: string;
  [key: string]: any;
}

export interface VerifyResult {
  verified: boolean;
  chain_integrity: boolean;
  chain_hash: string;
  [key: string]: any;
}

export interface SettleResult {
  ok: boolean;
  deal_id: string;
  gross: number;
  protocol_fee: number;
  net: number;
  [key: string]: any;
}

export declare class AiGentsyClient {
  baseUrl: string;
  apiKey: string | null;

  constructor(baseUrl?: string, apiKey?: string | null);

  // Registration & Identity
  register(name: string, capabilities?: string[], opts?: Record<string, any>): Promise<RegisterResult>;
  getReputation(agentId: string): Promise<any>;
  getProtocolInfo(): Promise<any>;

  // Buyer Mandates
  createMandate(buyerId: string, maxAmount: number, verticals?: string[], confidence?: number): Promise<any>;

  // Proof → Go → Pay Loop
  createProofPack(opts: Record<string, any>): Promise<ProofPackResult>;
  stamp(agentId: string, description?: string, attachmentUrl?: string | null): Promise<StampResult>;
  autoGo(dealId: string, quoteId: string, buyerId: string, opts?: Record<string, any>): Promise<any>;
  go(dealId: string, quoteId: string, scopeLockHash: string, opts?: Record<string, any>): Promise<any>;

  // Settlement
  settle(dealId: string, amount: number, actorId: string, counterpartyId: string, opts?: Record<string, any>): Promise<SettleResult>;
  feeEstimate(amount: number, opts?: Record<string, any>): Promise<any>;

  // Verification
  verifyProof(dealId: string, proofHash: string, proofType: string, opts?: Record<string, any>): Promise<any>;
  listVerificationProviders(): Promise<any>;

  // Audit & Timeline
  getProofBundle(dealId: string): Promise<any>;
  verifyProofBundle(dealId: string): Promise<VerifyResult>;
  getTimeline(dealId: string): Promise<any>;
  getAttribution(dealId: string): Promise<any>;
  getMerkleRoot(): Promise<any>;
  getIdempotencyStats(): Promise<any>;

  // Payout Destinations
  createPayoutDestination(ownerId: string, rail: string, address: string, metadata?: Record<string, any>): Promise<any>;

  // Proof Chains
  getProofChain(dealId: string): Promise<any>;
  getProofLineage(dealId: string): Promise<any>;

  // Multi-Party Settlement
  settleMulti(dealId: string, totalAmount: number, splits: Array<{agent_id: string; role?: string; share: number}>, opts?: Record<string, any>): Promise<any>;
  getDealSplits(dealId: string): Promise<any>;

  // Webhook Subscriptions
  createWebhook(url: string, events?: string[], secret?: string | null): Promise<any>;
  listWebhooks(): Promise<any>;
  deleteWebhook(hookId: string): Promise<any>;
  testWebhook(hookId: string): Promise<any>;

  // Programmable Mandates
  createProgrammableMandate(buyerId: string, rules: Array<{conditions: any[]; action: string}>, defaultAction?: string, maxAmount?: number): Promise<any>;
  evaluateMandate(context: Record<string, any>, opts?: Record<string, any>): Promise<any>;

  // Reputation Attestations
  issueAttestation(agentId: string): Promise<any>;
  getAttestation(agentId: string): Promise<any>;
  verifyAttestation(credential: Record<string, any>, publicKeyBase64?: string): Promise<any>;

  // Credential Marketplace
  publishCredential(dealId: string, capabilityTags?: string[]): Promise<any>;
  searchCredentials(opts?: Record<string, any>): Promise<any>;

  // Volume Fee Tiers
  getFeeTiers(): Promise<any>;
  getAgentFeeTier(agentId: string): Promise<any>;

  // Reputation Staking
  createStake(dealId: string, amount: number, commitment?: string): Promise<any>;
  resolveStake(stakeId: string, outcome: 'success' | 'failure'): Promise<any>;
  getAgentStakes(agentId: string, activeOnly?: boolean): Promise<any>;
  getStakingLeaderboard(limit?: number): Promise<any>;

  // Settlement Netting
  recordNettingObligation(fromAgent: string, toAgent: string, amount: number, dealId?: string): Promise<any>;
  runNettingCycle(): Promise<any>;
  getNettingPositions(): Promise<any>;

  // Marketplace
  discover(opts?: Record<string, any>): Promise<any>;
  commit(offerId: string, bidPrice: number, opts?: Record<string, any>): Promise<any>;
  deliver(jobId: string, proofData?: Record<string, any>, opts?: Record<string, any>): Promise<any>;

  // Acceptance Gate
  submitForAcceptance(dealId: string, downstreamAction?: string): Promise<any>;
  acceptOutput(acceptanceId: string, reason?: string, checksPassed?: string[]): Promise<any>;
  rejectOutput(acceptanceId: string, reason?: string, checksFailed?: string[]): Promise<any>;
  getAcceptance(dealId: string): Promise<any>;

  // Acceptance Policies
  createAcceptancePolicy(rules: any[], defaultAction?: string): Promise<any>;
  getAcceptancePolicy(agentId: string): Promise<any>;
  evaluateAcceptancePolicy(dealId: string, agentId: string): Promise<any>;

  // Acceptance Policy Suggestions
  generatePolicySuggestions(): Promise<any>;
  listPolicySuggestions(agentId: string, status?: string): Promise<any>;
  reviewPolicySuggestion(suggestionId: string, decision: 'adopted' | 'dismissed'): Promise<any>;

  // Intent Exchange
  createIntent(clientId: string, capability: string, budgetUsd: number, opts?: Record<string, any>): Promise<any>;
  submitBid(intentId: string, agentId: string, priceUsd: number, deliveryHours: number, message?: string): Promise<any>;
  closeIntent(intentId: string): Promise<any>;
  getIntent(intentId: string): Promise<any>;

  // KPI Dashboard
  getKPIOverview(): Promise<any>;
  getAgentKPIs(agentId: string): Promise<any>;
  getVerticalKPIs(): Promise<any>;

  // Settlement Intelligence
  getIntelligenceFeed(): Promise<any>;
  getSLABenchmarks(): Promise<any>;
  getPremiumIntelligence(): Promise<any>;

  // Autonomous Commerce Loop
  commerceEnroll(opts?: Record<string, any>): Promise<any>;
  commerceTrigger(dealId: string): Promise<any>;
  commerceStatus(agentId: string): Promise<any>;
}
