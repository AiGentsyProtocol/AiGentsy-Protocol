#!/usr/bin/env python3
"""
AiGentsy CLI — command-driven developer path.

Usage:
    aigentsy init                              # Register agent, save credentials
    aigentsy stamp "work"                      # Create a ProofPack
    aigentsy verify DEAL_ID                    # Verify a proof bundle
    aigentsy settle DEAL_ID                    # Settle a deal
    aigentsy status                            # Show agent status
    aigentsy demo                              # Run full proof→verify→export flow
    aigentsy create-agent NAME                 # Scaffold a settlement-native agent starter
                          [--template TEMPLATE]
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import httpx
except ImportError:
    print("Install httpx: pip install httpx")
    sys.exit(1)


# ────────────────────────────────────────────────────────────────────────
# create-agent: thin adapter on top of the Settlement-Native Agent Core
# ────────────────────────────────────────────────────────────────────────
#
# Templates ship inside this package (aigentsy/templates/<template-name>/)
# so `pip install aigentsy` carries them. The registry is open by design:
# adding a future `settlement-native-langgraph` template means dropping a
# new subdirectory into aigentsy/templates/ — no CLI rewrite needed.

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_DEFAULT_TEMPLATE = "settlement-native-mcp"
_TEMPLATE_PLACEHOLDER = "{{PROJECT_NAME}}"


def _available_templates() -> List[str]:
    """List available scaffold templates. Directory names use underscores
    internally (settlement_native_mcp) but are surfaced to users with
    hyphens (settlement-native-mcp), matching `--template` convention."""
    if not _TEMPLATES_DIR.is_dir():
        return []
    return sorted(
        d.name.replace("_", "-")
        for d in _TEMPLATES_DIR.iterdir()
        if d.is_dir() and not d.name.startswith("_")
    )


def _resolve_template_dir(template_name: str) -> Optional[Path]:
    """Map a user-facing template name (hyphens) to its on-disk directory
    (underscores). Returns None if not found."""
    on_disk = _TEMPLATES_DIR / template_name.replace("-", "_")
    return on_disk if on_disk.is_dir() else None


def _validate_target_name(name: str) -> Tuple[bool, str]:
    """Reject unsafe project names. Returns (ok, error_message)."""
    if not name or not name.strip():
        return False, "project name is required"
    if name != name.strip():
        return False, "project name must not have leading or trailing whitespace"
    if os.path.isabs(name):
        return False, "project name must not be an absolute path"
    if ".." in name.split(os.sep):
        return False, "project name must not contain '..' (path traversal)"
    if "/" in name or "\\" in name:
        return False, "project name must not contain path separators"
    if name.startswith("."):
        return False, "project name must not start with '.'"
    # Restrict to a portable, shell-friendly character set: alphanumerics
    # plus underscore, hyphen, and dot. Reject spaces and shell-specials so
    # the printed `cd <name>` next-step is unambiguous.
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", name):
        return False, (
            "project name must start with a letter or digit and contain only "
            "letters, digits, '.', '_', or '-'"
        )
    # Refuse to overwrite an existing non-empty directory.
    target = Path(name)
    if target.exists() and target.is_dir() and any(target.iterdir()):
        return False, f"target directory {name!r} already exists and is not empty"
    if target.exists() and not target.is_dir():
        return False, f"target {name!r} exists and is not a directory"
    return True, ""


def _emit_file(src: Path, dst: Path, project_name: str) -> Path:
    """Copy one template file to its target. Files ending in `.template`
    get `{{PROJECT_NAME}}` substituted and the `.template` suffix stripped;
    everything else is copied byte-for-byte. Returns the final dst path."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix == ".template":
        body = src.read_text(encoding="utf-8")
        body = body.replace(_TEMPLATE_PLACEHOLDER, project_name)
        final_dst = dst.with_name(dst.name[: -len(".template")])
        final_dst.write_text(body, encoding="utf-8")
        return final_dst
    dst.write_bytes(src.read_bytes())
    return dst


def _scaffold(template_dir: Path, target: Path, project_name: str) -> List[str]:
    """Walk the template tree and emit files into target. Returns the list
    of created file paths (relative to target)."""
    created: List[str] = []
    for src in sorted(template_dir.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(template_dir)
        dst = target / rel
        final_dst = _emit_file(src, dst, project_name)
        created.append(str(final_dst.relative_to(target)))
    return sorted(created)


def cmd_create_agent(args):
    """Scaffold a settlement-native agent starter project.

    Generates a minimal starter — no network, no credentials, no real
    ProofPacks, no outreach. The starter is a local demo of the canonical
    settlement lifecycle (proof → verify → accept → settle/export) plus
    the AiGentsy MCP tool names that apply at each stage.
    """
    ok, err = _validate_target_name(args.name)
    if not ok:
        print(f"error: {err}", file=sys.stderr)
        sys.exit(2)

    template_dir = _resolve_template_dir(args.template)
    if template_dir is None:
        avail = _available_templates()
        print(
            f"error: unknown template {args.template!r}. Available: {', '.join(avail) if avail else '(none)'}",
            file=sys.stderr,
        )
        sys.exit(2)

    target = Path(args.name)
    target.mkdir(parents=True, exist_ok=True)

    created = _scaffold(template_dir, target, args.name)

    print(f"Created settlement-native agent starter: {args.name}/")
    print(f"  template: {args.template}")
    print(f"  files:    {len(created)}")
    for f in created:
        print(f"    - {args.name}/{f}")
    print()
    print("Next steps:")
    print(f"  cd {args.name}")
    print("  python agent.py")
    print("  python -m pytest tests/test_settlement_lifecycle.py -v")
    print()
    print("Consent note: this starter has zero network calls and creates zero")
    print("real ProofPacks. Connect the AiGentsy MCP server to your host")
    print("(see https://aigentsy.com/mcp-setup) to exercise real settlement")
    print("primitives inside an authorized session.")

BASE = os.getenv("AME_BASE", "https://aigentsy-ame-runtime.onrender.com")
CRED_FILE = os.path.expanduser("~/.aigentsy_credentials.json")


def _load_creds():
    if os.path.exists(CRED_FILE):
        with open(CRED_FILE) as f:
            return json.load(f)
    return {}


def _save_creds(creds):
    with open(CRED_FILE, "w") as f:
        json.dump(creds, f, indent=2)
    os.chmod(CRED_FILE, 0o600)


def _client():
    creds = _load_creds()
    c = httpx.Client(base_url=BASE, timeout=30.0)
    return c, creds


def cmd_init(args):
    """Register a new agent and save credentials locally."""
    c, _ = _client()
    name = args.name or input("Agent name: ").strip()
    r = c.post("/protocol/register", json={"name": name, "capabilities": ["general"]}).json()
    if not r.get("api_key"):
        print("Registration failed:", json.dumps(r, indent=2))
        return
    creds = {"agent_id": r["agent_id"], "api_key": r["api_key"], "base": BASE}
    _save_creds(creds)
    print(f"Agent registered: {r['agent_id']}")
    print(f"API key saved to {CRED_FILE}")
    print(f"OCS: {r.get('ocs', 0)} | Tier: {r.get('tier', 'restricted')}")


def cmd_stamp(args):
    """Create a ProofPack."""
    c, creds = _client()
    if not creds.get("api_key"):
        print("Run 'aigentsy init' first.")
        return
    desc = args.description or input("Deliverable description: ").strip()
    r = c.post("/protocol/stamp", json={
        "agent_id": creds["agent_id"], "description": desc,
    }).json()
    if r.get("ok"):
        print(f"ProofPack created: {r['deal_id']}")
        print(f"Proof URL: {r.get('proof_url', '')}")
        print(f"Verify URL: {r.get('verify_url', '')}")
    else:
        print("Failed:", json.dumps(r, indent=2))


def cmd_verify(args):
    """Verify a proof bundle."""
    c, _ = _client()
    r = c.get(f"/proof/{args.deal_id}/verify").json()
    if r.get("verified"):
        print(f"VERIFIED — chain integrity: {r.get('chain_integrity')}, events: {r.get('event_count')}")
    else:
        print(f"NOT VERIFIED — errors: {r.get('errors', [])}")


def cmd_settle(args):
    """Settle a deal."""
    c, creds = _client()
    if not creds.get("api_key"):
        print("Run 'aigentsy init' first.")
        return
    r = c.post("/protocol/settle", json={
        "deal_id": args.deal_id, "amount_usd": args.amount,
        "to_agent": creds["agent_id"], "provider": "balance",
    }, headers={"X-API-Key": creds["api_key"]}).json()
    print(json.dumps(r, indent=2))


def cmd_status(args):
    """Show current agent status."""
    creds = _load_creds()
    if not creds.get("agent_id"):
        print("No agent registered. Run 'aigentsy init'.")
        return
    c, _ = _client()
    r = c.get(f"/protocol/reputation/{creds['agent_id']}").json()
    print(f"Agent: {creds['agent_id']}")
    print(f"Base: {creds.get('base', BASE)}")
    print(f"OCS: {r.get('ocs', '?')} | Tier: {r.get('tier', '?')}")


def cmd_demo(args):
    """Run full proof→verify→export demo."""
    c, creds = _client()
    if not creds.get("api_key"):
        print("Registering new agent...")
        r = c.post("/protocol/register", json={"name": "cli_demo", "capabilities": ["demo"]}).json()
        creds = {"agent_id": r["agent_id"], "api_key": r["api_key"], "base": BASE}
        _save_creds(creds)
        print(f"  Agent: {r['agent_id']}")

    print("\n1. Creating ProofPack...")
    p = c.post("/protocol/proof-pack", json={
        "agent_username": creds["agent_id"], "vertical": "marketing",
        "proof_type": "creative_preview", "scope_summary": "CLI demo proof",
        "proof_data": {"preview_url": "https://example.com/demo.jpg", "asset_type": "graphic",
                       "timestamp": "2026-01-01T00:00:00Z"},
    }).json()
    if not p.get("ok"):
        print("  Failed:", p)
        return
    print(f"  Deal: {p['deal_id']}")

    print("\n2. Verifying...")
    v = c.get(f"/proof/{p['deal_id']}/verify").json()
    print(f"  Verified: {v.get('verified')} | Chain: {v.get('chain_integrity')} | Events: {v.get('event_count')}")

    print("\n3. Exporting bundle...")
    b = c.get(f"/proof/{p['deal_id']}").json()
    print(f"  Proofs: {b.get('proof_count')} | Events: {b.get('event_count')}")

    print(f"\nDone. View: {BASE}/proof/{p['deal_id']}")


def main():
    from aigentsy import __version__
    parser = argparse.ArgumentParser(prog="aigentsy", description="AiGentsy CLI")
    parser.add_argument("-V", "--version", action="version", version=f"aigentsy {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Register agent")
    p_init.add_argument("--name", default="")

    p_stamp = sub.add_parser("stamp", help="Create ProofPack")
    p_stamp.add_argument("description", nargs="?", default="")

    p_verify = sub.add_parser("verify", help="Verify proof")
    p_verify.add_argument("deal_id")

    p_settle = sub.add_parser("settle", help="Settle deal")
    p_settle.add_argument("deal_id")
    p_settle.add_argument("--amount", type=float, default=0)

    p_status = sub.add_parser("status", help="Agent status")
    sub.add_parser("demo", help="Full demo flow")

    p_create = sub.add_parser(
        "create-agent",
        help="Scaffold a settlement-native agent starter project",
    )
    p_create.add_argument(
        "name",
        help="Target directory name for the generated starter (no path separators)",
    )
    p_create.add_argument(
        "--template",
        default=_DEFAULT_TEMPLATE,
        help=f"Starter template to use (default: {_DEFAULT_TEMPLATE})",
    )

    # Pass 65 — adapter contract developer UX
    p_adapter = sub.add_parser(
        "adapter",
        help="AdapterContract author / lint tools",
    )
    p_adapter_sub = p_adapter.add_subparsers(
        dest="adapter_cmd", required=False,
    )

    p_lint = p_adapter_sub.add_parser(
        "lint",
        help="Validate an adapter_contract.json declaration locally",
    )
    p_lint.add_argument(
        "path",
        help="Path to the adapter contract JSON file",
    )

    p_scaff = p_adapter_sub.add_parser(
        "scaffold",
        help="Generate a stub adapter_contract.json a developer can edit",
    )
    p_scaff.add_argument(
        "--id", dest="adapter_id", required=True,
        help="Reverse-DNS adapter_id (e.g. acme.eval_suite.v0)",
    )
    p_scaff.add_argument(
        "--version", dest="adapter_version", default="0.1.0",
        help="Semver of this adapter (default: 0.1.0)",
    )
    p_scaff.add_argument(
        "--validator", dest="validator", default="boolean",
        choices=["boolean"],
        help="Validator family (only 'boolean' supported in v0)",
    )
    p_scaff.add_argument(
        "--out", dest="out", default=".",
        help="Output directory (default: current dir)",
    )
    p_scaff.add_argument(
        "--fields", dest="fields",
        default="signal_a,signal_b,signal_c",
        help="Comma-separated output field names (snake_case)",
    )

    # Pass 67 — adapter lifecycle commands. All four operate on local files
    # or a fetched manifest; none ever influences replay.
    p_list = p_adapter_sub.add_parser(
        "list",
        help="List AdapterContracts from a manifest (default: aigentsy.com)",
    )
    p_list.add_argument(
        "--from", dest="manifest_url",
        default="https://aigentsy.com/specs/adapter-contracts.manifest.json",
        help="Manifest URL (default: aigentsy.com canonical manifest)",
    )
    p_list.add_argument(
        "--manifest", dest="manifest_path", default=None,
        help="Local manifest path (overrides --from)",
    )

    p_pin = p_adapter_sub.add_parser(
        "pin",
        help="Pin (id, version, hash) into ./pinned_adapters.json",
    )
    p_pin.add_argument("--id", dest="adapter_id", required=True)
    p_pin.add_argument("--version", dest="adapter_version", required=True)
    p_pin.add_argument("--hash", dest="contract_hash", required=True,
                       help="64-char sha256 hex of the contract")
    p_pin.add_argument("--out", dest="out", default="pinned_adapters.json")
    p_pin.add_argument(
        "--manifest", dest="manifest_path", default=None,
        help="Optional manifest path or URL. When supplied, pin also "
             "records entry_hash + publisher_id from the matching entry. "
             "If absent or unsignable, the pin is still written but with "
             "explicit entry_hash_status='no_manifest_supplied' so a "
             "reviewer sees that publisher trust was NOT verified.",
    )
    p_pin.add_argument(
        "--public-key-base64", dest="public_key_base64", default=None,
        help="Optional Ed25519 public key to verify the manifest entry "
             "signature offline. Without it, the entry_signature_status "
             "in the pin is 'no_public_key' (NOT silent trust).",
    )
    p_pin.add_argument(
        "--allow-revoked-for-legacy-inspection",
        dest="allow_revoked", action="store_true",
        help=("Print the pin metadata for a REVOKED manifest entry so a "
              "reviewer can inspect it for legacy / forensic purposes. "
              "Pin file records status=revoked + advice; it is NOT a "
              "recommendation to adopt the revoked contract for new work."),
    )

    p_bump = p_adapter_sub.add_parser(
        "bump",
        help="Bump a declaration's adapter_version + recompute hashes in place",
    )
    p_bump.add_argument("path", help="Path to the adapter contract JSON file")
    p_bump.add_argument("--version", dest="adapter_version", required=True,
                        help="New semver for adapter_version")

    p_diff = p_adapter_sub.add_parser(
        "diff",
        help="Show a structural diff between two adapter contract files",
    )
    p_diff.add_argument("old", help="Path to the prior declaration")
    p_diff.add_argument("new", help="Path to the proposed declaration")

    # Pass 68 — publication attestation. These commands operate over the
    # public manifest layer; they do NOT affect bundle replay.
    p_attest = p_adapter_sub.add_parser(
        "attest",
        help="Emit a manifest entry (entry_hash + unsigned/optionally-signed)",
    )
    p_attest.add_argument(
        "path", help="Path to the adapter contract declaration JSON",
    )
    p_attest.add_argument(
        "--status", dest="status", default="active",
        choices=["active", "deprecated", "revoked"],
    )
    p_attest.add_argument(
        "--channel", dest="distribution_channel", default="developer.local",
        choices=["aigentsy.builtin", "aigentsy.examples",
                 "developer.local", "third_party"],
    )
    p_attest.add_argument(
        "--publisher-id", dest="publisher_id", default="aigentsy.publisher.v1",
    )
    p_attest.add_argument(
        "--publisher-key-id", dest="publisher_key_id",
        default="aigentsy_log_signer_v1",
    )
    p_attest.add_argument(
        "--docs-url", dest="docs_url",
        default="https://aigentsy.com/docs/adapter-contracts",
    )
    p_attest.add_argument(
        "--declaration-url", dest="declaration_url", default="",
    )
    p_attest.add_argument(
        "--release-notes", dest="release_notes", default="",
    )
    p_attest.add_argument(
        "--supersedes", dest="supersedes", default="",
    )
    p_attest.add_argument(
        "--replaced-by", dest="replaced_by", default="",
    )

    p_mfst = p_adapter_sub.add_parser(
        "manifest",
        help="Manifest publication helpers (currently: verify)",
    )
    p_mfst_sub = p_mfst.add_subparsers(dest="manifest_cmd", required=False)
    p_mfst_verify = p_mfst_sub.add_parser(
        "verify",
        help="Verify a manifest file or URL offline (entry hashes, "
             "signatures, manifest hash, duplicate keys)",
    )
    p_mfst_verify.add_argument(
        "target",
        help="Manifest path OR https:// URL",
    )
    p_mfst_verify.add_argument(
        "--public-key-base64", dest="public_key_base64", default=None,
        help="Optional Ed25519 public key (base64). If absent, the "
             "verifier reports signature_status=no_public_key for clarity "
             "(does NOT silently trust unverified entries).",
    )
    p_mfst_verify.add_argument(
        "--from-publisher-document",
        dest="publisher_document_url",
        default="https://aigentsy.com/.well-known/aigentsy-publisher.json",
        help=("Optional URL of a publisher document with public_key + "
              "publisher_key_id. Used only when --public-key-base64 not "
              "supplied AND --fetch-publisher is set."),
    )
    p_mfst_verify.add_argument(
        "--fetch-publisher", dest="fetch_publisher", action="store_true",
        help="Allow one HTTPS GET of the publisher document to obtain the "
             "verification key. Off by default — the verifier prefers a "
             "locally-supplied --public-key-base64.",
    )

    # ── Pass 78I — Admin CLI family ──────────────────────────────────
    #
    # Wraps the admin-protected production endpoint added in Pass 78G:
    #   POST /vault/owner-bound
    # Reads OPS_ADMIN_KEY from env. Never accepts the token as a CLI
    # arg. Never prints the token in any code path. CLI does pre-flight
    # client-side validation that mirrors server constraints; server
    # remains authoritative.

    p_admin = sub.add_parser(
        "admin",
        help="Admin-protected operations (require OPS_ADMIN_KEY)",
    )
    p_admin_sub = p_admin.add_subparsers(
        dest="admin_cmd", required=False,
    )

    p_obind = p_admin_sub.add_parser(
        "owner-bound",
        help="Create a platform-attested Vault owner binding (admin only)",
    )
    p_obind.add_argument(
        "--deal-id", dest="deal_id", required=True,
        help="Deal id to bind (1..200 chars)",
    )
    p_obind.add_argument(
        "--agent-id", dest="agent_id", required=True,
        help="Agent id to bind (1..200 chars)",
    )
    p_obind.add_argument(
        "--scope-type", dest="scope_type", required=True,
        choices=["agent", "account", "workspace", "enterprise"],
        help="Owner scope type for this binding",
    )
    p_obind.add_argument(
        "--enterprise-id", dest="enterprise_id", default=None,
        help="Enterprise id (required when --scope-type is non-agent unless "
             "another identity field is supplied)",
    )
    p_obind.add_argument(
        "--workspace-id", dest="workspace_id", default=None,
        help="Workspace id (optional)",
    )
    p_obind.add_argument(
        "--account-id", dest="account_id", default=None,
        help="Account id (optional)",
    )
    p_obind.add_argument(
        "--user-id", dest="user_id", default=None,
        help="User id (optional)",
    )
    p_obind.add_argument(
        "--reason", dest="reason", default=None,
        help="Reason for the binding (≤500 chars, optional)",
    )

    # ── Pass 79C Stage 2 — admin account subcommand family ─────────────
    # Mirrors `aigentsy admin owner-bound` security model: OPS_ADMIN_KEY
    # env-only, never accepted as --admin-token, never echoed.
    p_account = p_admin_sub.add_parser(
        "account",
        help="Manage Account Registry rows (admin only, 79A/79C)",
    )
    p_account_sub = p_account.add_subparsers(
        dest="account_cmd", required=False,
    )

    # create
    p_account_create = p_account_sub.add_parser(
        "create",
        help="Create or upsert an AccountRegistry row",
    )
    p_account_create.add_argument(
        "--account-id", dest="account_id", required=True,
        help="Account id (1..200 chars, no control chars)",
    )
    p_account_create.add_argument(
        "--account-type", dest="account_type", required=True,
        choices=["developer", "enterprise", "internal", "demo"],
        help="Account type",
    )
    p_account_create.add_argument(
        "--owner-agent-id", dest="owner_agent_id", required=True,
        help="Owner agent id (drives Principal resolution)",
    )
    p_account_create.add_argument(
        "--account-name", dest="account_name", default=None,
        help="Display name (optional, ≤200 chars)",
    )
    p_account_create.add_argument(
        "--enterprise-id", dest="enterprise_id", default=None,
        help="Enterprise id (optional)",
    )
    p_account_create.add_argument(
        "--workspace-id", dest="workspace_id", default=None,
        help="Workspace id (optional)",
    )
    p_account_create.add_argument(
        "--owner-email", dest="owner_email", default=None,
        help="Owner email label (NOT verified, label-only)",
    )
    p_account_create.add_argument(
        "--status", dest="status", default="active",
        choices=["active", "suspended", "disabled"],
        help="Account status (default: active)",
    )
    p_account_create.add_argument(
        "--base-url", dest="base_url", default=None,
        help="Override runtime base URL (default uses AME_BASE)",
    )

    # list
    p_account_list = p_account_sub.add_parser(
        "list",
        help="List AccountRegistry rows with optional filters",
    )
    p_account_list.add_argument(
        "--account-id", dest="account_id", default=None,
        help="Filter by exact account id",
    )
    p_account_list.add_argument(
        "--enterprise-id", dest="enterprise_id", default=None,
        help="Filter by enterprise id",
    )
    p_account_list.add_argument(
        "--owner-agent-id", dest="owner_agent_id", default=None,
        help="Filter by owner agent id",
    )
    p_account_list.add_argument(
        "--status", dest="status", default=None,
        choices=["active", "suspended", "disabled"],
        help="Filter by status",
    )
    p_account_list.add_argument(
        "--base-url", dest="base_url", default=None,
        help="Override runtime base URL",
    )

    # get
    p_account_get = p_account_sub.add_parser(
        "get",
        help="Fetch one AccountRegistry row by account id",
    )
    p_account_get.add_argument(
        "--account-id", dest="account_id", required=True,
        help="Account id to fetch",
    )
    p_account_get.add_argument(
        "--base-url", dest="base_url", default=None,
        help="Override runtime base URL",
    )

    # suspend
    p_account_suspend = p_account_sub.add_parser(
        "suspend",
        help="Set an account status to 'suspended'",
    )
    p_account_suspend.add_argument(
        "--account-id", dest="account_id", required=True,
        help="Account id to suspend",
    )
    p_account_suspend.add_argument(
        "--base-url", dest="base_url", default=None,
        help="Override runtime base URL",
    )

    # disable
    p_account_disable = p_account_sub.add_parser(
        "disable",
        help="Set an account status to 'disabled'",
    )
    p_account_disable.add_argument(
        "--account-id", dest="account_id", required=True,
        help="Account id to disable",
    )
    p_account_disable.add_argument(
        "--base-url", dest="base_url", default=None,
        help="Override runtime base URL",
    )

    # activate (the inverse — restore from suspended/disabled)
    p_account_activate = p_account_sub.add_parser(
        "activate",
        help="Set an account status to 'active' (restore)",
    )
    p_account_activate.add_argument(
        "--account-id", dest="account_id", required=True,
        help="Account id to activate",
    )
    p_account_activate.add_argument(
        "--base-url", dest="base_url", default=None,
        help="Override runtime base URL",
    )

    # ── Pass 79F Stage 2 — admin account membership subcommand family ──
    # Wraps the three runtime endpoints added in 79F Stage 1:
    #   POST /admin/accounts/{account_id}/memberships
    #   GET  /admin/accounts/{account_id}/memberships
    #   POST /admin/accounts/{account_id}/memberships/{membership_id}/status
    p_membership = p_account_sub.add_parser(
        "membership",
        help="Manage AccountMembership rows (admin only, 79F)",
    )
    p_membership_sub = p_membership.add_subparsers(
        dest="membership_cmd", required=False,
    )

    # add
    p_mb_add = p_membership_sub.add_parser(
        "add",
        help="Create or upsert a membership row",
    )
    p_mb_add.add_argument(
        "--account-id", dest="account_id", required=True,
        help="Parent account id",
    )
    p_mb_add.add_argument(
        "--agent-id", dest="agent_id", required=True,
        help="Agent id to grant the role to",
    )
    p_mb_add.add_argument(
        "--role", dest="role", required=True,
        choices=["owner", "admin", "operator", "auditor", "viewer"],
        help="Role to grant for this (account_id, agent_id) pair",
    )
    p_mb_add.add_argument(
        "--enterprise-id", dest="enterprise_id", default=None,
        help="Enterprise id (server denormalizes from parent account)",
    )
    p_mb_add.add_argument(
        "--workspace-id", dest="workspace_id", default=None,
        help="Workspace id (optional)",
    )
    p_mb_add.add_argument(
        "--status", dest="status", default="active",
        choices=["active", "suspended", "disabled"],
        help="Membership status (default: active)",
    )
    p_mb_add.add_argument(
        "--base-url", dest="base_url", default=None,
        help="Override runtime base URL",
    )

    # list
    p_mb_list = p_membership_sub.add_parser(
        "list",
        help="List memberships under an account",
    )
    p_mb_list.add_argument(
        "--account-id", dest="account_id", required=True,
        help="Parent account id",
    )
    p_mb_list.add_argument(
        "--status", dest="status", default=None,
        choices=["active", "suspended", "disabled"],
        help="Filter by status",
    )
    p_mb_list.add_argument(
        "--base-url", dest="base_url", default=None,
        help="Override runtime base URL",
    )

    # status
    p_mb_status = p_membership_sub.add_parser(
        "status",
        help="Change a membership's status (status-only update)",
    )
    p_mb_status.add_argument(
        "--account-id", dest="account_id", required=True,
        help="Parent account id",
    )
    p_mb_status.add_argument(
        "--membership-id", dest="membership_id", required=True,
        help="Membership id to update",
    )
    p_mb_status.add_argument(
        "--status", dest="status", required=True,
        choices=["active", "suspended", "disabled"],
        help="New membership status",
    )
    p_mb_status.add_argument(
        "--base-url", dest="base_url", default=None,
        help="Override runtime base URL",
    )

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    {"init": cmd_init, "stamp": cmd_stamp, "verify": cmd_verify,
     "settle": cmd_settle, "status": cmd_status, "demo": cmd_demo,
     "create-agent": cmd_create_agent,
     "adapter": cmd_adapter,
     "admin": cmd_admin}[args.command](args)


# ── Pass 65 — AdapterContract developer UX ───────────────────────────


# Snake-case alphanumeric_ identifiers.
_FIELD_RE = __import__("re").compile(r"^[a-z][a-z0-9_]*$")
_ADAPTER_ID_RE = __import__("re").compile(
    r"^[a-z][a-z0-9_]*(\.[a-z0-9_][a-z0-9_]*)+$"
)
_SEMVER_RE = __import__("re").compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_SHA_RE = __import__("re").compile(r"^[a-f0-9]{64}$")


def _canonical_hash_cli(obj):
    """sha256 over canonical-JSON. Mirrors protocol/adapter_contract.py's
    _canonical_hash so a CLI without runtime access can recompute hashes
    identically."""
    import hashlib, json
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                           default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _recompute_contract_hash(decl):
    return _canonical_hash_cli({
        "adapter_contract_version": decl.get("adapter_contract_version", "1.0.0"),
        "adapter_id": decl.get("adapter_id", ""),
        "adapter_version": decl.get("adapter_version", ""),
        "input_schema_version": decl.get("input_schema_version", ""),
        "output_fields": sorted(decl.get("output_fields") or []),
        "allowed_policy_fields": sorted(decl.get("allowed_policy_fields") or []),
        "validator_name": decl.get("validator_name", ""),
        "validator_version": decl.get("validator_version", ""),
    })


def _recompute_input_schema_hash(decl):
    return _canonical_hash_cli({
        "input_schema_version": decl.get("input_schema_version", ""),
        "output_fields": sorted(decl.get("output_fields") or []),
        "validator_name": decl.get("validator_name", ""),
        "validator_version": decl.get("validator_version", ""),
    })


def _lint_declaration(decl):
    """Return (errors, warnings) for a parsed declaration dict. The lint
    rules mirror protocol/adapter_contract._validate_contract_declaration
    so the CLI agrees with the runtime on what's accepted."""
    errors = []
    warnings = []
    if not isinstance(decl, dict):
        return ["declaration is not a JSON object"], []

    required = (
        "adapter_contract_version", "adapter_id", "adapter_version",
        "input_schema_version", "input_schema_hash",
        "output_fields", "allowed_policy_fields",
        "validator_name", "validator_version", "contract_hash",
    )
    missing = [k for k in required if k not in decl]
    if missing:
        return [f"missing required field: {k}" for k in missing], []

    for vfield in ("adapter_contract_version", "adapter_version",
                   "input_schema_version", "validator_version"):
        if not isinstance(decl[vfield], str) or not _SEMVER_RE.match(decl[vfield]):
            errors.append(f"{vfield} is not semver MAJOR.MINOR.PATCH")

    if not _ADAPTER_ID_RE.match(str(decl.get("adapter_id", ""))):
        errors.append(
            "adapter_id must be reverse-DNS style (e.g. org.team.adapter)"
        )

    for arrkey in ("output_fields", "allowed_policy_fields"):
        arr = decl.get(arrkey)
        if not isinstance(arr, list):
            errors.append(f"{arrkey} is not an array")
            continue
        if arrkey == "output_fields" and len(arr) == 0:
            errors.append("output_fields must have at least one entry")
        if len(arr) != len(set(arr)):
            errors.append(f"{arrkey} has duplicate entries")
        for item in arr:
            if not isinstance(item, str) or not _FIELD_RE.match(item):
                errors.append(f"{arrkey} entry {item!r} is not snake_case")

    if not isinstance(decl.get("validator_name", ""), str) or \
            not _FIELD_RE.match(str(decl.get("validator_name", ""))):
        errors.append("validator_name must be snake_case")

    for hkey in ("input_schema_hash", "contract_hash"):
        h = decl.get(hkey, "")
        if not isinstance(h, str) or not _SHA_RE.match(h):
            errors.append(
                f"{hkey} is not a sha256 hex digest (64 lowercase hex chars)"
            )

    of = set(decl.get("output_fields") or [])
    apf = set(decl.get("allowed_policy_fields") or [])
    leaked = apf - of
    if leaked:
        errors.append(
            f"allowed_policy_fields not in output_fields: {sorted(leaked)}"
        )

    if not errors:
        ish = _recompute_input_schema_hash(decl)
        if ish != decl.get("input_schema_hash"):
            errors.append(
                f"input_schema_hash mismatch: declared "
                f"{decl.get('input_schema_hash')!r}, recomputed {ish!r}"
            )
        ch = _recompute_contract_hash(decl)
        if ch != decl.get("contract_hash"):
            errors.append(
                f"contract_hash mismatch: declared "
                f"{decl.get('contract_hash')!r}, recomputed {ch!r}"
            )

    # Validator-name advisory: 'boolean' family is the only known v0
    # validator. Anything else is fine for the lint check (the runtime
    # registers it but evaluate_adapter will fail-closed at evaluation
    # time if the validator isn't installed in this runtime).
    KNOWN_VALIDATORS = {"starter_boolean_validator"}
    if decl.get("validator_name") not in KNOWN_VALIDATORS:
        warnings.append(
            f"validator_name {decl.get('validator_name')!r} is not in the "
            f"locally-known set {sorted(KNOWN_VALIDATORS)}; the runtime "
            "will register the contract but evaluate_adapter will fail "
            "closed (route to require_review) unless the validator is "
            "registered server-side."
        )

    # Pass 67 — lifecycle metadata. OPTIONAL; never enters hash. Lint
    # validates type/pattern only when fields are present.
    pin_re = __import__("re").compile(
        r"^[a-z][a-z0-9_]*(\.[a-z0-9_][a-z0-9_]*)+@[0-9]+\.[0-9]+\.[0-9]+$"
    )
    if "status" in decl and decl["status"] not in ("active", "deprecated", "revoked"):
        errors.append(
            f"status must be one of ['active', 'deprecated', 'revoked']; "
            f"got {decl['status']!r}"
        )
    for ptr in ("supersedes", "replaced_by"):
        if ptr in decl:
            if not isinstance(decl[ptr], str) or not pin_re.match(decl[ptr]):
                errors.append(
                    f"{ptr} must be 'adapter_id@semver' "
                    f"(reverse-DNS id + @ + MAJOR.MINOR.PATCH)"
                )
    if "min_verifier_version" in decl:
        v = decl["min_verifier_version"]
        if not isinstance(v, str) or not _SEMVER_RE.match(v):
            errors.append("min_verifier_version is not semver MAJOR.MINOR.PATCH")
    if "published_at" in decl:
        if not isinstance(decl["published_at"], str) or len(decl["published_at"]) < 10:
            errors.append("published_at must be an ISO-8601 string")
    if "distribution_channel" in decl:
        if decl["distribution_channel"] not in (
            "aigentsy.builtin", "aigentsy.examples",
            "developer.local", "third_party",
        ):
            errors.append(
                "distribution_channel must be one of "
                "aigentsy.builtin | aigentsy.examples | "
                "developer.local | third_party"
            )

    # Pass 69A — surface lifecycle status as a lint WARNING so authors see
    # the adoption advisory without the lint failing. Lint failure is for
    # malformed declarations, not for legitimate-but-deprecated state.
    status = decl.get("status")
    if status == "deprecated":
        replacement = decl.get("replaced_by") or "(none declared)"
        warnings.append(
            f"status=deprecated — recommend migrating to {replacement} for new work; "
            "existing bundles remain replayable from their embedded declarations."
        )
    elif status == "revoked":
        replacement = decl.get("replaced_by") or "(none declared)"
        warnings.append(
            f"status=revoked — new adoption is blocked at evaluate_adapter "
            f"(routes to unknown_adapter). Replacement: {replacement}. "
            "Historical bundles remain replayable from their embedded declarations."
        )
    elif status == "active" and decl.get("replaced_by"):
        warnings.append(
            f"status=active but replaced_by={decl['replaced_by']} — this "
            "contract is superseded. Adoption is allowed; consider migrating."
        )

    return errors, warnings


def cmd_adapter(args):
    import sys
    if not getattr(args, "adapter_cmd", None):
        print("usage: aigentsy adapter "
              "{lint,scaffold,list,pin,bump,diff,attest,manifest} [...]")
        sys.exit(2)
    if args.adapter_cmd == "lint":
        return _cmd_adapter_lint(args)
    if args.adapter_cmd == "scaffold":
        return _cmd_adapter_scaffold(args)
    if args.adapter_cmd == "list":
        return _cmd_adapter_list(args)
    if args.adapter_cmd == "pin":
        return _cmd_adapter_pin(args)
    if args.adapter_cmd == "bump":
        return _cmd_adapter_bump(args)
    if args.adapter_cmd == "diff":
        return _cmd_adapter_diff(args)
    if args.adapter_cmd == "attest":
        return _cmd_adapter_attest(args)
    if args.adapter_cmd == "manifest":
        return _cmd_adapter_manifest(args)
    print(f"unknown adapter subcommand: {args.adapter_cmd}")
    sys.exit(2)


def _cmd_adapter_lint(args):
    import json, sys
    p = Path(args.path)
    if not p.is_file():
        print(json.dumps({
            "ok": False,
            "errors": [f"file_not_found: {args.path}"],
            "warnings": [],
        }, indent=2))
        sys.exit(1)
    try:
        decl = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "errors": [f"json_parse_failed: {type(e).__name__}: {e}"],
            "warnings": [],
        }, indent=2))
        sys.exit(1)
    # Strip _-prefixed metadata keys (comments) before lint.
    decl_for_lint = {k: v for k, v in decl.items() if not str(k).startswith("_")}
    errors, warnings = _lint_declaration(decl_for_lint)
    result = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "adapter_id": decl_for_lint.get("adapter_id", ""),
        "contract_hash": decl_for_lint.get("contract_hash", ""),
        "input_schema_hash": decl_for_lint.get("input_schema_hash", ""),
    }
    print(json.dumps(result, indent=2))
    sys.exit(0 if not errors else 1)


def _cmd_adapter_scaffold(args):
    import json, sys
    target_dir = Path(args.out).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / "adapter_contract.json"

    # Validate inputs first (CLI surface — be helpful, not silent)
    if not _ADAPTER_ID_RE.match(args.adapter_id):
        print(f"error: --id must be reverse-DNS style "
              f"(got {args.adapter_id!r})")
        sys.exit(2)
    if not _SEMVER_RE.match(args.adapter_version):
        print(f"error: --version must be semver "
              f"(got {args.adapter_version!r})")
        sys.exit(2)

    fields = [f.strip() for f in str(args.fields).split(",") if f.strip()]
    for f in fields:
        if not _FIELD_RE.match(f):
            print(f"error: field name {f!r} is not snake_case")
            sys.exit(2)
    if not fields:
        fields = ["signal_a", "signal_b", "signal_c"]

    # Validator family → name. v0 supports only the boolean family.
    validator_name = "starter_boolean_validator"
    validator_version = "1.0.0"

    decl_skeleton = {
        "adapter_contract_version": "1.0.0",
        "adapter_id": args.adapter_id,
        "adapter_version": args.adapter_version,
        "input_schema_version": "1.0.0",
        "output_fields": fields,
        "allowed_policy_fields": fields,
        "validator_name": validator_name,
        "validator_version": validator_version,
    }
    decl_skeleton["input_schema_hash"] = _recompute_input_schema_hash(decl_skeleton)
    decl_skeleton["contract_hash"] = _recompute_contract_hash(decl_skeleton)

    decl_out = {
        "_comment": (
            "Stub AdapterContract scaffolded by `aigentsy adapter scaffold`. "
            "Edit output_fields and allowed_policy_fields to match the "
            "signals your adapter actually emits. Then re-lint with "
            "`aigentsy adapter lint adapter_contract.json` (which will "
            "complain until the hashes match the declaration — recompute "
            "them with the same command after editing)."
        ),
        "_layer_boundary": (
            "AdapterContract types, validates, versions, and allow-lists "
            "adapter-produced signals. AcceptancePolicy is where the "
            "user/counterparty defines whether those validated signals "
            "add up to acceptable work. AiGentsy enforces the user's "
            "policy deterministically against type-validated inputs; it "
            "does not decide what counts as good work."
        ),
        **decl_skeleton,
    }
    out_path.write_text(json.dumps(decl_out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "adapter_id": args.adapter_id,
        "out": str(out_path),
        "contract_hash": decl_skeleton["contract_hash"],
        "input_schema_hash": decl_skeleton["input_schema_hash"],
        "next": [
            f"aigentsy adapter lint {out_path}",
            "edit output_fields / allowed_policy_fields to match your adapter",
            "drop the file into AIGENTSY_ADAPTER_CONTRACTS_DIR on the runtime "
            "(default: data/adapter_contracts/) to register",
        ],
    }, indent=2))


def _cmd_adapter_list(args):
    """Read a manifest (local file or HTTPS URL) and print one row per
    contract. The manifest is a DISCOVERY surface — this command is
    convenience tooling for developers; aigentsy-verify does not consult
    a manifest at replay time."""
    import json, sys
    if getattr(args, "manifest_path", None):
        p = Path(args.manifest_path)
        if not p.is_file():
            print(f"error: manifest not found at {args.manifest_path}",
                  file=sys.stderr)
            sys.exit(2)
        try:
            manifest = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"error: failed to parse manifest: {e}", file=sys.stderr)
            sys.exit(2)
    else:
        try:
            r = httpx.get(args.manifest_url, timeout=10.0,
                          follow_redirects=True)
            r.raise_for_status()
            manifest = r.json()
        except Exception as e:
            print(f"error: failed to fetch manifest from "
                  f"{args.manifest_url}: {e}", file=sys.stderr)
            sys.exit(2)
    contracts = manifest.get("contracts") or []
    print(f"manifest_version: {manifest.get('manifest_version', '?')}")
    print(f"generated_at:     {manifest.get('generated_at', '?')}")
    print(f"contracts:        {len(contracts)}")
    print()
    for c in contracts:
        status = c.get("status", "active")
        # Pass 69A — visual signal for lifecycle status
        marker = {
            "active":     "[active]    ",
            "deprecated": "[DEPRECATED]",
            "revoked":    "[REVOKED]   ",
        }.get(status, f"[{status}]")
        print(f"  {marker} {c.get('adapter_id')}@{c.get('adapter_version')}")
        print(f"    status:               {status}")
        print(f"    distribution_channel: {c.get('distribution_channel') or '-'}")
        if c.get("replaced_by"):
            print(f"    replaced_by:          {c['replaced_by']}")
        if c.get("supersedes"):
            print(f"    supersedes:           {c['supersedes']}")
        print(f"    contract_hash:        {c.get('contract_hash', '')[:16]}…")
        print(f"    input_schema_hash:    {c.get('input_schema_hash', '')[:16]}…")
        print(f"    declaration_url:      {c.get('declaration_url', '-')}")
        if status == "deprecated":
            print("    advice:               deprecated — replacement "
                  "encouraged for new work")
        elif status == "revoked":
            print("    advice:               revoked — new adoption "
                  "BLOCKED; replay of historical bundles unaffected")
        elif status == "active" and c.get("replaced_by"):
            print("    advice:               superseded — newer version "
                  "available; adoption still allowed")
        print()
    print("NOTE: This is a discovery surface. Old bundles replay from "
          "their own embedded declarations; aigentsy-verify does not "
          "consult this manifest at replay time.")


def _cmd_adapter_pin(args):
    """Append/update a pinned entry in ./pinned_adapters.json. The pin
    file is meant to be committed to a developer's project so reviewers
    can see exactly which (id, version, hash) the project depends on.

    Pass 68 extension: when --manifest is supplied, the pin also records
    entry_hash + publisher_id from the matching manifest entry. With
    --public-key-base64 (or by reading the publisher document), the pin
    also records the verified entry_signature_status. Pins NEVER silently
    treat unverified entries as trusted — the status field is recorded
    explicitly so a reviewer sees the trust posture at pin time."""
    import json, sys
    if not _ADAPTER_ID_RE.match(args.adapter_id):
        print(f"error: --id must be reverse-DNS style", file=sys.stderr)
        sys.exit(2)
    if not _SEMVER_RE.match(args.adapter_version):
        print(f"error: --version must be semver", file=sys.stderr)
        sys.exit(2)
    if not _SHA_RE.match(args.contract_hash):
        print(f"error: --hash must be 64 lowercase hex chars",
              file=sys.stderr)
        sys.exit(2)

    pin_entry = {
        "adapter_id": args.adapter_id,
        "adapter_version": args.adapter_version,
        "contract_hash": args.contract_hash,
    }

    # Optional manifest binding — Pass 68
    # Pass 69A — gate adoption on lifecycle status:
    #   active     → pin normally
    #   deprecated → pin + WARN loudly + show replacement
    #   superseded → pin + WARN + show replacement (status still active but
    #                replaced_by is set)
    #   revoked    → BLOCK by default; require
    #                --allow-revoked-for-legacy-inspection to record
    if getattr(args, "manifest_path", None):
        manifest = _load_manifest(args.manifest_path)
        match = _find_manifest_entry(
            manifest, args.adapter_id, args.adapter_version,
        )
        if match is None:
            pin_entry["entry_hash_status"] = "manifest_entry_not_found"
            pin_entry["publisher_id"] = None
        else:
            pin_entry["entry_hash"] = match.get("entry_hash", "")
            pin_entry["publisher_id"] = match.get("publisher_id", "")
            pin_entry["status"] = match.get("status", "active")
            if match.get("replaced_by"):
                pin_entry["replaced_by"] = match["replaced_by"]
            if match.get("supersedes"):
                pin_entry["supersedes"] = match["supersedes"]
            # Lifecycle gating — Pass 69A
            status = pin_entry["status"]
            if status == "revoked":
                if not getattr(args, "allow_revoked", False):
                    print(json.dumps({
                        "ok": False,
                        "error": "pin_blocked_revoked",
                        "adapter_id": args.adapter_id,
                        "adapter_version": args.adapter_version,
                        "status": "revoked",
                        "replaced_by": match.get("replaced_by"),
                        "advice": (
                            "Refusing to pin a REVOKED contract for new "
                            "work. Pinning to a revoked version cannot "
                            "produce auto_accept at evaluation time; "
                            "ProofPack creation routes revoked contracts "
                            "to unknown_adapter (fail-closed). If you are "
                            "inspecting this entry for legacy / forensic "
                            "purposes only, re-run with "
                            "--allow-revoked-for-legacy-inspection."
                        ),
                    }, indent=2), file=sys.stderr)
                    sys.exit(3)
                pin_entry["lifecycle_advice"] = (
                    "REVOKED — inspection-only pin. Do not adopt for new "
                    "work; new evaluations will route to unknown_adapter."
                )
                print(
                    f"WARNING: pinning REVOKED contract "
                    f"{args.adapter_id}@{args.adapter_version} as "
                    "inspection-only.", file=sys.stderr,
                )
            elif status == "deprecated":
                pin_entry["lifecycle_advice"] = (
                    "DEPRECATED — replacement available. New work should "
                    "migrate to the replacement when ready. Historical "
                    "bundles continue to verify from their embedded "
                    "declarations."
                )
                print(
                    f"WARNING: {args.adapter_id}@{args.adapter_version} "
                    f"is DEPRECATED. Replacement: "
                    f"{match.get('replaced_by') or '(none declared)'}",
                    file=sys.stderr,
                )
            elif status == "active" and match.get("replaced_by"):
                pin_entry["lifecycle_advice"] = (
                    "SUPERSEDED — a newer version is available. Adoption "
                    "is allowed but consider migrating."
                )
                print(
                    f"NOTICE: {args.adapter_id}@{args.adapter_version} is "
                    f"superseded by {match['replaced_by']}.",
                    file=sys.stderr,
                )
            # Verify entry_hash recomputes
            recomputed = _recompute_entry_hash(match)
            if match.get("entry_hash") == recomputed:
                pin_entry["entry_hash_status"] = "ok"
            elif "entry_hash" in match:
                pin_entry["entry_hash_status"] = "mismatch"
            else:
                pin_entry["entry_hash_status"] = "unsigned_manifest"
            # Verify entry_signature offline if a public key was provided
            if "entry_signature" in match:
                if not getattr(args, "public_key_base64", None):
                    pin_entry["entry_signature_status"] = "no_public_key"
                else:
                    ok = _verify_ed25519_signature_cli(
                        match.get("entry_hash", "").encode("utf-8"),
                        match["entry_signature"],
                        args.public_key_base64,
                    )
                    pin_entry["entry_signature_status"] = "ok" if ok else "bad"
            else:
                pin_entry["entry_signature_status"] = "absent"
    else:
        pin_entry["entry_hash_status"] = "no_manifest_supplied"
        pin_entry["publisher_id"] = None

    out_path = Path(args.out)
    if out_path.is_file():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    else:
        existing = {}
    pins = existing.get("pinned_adapters") or []
    # Replace existing pin for same (id, version); else append.
    pins = [
        p for p in pins
        if not (p.get("adapter_id") == args.adapter_id
                and p.get("adapter_version") == args.adapter_version)
    ]
    pins.append(pin_entry)
    pins.sort(key=lambda p: (p["adapter_id"], p["adapter_version"]))
    existing["pinned_adapters"] = pins
    existing.setdefault("_note", (
        "Pins record (adapter_id, adapter_version, contract_hash) plus, "
        "when a manifest is supplied, entry_hash + publisher_id + "
        "entry_signature_status. At evaluation time, your runtime can "
        "refuse any bundle whose embedded contract_hash does not match a "
        "pin. Pinning is a developer-side adoption tool; aigentsy-verify "
        "does not require a pin file to replay a bundle."
    ))
    out_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "pinned": pins, "out": str(out_path)},
                     indent=2))


def _cmd_adapter_bump(args):
    """Replace the adapter_version in a declaration and recompute both
    hashes. Writes the file in place. Refuses to bump backwards."""
    import json, sys
    p = Path(args.path)
    if not p.is_file():
        print(f"error: file not found: {args.path}", file=sys.stderr)
        sys.exit(2)
    if not _SEMVER_RE.match(args.adapter_version):
        print("error: --version must be semver MAJOR.MINOR.PATCH",
              file=sys.stderr)
        sys.exit(2)
    try:
        decl = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"error: failed to parse {args.path}: {e}", file=sys.stderr)
        sys.exit(2)
    old_version = decl.get("adapter_version", "")
    if old_version == args.adapter_version:
        print(f"warning: adapter_version already {args.adapter_version}; "
              f"no change", file=sys.stderr)
        sys.exit(0)
    # Forbid backwards bumps.
    def _tup(v):
        try:
            return tuple(int(x) for x in str(v).split("."))
        except Exception:
            return (-1,)
    if _tup(args.adapter_version) <= _tup(old_version):
        print(f"error: refuse to bump backwards "
              f"({old_version} -> {args.adapter_version}). Use a strictly "
              f"higher semver.", file=sys.stderr)
        sys.exit(2)
    # Preserve key order; replace version + recompute hashes; strip the
    # hashes BEFORE recomputing so canonical input matches the runtime's
    # discipline (recompute helpers ignore the hash fields anyway, but
    # writing the result keeps the file diff minimal).
    decl["adapter_version"] = args.adapter_version
    decl["input_schema_hash"] = _recompute_input_schema_hash(decl)
    decl["contract_hash"] = _recompute_contract_hash(decl)
    p.write_text(json.dumps(decl, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "adapter_id": decl.get("adapter_id"),
        "previous_version": old_version,
        "new_version": args.adapter_version,
        "new_contract_hash": decl["contract_hash"],
        "new_input_schema_hash": decl["input_schema_hash"],
        "path": str(p),
    }, indent=2))


def _cmd_adapter_diff(args):
    """Show a structural diff between two declarations. Highlights field
    additions/removals/changes and the new vs old hashes. Lifecycle
    fields are flagged as 'discovery-only — does NOT change hash'."""
    import json, sys
    op = Path(args.old)
    np = Path(args.new)
    if not op.is_file() or not np.is_file():
        print(f"error: both files must exist", file=sys.stderr)
        sys.exit(2)
    try:
        old = json.loads(op.read_text(encoding="utf-8"))
        new = json.loads(np.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"error: parse: {e}", file=sys.stderr)
        sys.exit(2)
    # Strip _-prefixed metadata.
    old = {k: v for k, v in old.items() if not str(k).startswith("_")}
    new = {k: v for k, v in new.items() if not str(k).startswith("_")}
    LIFECYCLE = {
        "status", "supersedes", "replaced_by", "published_at",
        "min_verifier_version", "distribution_channel",
    }
    keys = sorted(set(old.keys()) | set(new.keys()))
    changes = []
    for k in keys:
        o = old.get(k)
        n = new.get(k)
        if o != n:
            kind = "lifecycle (discovery-only — does NOT change hash)" \
                   if k in LIFECYCLE else "hash-impacting"
            changes.append({"field": k, "kind": kind,
                            "old": o, "new": n})
    # Recompute hashes from both to confirm.
    old_ch = _recompute_contract_hash(old)
    new_ch = _recompute_contract_hash(new)
    print(json.dumps({
        "ok": True,
        "diff_field_count": len(changes),
        "changes": changes,
        "recomputed_old_contract_hash": old_ch,
        "recomputed_new_contract_hash": new_ch,
        "hash_changed": old_ch != new_ch,
        "note": (
            "Lifecycle changes alone do NOT change the canonical "
            "contract_hash. A change of contract_hash means a hash-"
            "impacting field changed — bump adapter_version and "
            "publish a new (id, version) coexistence entry."
        ),
    }, indent=2))


# ── Pass 68 — Publication attestation helpers (CLI-side mirrors) ─────


_MANIFEST_ENTRY_HASHED_FIELDS = (
    "entry_schema_version",
    "adapter_id",
    "adapter_version",
    "contract_hash",
    "input_schema_hash",
    "status",
    "distribution_channel",
    "published_at",
    "docs_url",
    "declaration_url",
    "release_notes",
    "supersedes",
    "replaced_by",
    "publisher_id",
    "publisher_key_id",
)


def _recompute_entry_hash(entry):
    """CLI mirror of protocol.adapter_contract.compute_entry_hash. Same
    canonical-JSON discipline; produces the same digest."""
    payload = {k: entry.get(k, "") for k in _MANIFEST_ENTRY_HASHED_FIELDS}
    return _canonical_hash_cli(payload)


def _recompute_manifest_hash(manifest):
    """CLI mirror of protocol.adapter_contract.compute_manifest_hash."""
    entries = manifest.get("contracts") or []
    return _canonical_hash_cli({
        "manifest_schema_version": manifest.get(
            "manifest_schema_version", "1.0.0",
        ),
        "publisher_id": manifest.get("publisher_id", ""),
        "publisher_key_id": manifest.get("publisher_key_id", ""),
        "ordered_entry_hashes": [e.get("entry_hash", "") for e in entries],
    })


def _verify_ed25519_signature_cli(message_bytes, signature_b64, public_key_base64):
    """Offline Ed25519 verification. Returns True/False. Used by `pin`
    and `manifest verify`. Mirrors the runtime helper and
    aigentsy_verify.merkle.verify_sth_signature's verification path."""
    import base64
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
    except ImportError:
        return False
    try:
        sig = base64.b64decode(signature_b64)
        raw_key = base64.b64decode(public_key_base64)
        pub_key = Ed25519PublicKey.from_public_bytes(raw_key)
        pub_key.verify(sig, message_bytes)
        return True
    except Exception:
        return False


def _load_manifest(path_or_url):
    """Read a manifest from a local path OR an HTTPS URL. The HTTPS path
    is the ONLY network call any aigentsy CLI publication command makes,
    and it is gated by the user passing an explicit URL — never automatic.
    aigentsy-verify never touches this code path."""
    import json
    if str(path_or_url).startswith(("http://", "https://")):
        r = httpx.get(path_or_url, timeout=10.0, follow_redirects=True)
        r.raise_for_status()
        return r.json()
    p = Path(path_or_url)
    if not p.is_file():
        raise FileNotFoundError(f"manifest not found: {path_or_url}")
    return json.loads(p.read_text(encoding="utf-8"))


def _find_manifest_entry(manifest, adapter_id, adapter_version):
    for e in (manifest.get("contracts") or []):
        if (e.get("adapter_id") == adapter_id
                and e.get("adapter_version") == adapter_version):
            return e
    return None


def _cmd_adapter_attest(args):
    """Emit a manifest entry for a local declaration file. The entry is
    unsigned by default; a developer wishing to publish into the AiGentsy
    public manifest sends the unsigned entry to AiGentsy who signs with
    the canonical Ed25519 key.

    Outputs JSON to stdout. Does NOT sign — local signing would require
    private-key access that this CLI deliberately does not have."""
    import json, sys
    p = Path(args.path)
    if not p.is_file():
        print(f"error: file not found: {args.path}", file=sys.stderr)
        sys.exit(2)
    try:
        decl = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"error: parse: {e}", file=sys.stderr)
        sys.exit(2)
    decl = {k: v for k, v in decl.items() if not str(k).startswith("_")}
    errors, warnings = _lint_declaration(decl)
    if errors:
        print(json.dumps({
            "ok": False,
            "errors": errors,
            "warnings": warnings,
            "note": "fix lint errors before attesting; entry_hash would be "
                    "computed over a declaration that does not pass schema "
                    "validation",
        }, indent=2))
        sys.exit(1)

    import datetime as _dt
    now_iso = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {
        "entry_schema_version": "1.0.0",
        "adapter_id": decl["adapter_id"],
        "adapter_version": decl["adapter_version"],
        "contract_hash": decl["contract_hash"],
        "input_schema_hash": decl["input_schema_hash"],
        "status": getattr(args, "status", "active"),
        "distribution_channel": getattr(
            args, "distribution_channel", "developer.local",
        ),
        "published_at": now_iso,
        "docs_url": getattr(args, "docs_url", ""),
        "declaration_url": getattr(args, "declaration_url", ""),
        "release_notes": getattr(args, "release_notes", ""),
        "supersedes": getattr(args, "supersedes", ""),
        "replaced_by": getattr(args, "replaced_by", ""),
        "publisher_id": getattr(args, "publisher_id", "aigentsy.publisher.v1"),
        "publisher_key_id": getattr(
            args, "publisher_key_id", "aigentsy_log_signer_v1",
        ),
    }
    entry_hash = _recompute_entry_hash(entry)
    print(json.dumps({
        "ok": True,
        "entry_hash": entry_hash,
        "entry": entry,
        "next_steps": [
            "Send `entry` (unsigned) to AiGentsy for inclusion in the "
            "public manifest. AiGentsy will sign entry_hash with "
            "aigentsy_log_signer_v1 (the same Ed25519 key used for STH + "
            "OutcomeReceipt + Passport) and publish to "
            "/.well-known/adapter-contracts.manifest.json. Local signing "
            "is intentionally NOT exposed by this CLI — there is no "
            "second signing model.",
            "Pin into your project with: "
            f"aigentsy adapter pin --id {decl['adapter_id']} "
            f"--version {decl['adapter_version']} --hash "
            f"{decl['contract_hash']} --manifest "
            "https://aigentsy.com/specs/adapter-contracts.manifest.json",
        ],
    }, indent=2))


def _cmd_adapter_manifest(args):
    import sys
    if not getattr(args, "manifest_cmd", None):
        print("usage: aigentsy adapter manifest {verify} [...]",
              file=sys.stderr)
        sys.exit(2)
    if args.manifest_cmd == "verify":
        return _cmd_adapter_manifest_verify(args)
    print(f"unknown manifest subcommand: {args.manifest_cmd}", file=sys.stderr)
    sys.exit(2)


def _cmd_adapter_manifest_verify(args):
    """Verify a manifest file or URL offline.

    Steps:
      1. Parse JSON.
      2. Recompute entry_hash for every entry; report per-entry status.
      3. If --public-key-base64 supplied (or --fetch-publisher and a
         publisher document is reachable), verify every entry_signature
         + the top-level manifest_signature.
      4. Recompute manifest_hash.
      5. Detect duplicates of (adapter_id, adapter_version) with diverging
         contract_hash (loud collision per Pass 67 invariants 4/5).
      6. Surface status values per entry.
      7. Print structured report; exit 0 iff every status is ok / no_public_key
         was the only signature-side advisory.

    NEVER silently treats absent signatures as trusted."""
    import json, sys
    try:
        manifest = _load_manifest(args.target)
    except Exception as e:
        print(json.dumps({"ok": False,
                          "error": f"{type(e).__name__}: {e}"}, indent=2))
        sys.exit(1)

    # Resolve the verification key
    pk_b64 = getattr(args, "public_key_base64", None)
    publisher_used = None
    if not pk_b64 and getattr(args, "fetch_publisher", False):
        try:
            pub_doc = _load_manifest(args.publisher_document_url)
            pk_b64 = pub_doc.get("public_key_base64") or pub_doc.get("public_key")
            publisher_used = args.publisher_document_url
        except Exception as e:
            print(json.dumps({
                "ok": False,
                "error": ("publisher_document_fetch_failed: "
                          f"{type(e).__name__}: {e}"),
            }, indent=2))
            sys.exit(1)

    # Entry-level checks
    seen = {}
    entry_reports = []
    loud_collisions = []
    overall_ok = True
    for i, entry in enumerate(manifest.get("contracts") or []):
        report = {
            "index": i,
            "adapter_id": entry.get("adapter_id", ""),
            "adapter_version": entry.get("adapter_version", ""),
            "status": entry.get("status", "active"),
        }
        # entry_hash
        if "entry_hash" not in entry:
            report["entry_hash_status"] = "absent"
            overall_ok = False
        else:
            recomputed = _recompute_entry_hash(entry)
            if recomputed == entry["entry_hash"]:
                report["entry_hash_status"] = "ok"
            else:
                report["entry_hash_status"] = "mismatch"
                report["expected"] = entry["entry_hash"]
                report["recomputed"] = recomputed
                overall_ok = False
        # entry_signature
        if "entry_signature" not in entry:
            report["entry_signature_status"] = "absent"
            overall_ok = False
        elif not pk_b64:
            report["entry_signature_status"] = "no_public_key"
        else:
            ok = _verify_ed25519_signature_cli(
                entry.get("entry_hash", "").encode("utf-8"),
                entry["entry_signature"],
                pk_b64,
            )
            report["entry_signature_status"] = "ok" if ok else "bad"
            if not ok:
                overall_ok = False
        # Status sanity
        if entry.get("status") not in (None, "active", "deprecated", "revoked"):
            report["status_validity"] = "invalid"
            overall_ok = False
        # Duplicate detection
        key = (entry.get("adapter_id", ""), entry.get("adapter_version", ""))
        prior = seen.get(key)
        if prior is not None and prior != entry.get("contract_hash"):
            loud_collisions.append(list(key))
            overall_ok = False
        seen[key] = entry.get("contract_hash")
        entry_reports.append(report)

    # Manifest-level
    manifest_hash_status = "absent"
    if "manifest_hash" in manifest:
        recomputed = _recompute_manifest_hash(manifest)
        if recomputed == manifest["manifest_hash"]:
            manifest_hash_status = "ok"
        else:
            manifest_hash_status = "mismatch"
            overall_ok = False
    if "manifest_signature" in manifest:
        if not pk_b64:
            manifest_signature_status = "no_public_key"
        else:
            ok = _verify_ed25519_signature_cli(
                manifest.get("manifest_hash", "").encode("utf-8"),
                manifest["manifest_signature"],
                pk_b64,
            )
            manifest_signature_status = "ok" if ok else "bad"
            if not ok:
                overall_ok = False
    else:
        manifest_signature_status = "absent"
        if "manifest_hash" in manifest:
            overall_ok = False

    print(json.dumps({
        "ok": overall_ok,
        "manifest_hash_status": manifest_hash_status,
        "manifest_signature_status": manifest_signature_status,
        "loud_collisions": loud_collisions,
        "publisher_document_used": publisher_used,
        "public_key_supplied": bool(pk_b64),
        "entry_count": len(entry_reports),
        "entries": entry_reports,
        "note": (
            "Manifest verification is for adoption provenance only. "
            "aigentsy-verify never reads this manifest; bundles replay "
            "from their embedded declarations. A 'no_public_key' status "
            "means signature verification was NOT performed — it is NOT "
            "silent trust."
        ),
    }, indent=2))
    sys.exit(0 if overall_ok else 1)


# ── Pass 78I — admin subcommand handlers ─────────────────────────────


_ALLOWED_ADMIN_SCOPE_TYPES = ("agent", "account", "workspace", "enterprise")
_MAX_ID_LEN = 200
_MAX_REASON_LEN = 500
# Substring patterns commonly found inside admin tokens; if any of these
# appear inside a string we're about to print, we redact rather than
# emit. Belt-and-suspenders — the code path that emits errors should
# never see the token to begin with.
_TOKEN_FINGERPRINTS = ("ops_", "_authToken", "AdminToken", "X-Admin-Token")


def _redact_token_substrings(s: str) -> str:
    """Replace any token-looking substrings with `***redacted***`. The
    token never leaves the env var in normal paths; this is defensive."""
    if not isinstance(s, str):
        return s
    redacted = s
    for needle in _TOKEN_FINGERPRINTS:
        if needle in redacted:
            redacted = redacted.replace(needle, "***redacted***")
    return redacted


def _has_control_chars(s: str) -> bool:
    if not isinstance(s, str):
        return False
    return any(ord(ch) < 0x20 for ch in s)


def _validate_owner_bound_args(args) -> Tuple[bool, str]:
    """Mirror server constraints client-side. Server remains authoritative."""
    deal_id = (args.deal_id or "").strip()
    agent_id = (args.agent_id or "").strip()
    scope_type = (args.scope_type or "").strip()

    if not deal_id:
        return False, "deal_id is required"
    if len(deal_id) > _MAX_ID_LEN:
        return False, f"deal_id too long (>{_MAX_ID_LEN} chars)"
    if _has_control_chars(deal_id):
        return False, "deal_id contains control characters"

    if not agent_id:
        return False, "agent_id is required"
    if len(agent_id) > _MAX_ID_LEN:
        return False, f"agent_id too long (>{_MAX_ID_LEN} chars)"
    if _has_control_chars(agent_id):
        return False, "agent_id contains control characters"

    if scope_type not in _ALLOWED_ADMIN_SCOPE_TYPES:
        return False, (
            "scope_type must be one of "
            f"{sorted(_ALLOWED_ADMIN_SCOPE_TYPES)}"
        )

    # For non-agent scopes, at least one identity field must be set.
    if scope_type != "agent":
        identity_fields = [
            ("enterprise_id", args.enterprise_id),
            ("workspace_id", args.workspace_id),
            ("account_id", args.account_id),
            ("user_id", args.user_id),
        ]
        if not any((v or "").strip() for _, v in identity_fields):
            return False, (
                f"scope_type={scope_type} requires at least one of "
                "--enterprise-id / --workspace-id / --account-id / --user-id"
            )
        for label, val in identity_fields:
            v = (val or "").strip()
            if not v:
                continue
            if len(v) > _MAX_ID_LEN:
                return False, f"{label} too long (>{_MAX_ID_LEN} chars)"
            if _has_control_chars(v):
                return False, f"{label} contains control characters"

    if args.reason:
        if len(args.reason) > _MAX_REASON_LEN:
            return False, f"reason too long (>{_MAX_REASON_LEN} chars)"
        if _has_control_chars(args.reason):
            return False, "reason contains control characters"

    return True, ""


def cmd_admin(args):
    """Dispatch `aigentsy admin <subcmd>`."""
    sub = getattr(args, "admin_cmd", None)
    if not sub:
        print(
            "Usage:\n"
            "  aigentsy admin owner-bound --help\n"
            "  aigentsy admin account --help\n\n"
            "Admin operations require OPS_ADMIN_KEY in the environment.\n"
            "Never pass the admin token on the command line.",
            file=sys.stderr,
        )
        sys.exit(2)
    if sub == "owner-bound":
        return _cmd_admin_owner_bound(args)
    if sub == "account":
        return _cmd_admin_account(args)
    print(f"Unknown admin subcommand: {sub}", file=sys.stderr)
    sys.exit(2)


def _cmd_admin_account(args):
    """Dispatch `aigentsy admin account <subcmd>`."""
    sub = getattr(args, "account_cmd", None)
    if not sub:
        print(
            "Usage:\n"
            "  aigentsy admin account create --help\n"
            "  aigentsy admin account list --help\n"
            "  aigentsy admin account get --help\n"
            "  aigentsy admin account suspend --help\n"
            "  aigentsy admin account disable --help\n"
            "  aigentsy admin account activate --help\n"
            "  aigentsy admin account membership --help\n\n"
            "All account operations require OPS_ADMIN_KEY in the environment.\n"
            "Never pass the admin token on the command line.",
            file=sys.stderr,
        )
        sys.exit(2)
    handler = {
        "create": _cmd_admin_account_create,
        "list": _cmd_admin_account_list,
        "get": _cmd_admin_account_get,
        "suspend": _cmd_admin_account_suspend,
        "disable": _cmd_admin_account_disable,
        "activate": _cmd_admin_account_activate,
        "membership": _cmd_admin_account_membership,
    }.get(sub)
    if handler is None:
        print(f"Unknown admin account subcommand: {sub}", file=sys.stderr)
        sys.exit(2)
    return handler(args)


def _cmd_admin_account_membership(args):
    """Dispatch `aigentsy admin account membership <subcmd>`."""
    sub = getattr(args, "membership_cmd", None)
    if not sub:
        print(
            "Usage:\n"
            "  aigentsy admin account membership add --help\n"
            "  aigentsy admin account membership list --help\n"
            "  aigentsy admin account membership status --help\n\n"
            "All membership operations require OPS_ADMIN_KEY in the environment.\n"
            "Never pass the admin token on the command line.",
            file=sys.stderr,
        )
        sys.exit(2)
    handler = {
        "add": _cmd_admin_account_membership_add,
        "list": _cmd_admin_account_membership_list,
        "status": _cmd_admin_account_membership_status,
    }.get(sub)
    if handler is None:
        print(f"Unknown admin account membership subcommand: {sub}", file=sys.stderr)
        sys.exit(2)
    return handler(args)


def _cmd_admin_owner_bound(args):
    """Create a platform-attested Vault owner binding by calling the
    admin-protected POST /vault/owner-bound endpoint.

    Token handling: read once from OPS_ADMIN_KEY env var. Send as
    X-Admin-Token. NEVER print or persist. NEVER accept on argv.
    """
    # 1. Token from env. Fail-closed if absent.
    admin_token = os.getenv("OPS_ADMIN_KEY", "")
    if not admin_token:
        print(
            "Error: OPS_ADMIN_KEY environment variable is required.\n"
            "Set it in your shell session (do not paste it into shared "
            "channels or pass it on the command line):\n"
            "  read -s OPS_ADMIN_KEY; export OPS_ADMIN_KEY",
            file=sys.stderr,
        )
        sys.exit(2)

    # 2. Pre-flight validation (mirrors server; server is authoritative).
    ok, err = _validate_owner_bound_args(args)
    if not ok:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(2)

    # 3. Build JSON body. Strip whitespace; omit None fields so the
    #    server's default behavior applies for absent fields.
    body = {
        "deal_id": args.deal_id.strip(),
        "agent_id": args.agent_id.strip(),
        "scope_type": args.scope_type.strip(),
    }
    for key, src in (
        ("enterprise_id", args.enterprise_id),
        ("workspace_id", args.workspace_id),
        ("account_id", args.account_id),
        ("user_id", args.user_id),
        ("reason", args.reason),
    ):
        v = (src or "").strip()
        if v:
            body[key] = v

    print(
        "WARNING: This command creates a platform-attested Vault owner "
        "binding.\nIt is an admin operation. Do not run unless you "
        "intend to bind\nthe deal+agent to the specified scope.",
        file=sys.stderr,
    )

    # 4. Send the request. Use the existing httpx client + BASE URL.
    try:
        import httpx
    except ImportError:
        print(
            "Error: httpx is not installed. Run: pip install httpx",
            file=sys.stderr,
        )
        sys.exit(2)

    url = BASE.rstrip("/") + "/vault/owner-bound"
    headers = {
        "X-Admin-Token": admin_token,
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, headers=headers, json=body)
    except httpx.HTTPError as e:
        # Never include `headers` in the message — that would leak the
        # token. Only mention the URL (which does not include the token).
        print(
            f"Error: network failure contacting {url}: "
            f"{_redact_token_substrings(str(e))}",
            file=sys.stderr,
        )
        sys.exit(3)
    finally:
        # Defensive: clear the token from local scope as soon as
        # possible. Python doesn't make this a hard guarantee but the
        # intent is documented.
        admin_token = ""
        headers = None

    # 5. Handle response.
    status = resp.status_code
    if status == 403:
        print(
            "Error: admin token rejected or missing (HTTP 403). "
            "Verify OPS_ADMIN_KEY is set to the current Render value.",
            file=sys.stderr,
        )
        sys.exit(3)
    if status == 422:
        try:
            detail = resp.json().get("detail")
        except Exception:
            detail = resp.text[:300]
        print(
            "Error: server validation failed (HTTP 422): "
            f"{_redact_token_substrings(str(detail))}",
            file=sys.stderr,
        )
        sys.exit(2)
    if status == 503:
        print(
            "Error: vault records subsystem unavailable on the runtime "
            f"(HTTP {status}). Try again or check /build status.",
            file=sys.stderr,
        )
        sys.exit(3)
    if status >= 400:
        # Generic non-2xx — surface status + body but never headers.
        try:
            body_resp = resp.json()
        except Exception:
            body_resp = {"raw": resp.text[:300]}
        print(
            f"Error: unexpected HTTP {status} from {url}: "
            f"{_redact_token_substrings(json.dumps(body_resp))}",
            file=sys.stderr,
        )
        sys.exit(3)

    # 2xx — must be JSON.
    try:
        data = resp.json()
    except Exception:
        print(
            f"Error: server returned non-JSON response (HTTP {status}).",
            file=sys.stderr,
        )
        sys.exit(3)

    # Concise success result.
    if not isinstance(data, dict) or not data.get("ok"):
        print(
            "Error: server response did not signal ok=True: "
            f"{_redact_token_substrings(json.dumps(data)[:300])}",
            file=sys.stderr,
        )
        sys.exit(3)

    out = {
        "ok": True,
        "binding_id": data.get("binding_id"),
        "deal_id": data.get("deal_id"),
        "agent_id": data.get("agent_id"),
        "scope_type": data.get("scope_type"),
        "enterprise_id": data.get("enterprise_id"),
        "workspace_id": data.get("workspace_id"),
        "account_id": data.get("account_id"),
        "user_id": data.get("user_id"),
        "attested": data.get("attested"),
        "binding_quality": data.get("binding_quality"),
        "issuer": data.get("issuer"),
        "source_event_id": data.get("source_event_id"),
        "stored_binding_present": data.get("stored_binding_present"),
        "demo": data.get("demo"),
    }
    print(json.dumps(out, indent=2))


# ── Pass 79C Stage 2 — admin account handlers ────────────────────────


_ALLOWED_ACCOUNT_TYPES = ("developer", "enterprise", "internal", "demo")
_ALLOWED_ACCOUNT_STATUSES = ("active", "suspended", "disabled")


def _require_admin_token() -> str:
    """Read OPS_ADMIN_KEY from env. Fail-closed with sanitized message."""
    tok = os.getenv("OPS_ADMIN_KEY", "")
    if not tok:
        print(
            "Error: OPS_ADMIN_KEY environment variable is required.\n"
            "Set it in your shell session (do not paste it into shared "
            "channels or pass it on the command line):\n"
            "  read -s OPS_ADMIN_KEY; export OPS_ADMIN_KEY",
            file=sys.stderr,
        )
        sys.exit(2)
    return tok


def _account_base_url(args) -> str:
    """Resolve runtime base URL. --base-url overrides the AME_BASE env."""
    override = getattr(args, "base_url", None)
    if override:
        return override.rstrip("/")
    return BASE.rstrip("/")


def _account_handle_http_error(resp, *, url: str) -> None:
    """Map HTTP error responses to sanitized stderr + exit code. Token-
    scrubbed; never echoes headers."""
    status = resp.status_code
    if status == 403:
        print(
            "Error: admin token rejected or missing (HTTP 403). "
            "Verify OPS_ADMIN_KEY is set to the current Render value.",
            file=sys.stderr,
        )
        sys.exit(3)
    if status == 404:
        print(
            f"Error: account not found (HTTP 404) at {url}.",
            file=sys.stderr,
        )
        sys.exit(3)
    if status == 422:
        try:
            detail = resp.json().get("detail")
        except Exception:
            detail = resp.text[:300]
        print(
            "Error: server validation failed (HTTP 422): "
            f"{_redact_token_substrings(str(detail))}",
            file=sys.stderr,
        )
        sys.exit(2)
    if status == 503:
        print(
            f"Error: account registry subsystem unavailable (HTTP {status}).",
            file=sys.stderr,
        )
        sys.exit(3)
    if status >= 400:
        try:
            body_resp = resp.json()
        except Exception:
            body_resp = {"raw": resp.text[:300]}
        print(
            f"Error: unexpected HTTP {status} from {url}: "
            f"{_redact_token_substrings(json.dumps(body_resp))}",
            file=sys.stderr,
        )
        sys.exit(3)


def _account_http_call(method: str, url: str, *, json_body=None,
                       query=None) -> "Any":
    """POST/GET wrapper that sends X-Admin-Token internally only.
    Token is read from env at call time and cleared from local scope
    immediately after the request. Never echoes the token in any
    error path."""
    try:
        import httpx
    except ImportError:
        print(
            "Error: httpx is not installed. Run: pip install httpx",
            file=sys.stderr,
        )
        sys.exit(2)

    admin_token = _require_admin_token()
    headers = {
        "X-Admin-Token": admin_token,
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            if method == "GET":
                resp = client.get(url, headers=headers, params=query)
            elif method == "POST":
                resp = client.post(url, headers=headers, json=json_body)
            else:
                raise ValueError(f"unsupported method {method}")
    except httpx.HTTPError as e:
        # NEVER include headers (would leak the token). Only URL.
        print(
            f"Error: network failure contacting {url}: "
            f"{_redact_token_substrings(str(e))}",
            file=sys.stderr,
        )
        sys.exit(3)
    finally:
        admin_token = ""
        headers = None
    return resp


def _print_json(data) -> None:
    """Print JSON output through the same redaction sieve. Defense-in-
    depth: the server NEVER includes the token in responses; this guards
    against future regressions."""
    print(_redact_token_substrings(json.dumps(data, indent=2)))


def _cmd_admin_account_create(args):
    """POST /admin/accounts — create/upsert an account row."""
    # Client-side enum validation (server is authoritative).
    if args.account_type not in _ALLOWED_ACCOUNT_TYPES:
        print(
            f"Error: --account-type must be one of {list(_ALLOWED_ACCOUNT_TYPES)}",
            file=sys.stderr,
        )
        sys.exit(2)
    if args.status not in _ALLOWED_ACCOUNT_STATUSES:
        print(
            f"Error: --status must be one of {list(_ALLOWED_ACCOUNT_STATUSES)}",
            file=sys.stderr,
        )
        sys.exit(2)
    if not (args.account_id or "").strip():
        print("Error: --account-id is required", file=sys.stderr)
        sys.exit(2)
    if not (args.owner_agent_id or "").strip():
        print("Error: --owner-agent-id is required", file=sys.stderr)
        sys.exit(2)
    if _has_control_chars(args.account_id):
        print("Error: --account-id contains control characters", file=sys.stderr)
        sys.exit(2)

    body = {
        "account_id": args.account_id.strip(),
        "account_type": args.account_type,
        "owner_agent_id": args.owner_agent_id.strip(),
        "status": args.status,
    }
    for key, src in (
        ("account_name", args.account_name),
        ("enterprise_id", args.enterprise_id),
        ("workspace_id", args.workspace_id),
        ("owner_email", args.owner_email),
    ):
        v = (src or "").strip()
        if v:
            body[key] = v

    url = _account_base_url(args) + "/admin/accounts"
    resp = _account_http_call("POST", url, json_body=body)
    _account_handle_http_error(resp, url=url)
    try:
        data = resp.json()
    except Exception:
        print(
            f"Error: server returned non-JSON response (HTTP {resp.status_code}).",
            file=sys.stderr,
        )
        sys.exit(3)
    _print_json(data)


def _cmd_admin_account_list(args):
    """GET /admin/accounts — list with optional filters."""
    if args.status is not None and args.status not in _ALLOWED_ACCOUNT_STATUSES:
        print(
            f"Error: --status must be one of {list(_ALLOWED_ACCOUNT_STATUSES)}",
            file=sys.stderr,
        )
        sys.exit(2)

    query = {}
    for key, src in (
        ("account_id", args.account_id),
        ("enterprise_id", args.enterprise_id),
        ("owner_agent_id", args.owner_agent_id),
        ("status", args.status),
    ):
        v = (src or "").strip() if isinstance(src, str) else None
        if v:
            query[key] = v

    url = _account_base_url(args) + "/admin/accounts"
    resp = _account_http_call("GET", url, query=query)
    _account_handle_http_error(resp, url=url)
    try:
        data = resp.json()
    except Exception:
        print(
            f"Error: server returned non-JSON response (HTTP {resp.status_code}).",
            file=sys.stderr,
        )
        sys.exit(3)
    _print_json(data)


def _cmd_admin_account_get(args):
    """GET /admin/accounts/{account_id} — fetch one row."""
    if not (args.account_id or "").strip():
        print("Error: --account-id is required", file=sys.stderr)
        sys.exit(2)
    account_id = args.account_id.strip()
    if _has_control_chars(account_id):
        print("Error: --account-id contains control characters", file=sys.stderr)
        sys.exit(2)

    url = _account_base_url(args) + f"/admin/accounts/{account_id}"
    resp = _account_http_call("GET", url)
    _account_handle_http_error(resp, url=url)
    try:
        data = resp.json()
    except Exception:
        print(
            f"Error: server returned non-JSON response (HTTP {resp.status_code}).",
            file=sys.stderr,
        )
        sys.exit(3)
    _print_json(data)


def _account_status_call(args, new_status: str):
    """Shared helper for suspend/disable/activate."""
    if not (args.account_id or "").strip():
        print("Error: --account-id is required", file=sys.stderr)
        sys.exit(2)
    account_id = args.account_id.strip()
    if _has_control_chars(account_id):
        print("Error: --account-id contains control characters", file=sys.stderr)
        sys.exit(2)
    if new_status not in _ALLOWED_ACCOUNT_STATUSES:
        # Defense in depth — caller passes a constant, but guard anyway.
        print(
            f"Error: internal: bad status {new_status}",
            file=sys.stderr,
        )
        sys.exit(2)
    url = _account_base_url(args) + f"/admin/accounts/{account_id}/status"
    resp = _account_http_call("POST", url, json_body={"status": new_status})
    _account_handle_http_error(resp, url=url)
    try:
        data = resp.json()
    except Exception:
        print(
            f"Error: server returned non-JSON response (HTTP {resp.status_code}).",
            file=sys.stderr,
        )
        sys.exit(3)
    _print_json(data)


def _cmd_admin_account_suspend(args):
    _account_status_call(args, "suspended")


def _cmd_admin_account_disable(args):
    _account_status_call(args, "disabled")


def _cmd_admin_account_activate(args):
    _account_status_call(args, "active")


# ── Pass 79F Stage 2 — admin account membership handlers ────────────


_ALLOWED_MEMBERSHIP_ROLES = ("owner", "admin", "operator", "auditor", "viewer")


def _cmd_admin_account_membership_add(args):
    """POST /admin/accounts/{account_id}/memberships — create / upsert."""
    if not (args.account_id or "").strip():
        print("Error: --account-id is required", file=sys.stderr)
        sys.exit(2)
    if not (args.agent_id or "").strip():
        print("Error: --agent-id is required", file=sys.stderr)
        sys.exit(2)
    if args.role not in _ALLOWED_MEMBERSHIP_ROLES:
        print(
            f"Error: --role must be one of {list(_ALLOWED_MEMBERSHIP_ROLES)}",
            file=sys.stderr,
        )
        sys.exit(2)
    if args.status not in _ALLOWED_ACCOUNT_STATUSES:
        print(
            f"Error: --status must be one of {list(_ALLOWED_ACCOUNT_STATUSES)}",
            file=sys.stderr,
        )
        sys.exit(2)
    account_id = args.account_id.strip()
    if _has_control_chars(account_id):
        print("Error: --account-id contains control characters", file=sys.stderr)
        sys.exit(2)
    if _has_control_chars(args.agent_id.strip()):
        print("Error: --agent-id contains control characters", file=sys.stderr)
        sys.exit(2)

    body = {
        "agent_id": args.agent_id.strip(),
        "role": args.role,
        "status": args.status,
    }
    # NOTE: enterprise_id / workspace_id are denormalized by the server
    # from the parent AccountRecord. The CLI accepts the flags for
    # forward compatibility but does NOT pass them in the body — the
    # runtime endpoint ignores client-supplied scope context to prevent
    # spoofing.

    url = _account_base_url(args) + f"/admin/accounts/{account_id}/memberships"
    resp = _account_http_call("POST", url, json_body=body)
    _account_handle_http_error(resp, url=url)
    try:
        data = resp.json()
    except Exception:
        print(
            f"Error: server returned non-JSON response (HTTP {resp.status_code}).",
            file=sys.stderr,
        )
        sys.exit(3)
    _print_json(data)


def _cmd_admin_account_membership_list(args):
    """GET /admin/accounts/{account_id}/memberships — list."""
    if not (args.account_id or "").strip():
        print("Error: --account-id is required", file=sys.stderr)
        sys.exit(2)
    if args.status is not None and args.status not in _ALLOWED_ACCOUNT_STATUSES:
        print(
            f"Error: --status must be one of {list(_ALLOWED_ACCOUNT_STATUSES)}",
            file=sys.stderr,
        )
        sys.exit(2)
    account_id = args.account_id.strip()
    if _has_control_chars(account_id):
        print("Error: --account-id contains control characters", file=sys.stderr)
        sys.exit(2)

    query = {}
    if args.status:
        query["status"] = args.status

    url = _account_base_url(args) + f"/admin/accounts/{account_id}/memberships"
    resp = _account_http_call("GET", url, query=query)
    _account_handle_http_error(resp, url=url)
    try:
        data = resp.json()
    except Exception:
        print(
            f"Error: server returned non-JSON response (HTTP {resp.status_code}).",
            file=sys.stderr,
        )
        sys.exit(3)
    _print_json(data)


def _cmd_admin_account_membership_status(args):
    """POST /admin/accounts/{account_id}/memberships/{membership_id}/status."""
    if not (args.account_id or "").strip():
        print("Error: --account-id is required", file=sys.stderr)
        sys.exit(2)
    if not (args.membership_id or "").strip():
        print("Error: --membership-id is required", file=sys.stderr)
        sys.exit(2)
    if args.status not in _ALLOWED_ACCOUNT_STATUSES:
        print(
            f"Error: --status must be one of {list(_ALLOWED_ACCOUNT_STATUSES)}",
            file=sys.stderr,
        )
        sys.exit(2)
    account_id = args.account_id.strip()
    membership_id = args.membership_id.strip()
    if _has_control_chars(account_id) or _has_control_chars(membership_id):
        print("Error: id contains control characters", file=sys.stderr)
        sys.exit(2)

    url = (
        _account_base_url(args)
        + f"/admin/accounts/{account_id}/memberships/{membership_id}/status"
    )
    resp = _account_http_call("POST", url, json_body={"status": args.status})
    _account_handle_http_error(resp, url=url)
    try:
        data = resp.json()
    except Exception:
        print(
            f"Error: server returned non-JSON response (HTTP {resp.status_code}).",
            file=sys.stderr,
        )
        sys.exit(3)
    _print_json(data)


if __name__ == "__main__":
    main()
