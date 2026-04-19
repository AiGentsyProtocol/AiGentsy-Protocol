# vLLM Deployment — Running the HoverStack Runtime Benchmark

This document describes how to run `hoverstack.runtime_bench` on a host
that can actually host vLLM. The benchmark cannot run on darwin/arm64
or any CPU-only box; vLLM's prefix-caching path requires CUDA.

## Host requirements

- Linux x86_64 (Ubuntu 22.04 or similar) with CUDA 12.1+
- NVIDIA GPU, ≥ 16 GB VRAM for a 7/8B model, ≥ 24 GB for 13B
- Python 3.10 or 3.11
- `pip install vllm` (pulls the matching torch build)
- Network access to download a HuggingFace model (or a local path)

Example install:

```bash
python -m venv .venv && source .venv/bin/activate
pip install "vllm>=0.6" transformers
```

## Running the benchmark

From the repo root, with `hoverstack/` on `PYTHONPATH`:

```bash
# 6-wave default (about 60 cells per mode, 3 modes = 180 generations)
python -m hoverstack.runtime_bench --adapter vllm \
    --model meta-llama/Llama-3.1-8B-Instruct --waves 6

# Short 3-wave dry-run first:
python -m hoverstack.runtime_bench --adapter vllm \
    --model meta-llama/Llama-3.1-8B-Instruct --waves 3
```

Output lands in `runs/<timestamp>_vllm_runtime/summary.json` with the
exact fields the harness prints at the end.

## What the benchmark measures

Three modes over the same workload (classify / summarize / extract /
reason with shared system-prompt + few-shot prefixes):

| Mode | HoverStack policy | Runtime-native reuse |
|---|---|---|
| `baseline` | none | none |
| `lifecycle_only` | classification + preservation | **disabled at adapter boundary** |
| `runtime_native` | classification + preservation | enabled (prefix cache on) |

`lifecycle_only` vs `runtime_native` is the interesting delta. If
`runtime_native` materially beats `lifecycle_only` on p95 and/or total,
HoverStack's `reusable` and `batchable` classes have finally landed in
a substrate that can pay them off. If not, the honest report says so.

## Capability map

`VLLMAdapter.capabilities()` reports all five caps `true` when
`enable_prefix_caching=True` at init. If the runtime can't honor one,
flip the flag in the adapter and the benchmark will auto-downgrade
reusable/batchable to `warm` at the boundary.

## Proof fields added to HoverStamp

Additive only; absent on baseline / lifecycle modes unless the runtime
measured them:

- `runtime_name` — `vllm`
- `runtime_capabilities` — capability map snapshot
- `runtime_prefix_cache_hit` — bool per request
- `runtime_prefill_ms`, `runtime_decode_ms` — when vLLM exposes them
- `runtime_decode_batch_size` — 1 for single submit, N for batched
- `runtime_prefill_tokens_avoided` — heuristic; labelled so downstream
  consumers know whether it's vLLM-native or adapter-heuristic
- `runtime_queue_ms` — when available

None of these fields affect `proof_hash`, verification, acceptance, or
settlement. ProofPack v1 semantics are untouched (VLLM_BRIDGE.md §4).

## What is NOT claimed

- No claim that HuggingFace `generate()` on MPS can exploit prefix
  reuse. That was already settled.
- No performance claim generated from the reference simulator.
  `runtime_bench --adapter reference` marks `runtime_native_reuse_meaningful=false`
  in its summary and is used only for contract testing.
- No kernel changes, no model modifications, no speculative decoding,
  no recursive folding. vLLM's built-in automatic prefix cache is the
  only runtime mechanism relied on.
