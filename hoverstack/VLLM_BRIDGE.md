# HoverStack → vLLM / SGLang Migration Bridge (Design Only)

This document defines the minimum handoff contract and runtime capability
requirements to port HoverStack's `reusable` and `batchable` behaviour into
a runtime that can actually exploit shared structure (vLLM or SGLang).

**Scope boundary.** Nothing in this file is implemented. HoverStack today
remains on HuggingFace `generate()` with lifecycle-level reuse only. Runtime-
native prefix caching, prefill/decode separation, and batched decode are
**not** attempted in the current substrate. This file is the interface
contract so the same policy signals can later drive a runtime where those
primitives exist.

---

## 1. Execution-plane handoff contract

When a future venue consumes HoverStack classifications, each cell submits
the following envelope alongside its prompt. All fields are additive.

| Field | Type | Origin | Purpose in runtime-native venue |
|---|---|---|---|
| `shape_id` | str | Shape Memory Graph | Grouping key for cache retention + batch co-scheduling. |
| `processing_class` | enum | FrequencyPolicy | Drives the mapping table in §3. |
| `preservation_action` | `retire` \| `preserve` | PreservationPolicy | Tells the runtime whether to retain any KV / cache entry at all. |
| `preservation_ttl_waves` | int | PreservationPolicy | Retention budget; runtime translates to cache residency priority. |
| `reuse_candidate` | bool | PreservationPolicy | Hint that prefix-cache pinning is likely to pay off. |
| `fold_candidate` | bool | PreservationPolicy | Eligible for batched decode / prefill folding. |
| `shared_prefix_signature` | str (hash) | New (computed at submit time) | Stable identifier for the prompt prefix to be matched against the runtime's prefix cache. |
| `cache_retention_priority` | int 0–3 | Derived from class | Passes through to runtime eviction policy (0 = ephemeral, 3 = reusable/batchable). |
| `batching_window_ms` | int | Derived from class | Runtime-side batch coalescing window; 0 disables. |

`shared_prefix_signature` is the only new computation vs what HoverStack
already has today; it is a content hash of the deterministic prompt prefix
(e.g. the system prompt + template head). Everything else is already
produced by `frequency_policy.py` and `preservation_policy.py`.

---

## 2. Runtime capability map (minimum bar)

HoverStack must **not** enable runtime-native reuse unless all of these are
present. Each is a hard dependency; partial support is rejected.

| Capability | Required behaviour |
|---|---|
| **Native prefix caching** | Runtime stores per-request KV cache indexed by prefix hash and can match a new request's prefix against cached tensors before prefill. Eviction policy must be controllable (priority or TTL). |
| **Prefill/decode separation** | Prefill and decode run as separable phases with observable timings; enables attributing time saved to prefix hits. |
| **True batched decode** | Runtime can decode N concurrent requests in a single forward pass at decode time (vLLM continuous batching / SGLang radix batched decode). |
| **Cache compatibility guarantee** | Two requests with identical prefix hashes produce bit-identical output distributions when prefix is reused. No silent divergence from fresh computation. |
| **Stable metrics surface** | Runtime exposes per-request prefix hit / miss, prefill tokens avoided, decode batch size, and cache residency time. Needed for proof. |

If any cell fails to satisfy all five, HoverStack downgrades its
classification and executes as today (lifecycle hover only).

---

## 3. Policy-to-runtime mapping (future plane)

| HoverStack class | vLLM / SGLang path | Cache priority | Batching window |
|---|---|---|---|
| `ephemeral` | Submit, execute, evict on completion. No prefix cache write. | 0 | 0 ms |
| `warm` | Lifecycle hover only. Prefix cache entry writeable but evicted aggressively. | 1 | 0 ms |
| `reusable` | Pin prefix in cache for `preservation_ttl_waves`. Priority slot on prefix-hit lookup. | 2 | 0 ms |
| `batchable` | Prefix pinned + request enters batched-decode window. Runtime folds concurrent same-shape work into a single forward pass. | 3 | runtime-tuned (e.g. 25–50 ms) |

A downgraded cell (see §2 rejection) drops one row: `batchable → reusable →
warm → ephemeral`. Never upgrades.

---

## 4. Proof continuity

Runtime-native reuse metrics must flow into the HoverStamp **without
changing Level 1 proof semantics.**

The existing `evidence.hoverstamp` envelope (added to ProofPack in the
Level 1 HoverStamp→ProofPack integration) remains the sole attachment
point. Future venues extend only the inner HoverStamp payload with these
additive fields:

```json
{
  "runtime_venue": "vllm" | "sglang" | "hf_generate",
  "prefix_cache_hit": true,
  "prefill_tokens_avoided": 128,
  "decode_batch_size": 4,
  "cache_residency_ms": 4200,
  "shared_prefix_signature": "sha256:…",
  "cache_retention_priority": 2
}
```

Rules (unchanged from Level 1):

- These fields are optional and additive. Absence must not break any consumer.
- They do **not** participate in `proof_hash`, verification, acceptance, or
  settlement. `proof_hash` stays invariant to their presence.
- Older validators ignore unknown fields safely.
- The ProofPack schema is **not** modified to accommodate them; they live
  inside the already-optional `evidence.hoverstamp` object.

This preserves: v1 lifecycle shaping → frequency-aware classification →
selective preservation (today) → runtime-native reuse (future), all
surfacing through one portable artifact without changing what "valid
proof" means.

---

## 5. What this bridge deliberately does not define

- A vLLM / SGLang adapter implementation.
- Any change to `proof_pipe.create_proof` or the ProofPack schema.
- Any new public execution state. Active / Hover / Retire remain the only
  public states.
- Any change to the utility function or scoring.
- Any custom kernel, model modification, or speculative path.

Those are separate work items, each gated on §2 being satisfied by the
target runtime.
