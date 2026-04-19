# HoverStack vLLM CUDA Runbook — First Real Venue Benchmark

Exact steps to run `hoverstack.runtime_bench` against real vLLM on a
fresh CUDA Linux host. One operator, one session, no simulation, no
guessing.

**Target commit:** `83f57ee22e987029417002eb6643f301c9d86ea6` on `main`
(GitLab `origin`). Verify after clone with:

```bash
git rev-parse HEAD
# expect: 83f57ee22e987029417002eb6643f301c9d86ea6
```

If the displayed HEAD does not match, stop and resync — the benchmark
harness and adapter are tied to that commit.

---

## 0 · Host requirements (verify before any install)

- Linux x86_64 (Ubuntu 22.04 LTS recommended)
- NVIDIA GPU: A10G / L4 / A100 / H100 class
  - ≥ 16 GB VRAM for 7B–8B models (A10G 24 GB works; L4 24 GB works)
  - ≥ 40 GB VRAM if you want to try a 13B model
- CUDA 12.1+ driver installed (`nvidia-smi` responsive)
- Python 3.10 or 3.11 (NOT 3.12; vLLM wheels are sparser there)
- Outbound network to `pypi.org`, `huggingface.co`, `gitlab.com`,
  `aigentsy-ame-runtime.onrender.com`

```bash
nvidia-smi                      # must print the driver + GPU
python3 --version                # must be 3.10 or 3.11
```

---

## 1 · Fresh-host install

All commands assume a non-root user with sudo, from home directory.

```bash
# ── 1.1 System tools ──
sudo apt-get update
sudo apt-get install -y git python3-venv python3-pip

# ── 1.2 Clone the repo ──
# SSH preferred; HTTPS with a deploy token also works.
git clone git@gitlab.com:AiGentsy/aigentsy-ame-runtime.git
# OR:
# git clone https://gitlab.com/AiGentsy/aigentsy-ame-runtime.git

cd aigentsy-ame-runtime
git checkout main
git rev-parse HEAD  # expect 83f57ee22e987029417002eb6643f301c9d86ea6

# ── 1.3 Python venv + deps ──
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

# vLLM brings the matching torch CUDA build automatically.
pip install "vllm>=0.6,<0.12" transformers

# Sanity: import should succeed and report a CUDA device.
python - <<'PY'
import torch, vllm
print("torch", torch.__version__, "cuda", torch.cuda.is_available(),
      "device", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none")
print("vllm", vllm.__version__)
PY
```

**Abort if** `torch.cuda.is_available()` is `False`, or if `vllm`
import fails. Do not proceed — the adapter will fail meaningfully
but the run will not be honest.

---

## 2 · Environment variables

```bash
# ── HuggingFace auth (required for gated models like Llama-3.1) ──
export HF_TOKEN="hf_xxx_your_read_token"      # https://hf.co/settings/tokens
# or: huggingface-cli login

# ── Model cache (optional but recommended on ephemeral disks) ──
export HF_HOME="$HOME/.cache/huggingface"

# ── Model selection ──
# Gated (preferred):
export MODEL="meta-llama/Llama-3.1-8B-Instruct"
# Ungated fallback if HF access is a blocker:
# export MODEL="Qwen/Qwen2.5-7B-Instruct"
# Smaller fallback for a 16 GB card if OOM:
# export MODEL="Qwen/Qwen2.5-3B-Instruct"

# ── ProofPack attachment closure ──
export AME_BASE="https://aigentsy-ame-runtime.onrender.com"
```

No HoverStack env vars are required — the adapter reads flags from
constructor defaults in `hoverstack/runtime_vllm.py`.

---

## 3 · Phase 1 — Verify venue (no inference)

Before any benchmark, verify the adapter loads and the capability map
reports what it should:

```bash
python - <<'PY'
from hoverstack.runtime_vllm import VLLMAdapter
a = VLLMAdapter()
print("caps (pre-load):", a.capabilities().to_dict())
# Pre-load capabilities reflect CONFIG, not a live runtime. They
# should show prefix_cache=True, safe_reuse_enabled=True based on
# the adapter defaults. Loading the model next validates the path.
PY
```

Expected output includes `"safe_reuse_enabled": true`. If not, stop
and inspect `runtime_vllm.py`.

---

## 4 · Phase 2 — Short run (3 waves)

This verifies: model load, adapter-produced requests, vLLM metric
surface, HoverStamp population.

```bash
# Roughly 90 cells total (30 per mode, 3 modes). Expect ~5–15 min
# on an A10G for an 8B model; first run includes one-time model load.
python -m hoverstack.runtime_bench \
    --adapter vllm \
    --model "$MODEL" \
    --waves 3 \
    --run-dir runs/vllm_short_3w
```

Expected signals of success (check the printed JSON):

- `"adapter": "vllm"`
- `"adapter_is_simulated": false`
- `"runtime_native_reuse_meaningful": true`
- `"capabilities.safe_reuse_enabled": true`
- `"per_request.runtime_native.prefix_cache_hits"` > 0 on waves ≥ 2

If `runtime_native_reuse_meaningful` is `false`, stop. Capability gate
did not pass. Inspect `runs/vllm_short_3w/summary.json → capabilities`.

---

## 5 · Phase 3 — Extended run (6 waves)

Only run once Phase 2 reports success. This is the real number.

```bash
python -m hoverstack.runtime_bench \
    --adapter vllm \
    --model "$MODEL" \
    --waves 6 \
    --run-dir runs/vllm_ext_6w
```

Wall clock budget: ~15–40 min on an A10G (model-dependent). Watch
`nvidia-smi` in another shell if you want live VRAM confirmation.

The summary at `runs/vllm_ext_6w/summary.json` contains the full
per-mode metrics. Key deltas to inspect:

- `deltas_vs_baseline_pct.runtime_native_total_ms` — positive = faster
- `deltas_vs_baseline_pct.runtime_native_vs_lifecycle_total_ms`
  — positive = runtime-native beat lifecycle-only
- `deltas_vs_baseline_pct.runtime_native_p95_ms` — p95 improvement

---

## 6 · Phase 4 — ProofPack attachment closure

Take one real HoverStamp-shaped payload from the 6-wave run and attach
it to the already-live Level 1 ProofPack endpoint. No server changes.

```bash
# Extract the runtime HoverStamp from the 6-wave summary and POST it.
python - <<'PY'
import json, os, urllib.request

base = os.environ["AME_BASE"]
summary = json.load(open("runs/vllm_ext_6w/summary.json"))

# Use the first runtime_native entry's additive runtime fields as the
# HoverStamp payload. We fabricate nothing; every key comes from the
# actual vLLM response surface. If a metric wasn't populated, it's
# absent from the envelope.
rn = summary["per_request"]["runtime_native"]
caps = summary["capabilities"]
model = summary["model"]
hoverstamp = {
    "runtime_name": "vllm",
    "runtime_capabilities": caps,
    "runtime_model": model,
    "runtime_native_reuse_meaningful": summary["runtime_native_reuse_meaningful"],
    "runtime_per_request_summary": rn,
}

req = {
    "agent_username": "hoverstack_runtime_proof",
    "vertical": "marketing",
    "proof_type": "completion_photo",
    "scope_summary": "First real CUDA vLLM HoverStack run",
    "proof_data": {
        "photo_url": "https://aigentsy.com/proof",
        "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "location": "remote"
    },
    "hoverstamp": hoverstamp,
}
r = urllib.request.Request(
    base + "/protocol/proof-pack",
    data=json.dumps(req).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
resp = urllib.request.urlopen(r, timeout=30).read().decode()
out = json.loads(resp)
print(json.dumps({
    "ok": out.get("ok"),
    "deal_id": out.get("deal_id"),
    "proof_hash": out.get("proof_hash"),
    "evidence_present": "evidence" in out,
    "evidence_hoverstamp_keys": sorted(out.get("evidence", {}).get("hoverstamp", {}).keys()),
}, indent=2))
# Persist the full server response for the report.
open("runs/vllm_ext_6w/proofpack_response.json", "w").write(resp)
PY
```

Expected output:

```
{
  "ok": true,
  "deal_id": "deal_xxxxxxxxxxxx",
  "proof_hash": "...",
  "evidence_present": true,
  "evidence_hoverstamp_keys": ["runtime_capabilities", "runtime_model",
    "runtime_name", "runtime_native_reuse_meaningful",
    "runtime_per_request_summary"]
}
```

If `evidence_present` is `false`, the live server does not have the
Level 1 commit deployed — re-deploy Render from `main` and retry.

---

## 7 · Files to retrieve after the run

`scp`/`rsync` these back to your workstation:

```
runs/vllm_short_3w/summary.json
runs/vllm_ext_6w/summary.json
runs/vllm_ext_6w/proofpack_response.json
```

Plus, for repro:

```
.venv/pip-freeze.txt        # run: pip freeze > .venv/pip-freeze.txt
nvidia-smi.txt              # run: nvidia-smi > nvidia-smi.txt
```

---

## 8 · Operator checklist (one screen)

```
[ ]  nvidia-smi prints GPU and driver
[ ]  python3 --version is 3.10 or 3.11
[ ]  git clone + git checkout main
[ ]  git rev-parse HEAD == 83f57ee22e987029417002eb6643f301c9d86ea6
[ ]  python3 -m venv .venv && source .venv/bin/activate
[ ]  pip install "vllm>=0.6,<0.12" transformers
[ ]  python -c "import torch, vllm; assert torch.cuda.is_available()"
[ ]  export HF_TOKEN=... (if using gated model)
[ ]  export MODEL=meta-llama/Llama-3.1-8B-Instruct
[ ]  export AME_BASE=https://aigentsy-ame-runtime.onrender.com
[ ]  Phase 1: capability probe printed safe_reuse_enabled=true
[ ]  Phase 2: python -m hoverstack.runtime_bench --adapter vllm --model $MODEL --waves 3 --run-dir runs/vllm_short_3w
[ ]  Phase 2 summary: adapter=vllm, simulated=false, meaningful=true
[ ]  Phase 3: python -m hoverstack.runtime_bench --adapter vllm --model $MODEL --waves 6 --run-dir runs/vllm_ext_6w
[ ]  Phase 4: run the ProofPack attachment script above; evidence_present=true
[ ]  Retrieve runs/vllm_short_3w/summary.json
[ ]  Retrieve runs/vllm_ext_6w/summary.json
[ ]  Retrieve runs/vllm_ext_6w/proofpack_response.json
[ ]  pip freeze > .venv/pip-freeze.txt ; nvidia-smi > nvidia-smi.txt
[ ]  Tear down the GPU host to stop billing
```

---

## 9 · Remaining external dependencies

| Dep | Needed for | Blocker if absent |
|---|---|---|
| CUDA Linux host with NVIDIA GPU (≥16 GB VRAM) | Running vLLM at all | Hard stop — mission cannot proceed |
| `nvidia-smi` + CUDA 12.1+ driver | vLLM kernels load | Hard stop |
| `pip install vllm` successful | Real adapter | Hard stop |
| HuggingFace token with Llama-3.1 access | Preferred model | Soft — Qwen2.5-7B fallback works ungated |
| Outbound network to `aigentsy-ame-runtime.onrender.com` | Phase 4 ProofPack attachment | Soft — phases 1–3 run regardless |
| Render deploy of `main` (commit ≥ `012f864`) | ProofPack accepts `hoverstamp` key | Soft — already deployed as of this writing |

None of the above are in this machine's control. All are cleanly
decoupled from the repo.
