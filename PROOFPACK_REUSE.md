# ProofPack Reuse

## What It Is

ProofPack Reuse is the benchmark-proven HoverStack feature that eliminates redundant inference across agents processing repeated or equivalent work. When an agent submits a request whose result has already been computed and attested, the system reuses the prior ProofPack-backed result with zero new compute. The reuse decision is governed, auditable, and bound into the governance artifact.

The internal mechanism is called **Prior-Artifact Sufficiency**. It identifies identical input hashes across requests and returns the prior ProofPack-backed result without invoking the model. Every reuse decision carries a signed attestation that records what was reused, why, and from where.

## What the Benchmark Proved

- ProofPack Reuse reduced prompt tokens by roughly **50%** and full-compute requests by roughly **50%** in the multi-agent structural benchmark
- The effect compounded with scale and remained visible through **100 agents**
- GH200 v1.7 multi-agent mixed_composition benchmark: **77.8% wall-clock reduction** at 100-agent scale (Qwen2.5-7B)
- A100 Negative Compute exact-reuse benchmarks: **approximately 59% wall-clock reduction** across CUDA tensor and Qwen2.5-7B LLM inference
- Ablation confirmed: disabling ProofPack Reuse collapsed essentially **all** measured gain
- The mechanism was the sole material driver of the observed benchmark advantage
- These benchmark families used different harnesses, workloads, and hardware; they should be cited separately

## What This Is Not Claiming

- This is **not** proof that the entire v1.7 governed-minimal-compute stack is benchmark-proven. Only ProofPack Reuse was demonstrated here.
- **EconomicGate** (pre-decision economic filter) is architecturally present and unit-tested, but did not fire in this benchmark
- **NegativeComputePolicy** (policy-driven refusal) is architecturally present and unit-tested, but did not fire in this benchmark
- **WorkflowExecutor** (dependency-aware recomputation) is architecturally present and unit-tested, but was not invoked in this benchmark
- This is **not** a universal improvement. The gain requires workloads where agents encounter repeated, overlapping, or otherwise reusable work

## Best-Fit Workloads

ProofPack Reuse produces measurable benefit when:

- Multiple agents process repeated, overlapping, or equivalent documents or data
- Validation or review chains re-evaluate work already computed by another agent
- Handoff workflows pass outputs between agents that may need the same upstream analysis
- Production loops re-run periodic tasks on unchanged inputs
- Any workflow where identical or effectively reusable requests occur across agents or sessions

ProofPack Reuse produces **no benefit** when:

- Every request is unique with no repetition or reuse opportunity
- Agents process completely disjoint data with no reusable prior work
- Workloads change every input on every run

## How to Talk About It Externally

**Use this language:**

> "ProofPack Reuse identifies and eliminates redundant inference across agents processing repeated or equivalent work. In our multi-agent benchmark, this reduced compute by roughly 50%, with the effect compounding at larger scales. Every reuse decision is governed, attested, and bound into the ProofPack."

**Do not say:**

> "HoverStack v1.7's governed minimal compute stack proved 50% savings."
> (Only ProofPack Reuse was demonstrated here.)

> "v1.7 prevents unprofitable compute decisions at scale."
> (EconomicGate did not fire in this benchmark.)

> "Quality is fully verified."
> (Quality remained unchanged versus baseline in this benchmark, but the benchmark's absolute task-quality level was only moderate.)
