# HoverStack Versioned Apex Roadmap

Structural milestones tied to real implementation work.

## v1.2 — External Verification Becomes Routine

**Status: COMPLETE**

- [x] Ed25519 asymmetric signing (v1.1 foundation)
- [x] `governance_verifier.py` — standalone offline verifier (CLI + library)
- [x] Clean-machine verification flow (zero runtime dependency)
- [x] `policy_snapshot.py` — declarative, hashed policy capture
- [x] `policy_hash` field on GovernanceArtifact (backward compatible)
- [x] Refusal formalized as first-class governance act (`governance_act`, `refusal_type`, `chosen_instead`)
- [x] `apex_demo.py` — minimum convincing loop (end-to-end proof)
- [x] Backward compatibility: v1 HMAC, v1.1 Ed25519, v1.2 policy_hash all coexist

**Evidence:** `python -m hoverstack.apex_demo` passes all 6 steps.
**Claim now true:** "A HoverStack governance artifact can be verified independently, without access to our infrastructure."

## v1.3 — Economic Selectivity, Honest Reporting, and Benchmark Truthfulness

**Status: COMPLETE**

### Scoreboards & Memory Hardening
- [x] `scoreboards.py` — three official reporting planes (latency / governance / economic)
- [x] Shape Policy Memory hardening (behavioral):
  - [x] `persistent_low_value`, `stuck_warm`, `negative_net_persistent` tags
  - [x] Tags drive actual TTL reduction via `decide_with_cost(shape_tags=...)`
  - [x] `retire_aggressive` preservation recommendation
- [x] `deployment_modes.py` — three official deployment modes formalized

### Benchmark Rebuild (tests HoverStack where it structurally wins)
- [x] `bench_paraphrased.py` — paraphrased regime suite
  - Same shape_id, different prompt surface text per wave
  - vLLM prefix cache: near-zero hits. HoverStack recall: shape_id-based, holds.
  - Classifier accuracy reported separately from recall success rate
  - Recall reported at 0.7 / 0.85 / 0.9 reference thresholds
- [x] `bench_cold_start.py` — cross-session rehydration benchmark
  - Warm-up → persist priors → cold restart → rehydrate → measure advantage
  - Uses existing RuntimePriors persistence (no new mechanism)
- [x] `bench_report.py` — honest reporting layer
  - Every wall-clock claim scoped to the workload it's true on
  - No merged "HoverStack is X% faster" headline
  - Existing four-regime suite preserved as regression evidence
- [x] Speculation (risk-gated parallel paths) deferred — requires runtime work outside benchmark scope

**Evidence:** Four existing regimes pass as regression. New paraphrased + cold-start regimes test structural advantages. Honest report layer produces scoped claims only.

## v1.4 — Enterprise Packaging (NEXT)

Target work:
- [ ] Enterprise Policy Appliance packaging (single-binary or container)
- [ ] Consequence-ready governance events (link to AiGentsy consequence_graph)
- [ ] Governance artifact → PDF export for compliance review
- [ ] Risk-gated speculative execution (parallel recall + full-compute paths) — deferred from v1.3, requires runtime work
- [ ] Licensing/product packaging readiness
- [ ] Integration test: HoverStack governance artifact → ProofPack → bundle → aigentsy-verify → governance_verifier

## v1.4 — Multi-Agent Coordination

**Status:** Benchmark shipped, awaiting CUDA validation.

**Claim:** AiGentsy's coordination layer can batch shape-similar requests
from multiple agents, amortizing GPU compute across a single model
invocation while emitting per-agent proof bundles. This is a capability
only the settlement/coordination layer can deliver — inference providers
don't see cross-agent traffic, agent frameworks don't see cross-framework
traffic.

**Benchmark:** `hoverstack/bench_multi_agent.py` exercises 3 workload
distributions (uniform, clustered, zipfian) × 4 batching windows (100/250/500/1000ms)
× 2 conditions (baseline, coordinated). Supports --num_agents scaling from
100 (medium) to 1000 (large).

**Structural guarantees preserved:**
- Proof completeness rate 1.0 across all conditions (each agent still gets
  its own proof bundle with governance attestation)
- Shape-identity recall (v1.3) composes with batching (v1.4)
- No changes to settlement API, proof bundle spec, or Merkle log schema

**CUDA validation:** [pending — results to be appended]

## v1.4 — Proof-Bundle Reuse Across Agents

**Status:** Feature shipped, awaiting CUDA validation.

**Claim:** AiGentsy's settlement layer detects when a request's (prompt_instance, mandate, policy) triple has been fulfilled previously and serves the prior proof bundle with a new per-agent attestation. The compute is amortized across all agents whose settlements reference the same work.

**Simulation finding:** 33.1% warm-cache hit rate on realistic agent traffic (Zipf-concentrated shapes, pool of 100 mandates, 10K-request simulation). Equivalent to ~33% GPU-compute elimination at the settlement layer.

**Settlement-layer exclusivity:** this capability is only available at the coordination/settlement layer. Inference providers cannot see cross-agent request identity. Agent frameworks cannot see cross-framework traffic. AiGentsy sees every settlement and every proof is content-addressable in the Merkle log.

**Structural guarantees preserved:**
- Proof completeness rate 1.0 on both cache-hit and cache-miss paths
- Reused proofs are cryptographically bound to original bundle hashes
- Invalidation is explicit (policy change, mandate revision) — no time-based expiration
- All hit-path attestations pass external `aigentsy_verify.verify_bundle()`

**Parked — shape-clustering:** The v1.4 shape-clustering coordinator hypothesis did not validate on CUDA. Coordinator code retained for future experiments; not in the apex pitch.

**CUDA validation:** [pending]

## v1.5 Wave 1 — Non-Acceleration Compute Savings

**Status:** Feature shipped, awaiting CUDA validation.

Three features additive to v1.4 proof-reuse, extending the
"produce the same verifiable outcome with less new expensive work"
category.

- **Negative proof caching:** refusal attestations reused under active
  policy, preventing re-evaluation of known-bad requests
- **Pre-approval attestation:** separate attestation type emitted at
  mandate commitment, authorizing downstream work without
  per-request re-authorization
- **Shared verifier state:** VerifierSession API in aigentsy_verify
  SDK, reducing redundant policy-snapshot verification across bundles

Principle: AiGentsy does not optimize compute speed. It reduces
the amount of expensive computation required to produce an
accepted, verifiable outcome. v1.4 amortized work. v1.5 Wave 1
amortizes refusals and authorizations.

**CUDA validation:** [pending]

## v1.5 Wave 2 — Mandate-Driven Routing and Budget Enforcement

**Status:** Feature shipped, awaiting CUDA validation.

Two features extending mandate-graph semantics from pure authorization
into compute-allocation control.

- **Mandate-driven model routing:** mandates declare routing_tier
  (fast/full). Settlement layer routes compute accordingly. Routing
  decision is attested.
- **Mandate-bounded compute limits:** mandates declare compute_budget_tokens.
  Runtime tracks cumulative consumption per (mandate, agent) and
  enforces hard-stop at budget exceeded. Budget state is attested.

Principle: mandates express not just "what is authorized" but "how
much compute is authorized." The settlement layer enforces both,
making runaway agent behavior cryptographically impossible.

**CUDA validation:** [pending]

## v1.5 Wave 3 — Delta-Savings Curve Publication

**Status:** Benchmark shipped, awaiting CUDA validation.

Characterization of v1.3 delta-compute plane across controlled prompt-diff
percentages (1%, 5%, 10%, 25%, 50%). Not a new feature — a published
savings curve exercising existing capability. Establishes breakeven
thresholds for production deployment decisions.

**CUDA validation:** [pending]

## v1.6 — Delta-Within-Reuse

**Status:** Feature shipped, awaiting CUDA validation.

Extends v1.4 proof-reuse with a third tier: when a cached proof bundle
exists for the same (mandate, policy) but prompt differs slightly
(≤15% diff by default), the cached bundle serves as a delta-compute
baseline. Delta plane (v1.3) + proof cache (v1.4) compose.

Principle: the settlement layer stacks cache tiers. Exact triples serve
from cache. Near-miss triples compute only the delta. Cold triples run
full compute. Compute savings compound across tiers.

**CUDA validation:** [pending]

## Future work beyond v1.6

- **Imperfect classification testing.** Requires a shape_id classifier that runs on raw prompt text rather than relying on the prompt builder's assigned shape. This tests whether HoverStack's recall holds when classification itself is fallible. Out of scope for v1.3 and v1.4. Candidate for v1.5+.
