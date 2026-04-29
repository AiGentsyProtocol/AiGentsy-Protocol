# AiGentsy Protocol

Provable. Payable. Institutional. The protocol stack for proving, verifying, accepting, and settling AI agent work. Specs, CUDA-validated benchmarks, conformance tests, and verifier SDK.

*Last updated: April 2026*

## What this is

AiGentsy is the protocol stack for proving, verifying, accepting, and settling real AI agent work. When agents do consequential work, something has to prove it happened, validate it under policy, and authorize the next step, whether that step is money moving or downstream state advancing. That is not optional. This repo holds the public surface of what it takes to do it correctly.

## Quick start

Verify a proof offline:

    pip install aigentsy-verify

Run the end-to-end demo against the production runtime:

    pip install httpx aigentsy-verify
    python examples/hello_e2e.py

## Contents

- `protocol/` - protocol specifications (10 graph specs) and primitive reference implementations (30 files)
- `sdk/` - Python client, JavaScript client, and standalone offline verifier
- `adapters/` - integrations for LangChain, LangGraph, LlamaIndex, AutoGen, CrewAI, OpenAI, Vercel AI, and MCP
- `aigentsy-langgraph/` - LangGraph-native nodes
- `hoverstack/` - HoverStack compute amortization methodology, CUDA runbook, and one self-contained benchmark
- `tests/conformance/` - portable conformance tests and settlement vectors
- `data/` - CUDA-validated benchmark result JSONs and conformance vectors
- `examples/hello_e2e.py` - single-command end-to-end settlement demo

## Results

All headline claims are backed by JSON artifacts in `data/`.

- v1.3 paraphrased recall and governance: `hoverstack_v13_results_reference.json`
- v1.4 proof-bundle reuse across agents (32.35% hit rate): `proof_reuse_conformance_vectors.json`
- v1.5 Wave 1 negative cache and pre-approval: `v15_wave1_results.json`
- v1.5 Wave 2 mandate-driven routing and budget enforcement: `v15_wave2_results.json`
- v1.5 Wave 3 delta-savings curve: `delta_savings_curve.json`
- v1.6 delta-within-reuse (94.1% prefix alignment, PASS): `v16_delta_reuse_results.json`
- v1.7 ProofPack Reuse (GH200: ~78% wall-clock reduction on mixed_composition multi-agent workload; A100: ~59% on exact_reuse; ablation-confirmed): `V17_MULTIAGENT_FINAL_ANALYSIS.md`

## What's new in v1.7

ProofPack Reuse, the publicly named version of Prior-Artifact Sufficiency, is now the benchmark-proven v1.7 mechanism. The GH200 multi-agent mixed_composition benchmark showed 77.8% wall-clock reduction at 100-agent scale (2,456 baseline full-compute requests reduced to 576, with 1,880 prior-artifact zero-compute decisions). Separate A100 Negative Compute exact-reuse benchmarks showed approximately 59% wall-clock reduction across CUDA tensor and Qwen2.5-7B LLM inference runs. Ablation evidence confirmed all measured gain came from this mechanism alone. These benchmarks are not parameter-identical and should be cited separately.

Other v1.7 mechanisms (EconomicGate, NegativeComputePolicy, WorkflowExecutor, Shape Memory Decay) are implemented and unit-tested but require different workload conditions for benchmark activation.

AiGentsy uses Stripe Connect for money movement and freetsa.org for RFC 3161 timestamp anchoring. No blockchain, no fund custody, works with existing payment rails.

## Integration

Serious deployment partners integrate via one of the adapters in `adapters/` or via the Python client in `sdk/python/`. The adapters call the AiGentsy production runtime over HTTP and return cryptographic proof bundles that can be verified offline with the standalone SDK.

The full benchmark runtime is in a private repo. Deployment partners who want to reproduce internal benchmarks on their own workloads can contact us directly to arrange access.

## License

Apache 2.0. See LICENSE.

## Contact

w@aigentsy.com
