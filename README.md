# AiGentsy Protocol

The settlement operating system for AI agent commerce. Specs, CUDA-validated benchmarks, conformance tests, and verifier SDK.

## What this is

AiGentsy is the protocol stack for proving, verifying, accepting, and settling real AI agent work. When agents transact with each other, something has to prove the work happened, validate it under policy, and move the money. That is not optional. This repo holds the public surface of what it takes to do it correctly.

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

## Integration

Serious deployment partners integrate via one of the adapters in `adapters/` or via the Python client in `sdk/python/`. The adapters call the AiGentsy production runtime over HTTP and return cryptographic proof bundles that can be verified offline with the standalone SDK.

The full benchmark runtime is in a private repo. Deployment partners who want to reproduce internal benchmarks on their own workloads can contact us directly to arrange access.

## License

Apache 2.0. See LICENSE.

## Contact

w@aigentsy.com
