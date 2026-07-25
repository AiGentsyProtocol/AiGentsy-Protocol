"""Pass 79C Stage 2 — Tests for `aigentsy admin account` CLI.

Subcommands tested: create, list, get, suspend, disable, activate.

Mirrors the `test_cli_admin_owner_bound.py` test-fixture pattern:
  - subprocess invocation of the CLI against the source tree.
  - optional httpx monkeypatch via a wrapper script.
  - sentinel-token guards across multiple token shapes.

Security invariants (load-bearing):
  - OPS_ADMIN_KEY env-only; never accepted as `--admin-token` or positional.
  - The token NEVER appears in stdout / stderr in any code path.
  - PyPI / npm / V77D3 / X-Admin-Token sentinels also never appear.
  - HTTP errors are surfaced cleanly without leaking headers.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


SDK_ROOT = Path(__file__).parent.parent
SDK_SRC = SDK_ROOT / "src"


# Sentinel tokens — used to assert non-leakage. None of these are real.
SENTINEL_OPS_TOKEN = "ops_SENTINEL_79C_SHOULD_NOT_PRINT_in_output_xxxx"
SENTINEL_PYPI_TOKEN = "pypi-AgEISENTINEL_79C_SHOULD_NOT_PRINT_xxxx"
SENTINEL_NPM_TOKEN = "npm_SENTINEL79CSHOULDNOTPRINTxxxxxxxxxxxxxxxxxxxxxx"
SENTINEL_V77 = "V77D3_SENTINEL_SHOULD_NOT_PRINT_xxxx"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_cli(*args, env_extra=None, mock_httpx_script=None, cwd=None):
    """Invoke `aigentsy <args>` in a subprocess against the source tree."""
    cwd = cwd or SDK_ROOT
    env = os.environ.copy()
    env.pop("OPS_ADMIN_KEY", None)
    env["PYTHONPATH"] = str(SDK_SRC) + os.pathsep + env.get("PYTHONPATH", "")
    if env_extra:
        env.update(env_extra)

    if mock_httpx_script:
        import tempfile
        wrapper_dir = tempfile.mkdtemp(prefix="aigentsy_cli_acct_wrapper_")
        wrapper_path = Path(wrapper_dir) / "wrapper.py"
        wrapper_path.write_text(
            mock_httpx_script
            + "\n\nimport sys\n"
            + f"sys.argv = ['aigentsy', {', '.join(repr(a) for a in args)}]\n"
            + "from aigentsy.cli import main\n"
            + "main()\n"
        )
        return subprocess.run(
            [sys.executable, str(wrapper_path)],
            cwd=cwd, env=env, capture_output=True, text=True, timeout=30,
        )

    return subprocess.run(
        [sys.executable, "-m", "aigentsy", *args],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=30,
    )


def _no_token_anywhere(token: str, *outputs: str) -> bool:
    return all(token not in (o or "") for o in outputs)


def _assert_no_sentinels(stdout: str, stderr: str):
    """Defense in depth — assert none of the 4 sentinel patterns nor
    X-Admin-Token / X-API-Key literals appear in CLI output."""
    for sentinel in (
        SENTINEL_OPS_TOKEN, SENTINEL_PYPI_TOKEN, SENTINEL_NPM_TOKEN,
        SENTINEL_V77,
    ):
        assert _no_token_anywhere(sentinel, stdout, stderr), (
            f"sentinel '{sentinel[:30]}…' leaked to CLI output"
        )
    # X-Admin-Token header literal must never appear in output
    # (the CLI builds it internally only).
    assert "X-Admin-Token" not in stdout
    assert "X-Admin-Token" not in stderr


_MOCK_HTTPX_200 = """
import httpx
class _MockResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"ok": True, "account_id": "acct_x",
                                    "account_type": "developer",
                                    "status": "active"}
        self.text = ""
    def json(self):
        return self._payload
def _post(self, url, *args, **kwargs):
    # Defensive: assert the token never appears in the URL.
    assert "ops_" not in url
    return _MockResp()
def _get(self, url, *args, **kwargs):
    if url.endswith("/admin/accounts"):
        return _MockResp(payload={
            "ok": True, "accounts": [{"account_id": "a1", "status": "active"}],
            "count": 1, "filters_applied": {},
        })
    return _MockResp(payload={
        "ok": True, "account": {"account_id": "acct_x", "status": "active"}
    })
httpx.Client.post = _post
httpx.Client.get = _get
"""


_MOCK_HTTPX_403 = """
import httpx
class _MockResp:
    status_code = 403
    text = "forbidden"
    def json(self): return {"detail": "forbidden"}
def _post(self, url, *args, **kwargs): return _MockResp()
def _get(self, url, *args, **kwargs): return _MockResp()
httpx.Client.post = _post
httpx.Client.get = _get
"""


_MOCK_HTTPX_404 = """
import httpx
class _MockResp:
    status_code = 404
    text = "not found"
    def json(self): return {"detail": "account_not_found"}
def _get(self, url, *args, **kwargs): return _MockResp()
def _post(self, url, *args, **kwargs): return _MockResp()
httpx.Client.get = _get
httpx.Client.post = _post
"""


# ---------------------------------------------------------------------------
# Help / discovery (1-7)
# ---------------------------------------------------------------------------


def test_01_admin_account_help_works():
    r = _run_cli("admin", "account", "--help")
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    for sub in ("create", "list", "get", "suspend", "disable", "activate"):
        assert sub in combined


def test_02_admin_account_create_help_shows_args():
    r = _run_cli("admin", "account", "create", "--help")
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    for flag in (
        "--account-id", "--account-type", "--owner-agent-id",
        "--account-name", "--enterprise-id", "--workspace-id",
        "--owner-email", "--status", "--base-url",
    ):
        assert flag in combined


def test_03_admin_account_list_help_shows_args():
    r = _run_cli("admin", "account", "list", "--help")
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    for flag in (
        "--account-id", "--enterprise-id", "--owner-agent-id",
        "--status", "--base-url",
    ):
        assert flag in combined


def test_04_admin_account_get_help_shows_args():
    r = _run_cli("admin", "account", "get", "--help")
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    assert "--account-id" in combined
    assert "--base-url" in combined


def test_05_admin_account_suspend_help_works():
    r = _run_cli("admin", "account", "suspend", "--help")
    assert r.returncode == 0
    assert "--account-id" in (r.stdout + r.stderr)


def test_06_admin_account_disable_help_works():
    r = _run_cli("admin", "account", "disable", "--help")
    assert r.returncode == 0
    assert "--account-id" in (r.stdout + r.stderr)


def test_07_admin_account_activate_help_works():
    r = _run_cli("admin", "account", "activate", "--help")
    assert r.returncode == 0
    assert "--account-id" in (r.stdout + r.stderr)


# ---------------------------------------------------------------------------
# No --admin-token flag exposed anywhere (8)
# ---------------------------------------------------------------------------


def test_08_no_account_command_exposes_admin_token_flag():
    """No account subcommand may accept --admin-token. The flag must
    not appear in any --help output."""
    for sub in ("create", "list", "get", "suspend", "disable", "activate"):
        r = _run_cli("admin", "account", sub, "--help")
        combined = r.stdout + r.stderr
        assert "--admin-token" not in combined, (
            f"admin account {sub} exposes --admin-token"
        )


# ---------------------------------------------------------------------------
# Missing OPS_ADMIN_KEY fail-closed (9-10)
# ---------------------------------------------------------------------------


def test_09_missing_ops_admin_key_create_fails_clearly():
    r = _run_cli(
        "admin", "account", "create",
        "--account-id", "acct_test",
        "--account-type", "developer",
        "--owner-agent-id", "ag_test",
    )
    assert r.returncode != 0
    assert "OPS_ADMIN_KEY" in r.stderr


def test_10_missing_ops_admin_key_does_not_print_secret_patterns():
    r = _run_cli(
        "admin", "account", "create",
        "--account-id", "acct_test",
        "--account-type", "developer",
        "--owner-agent-id", "ag_test",
    )
    _assert_no_sentinels(r.stdout, r.stderr)


# ---------------------------------------------------------------------------
# Create — POST /admin/accounts + 403 + client-side validation (11-17)
# ---------------------------------------------------------------------------


def test_11_create_sends_post_to_admin_accounts():
    """Mock httpx to capture the URL; assert it's /admin/accounts and
    the body carries account_id."""
    mock = """
import httpx
calls = {}
class _R:
    status_code = 200
    text = ""
    def json(self): return {"ok": True, "account_id": "acct_x",
                            "account_type": "developer", "status": "active"}
def _post(self, url, *args, **kwargs):
    calls['url'] = url
    calls['body'] = kwargs.get('json')
    print('CAPTURED_POST_URL:', url)
    print('CAPTURED_POST_BODY_ACCOUNT_ID:', kwargs.get('json', {}).get('account_id'))
    return _R()
httpx.Client.post = _post
"""
    r = _run_cli(
        "admin", "account", "create",
        "--account-id", "acct_x",
        "--account-type", "developer",
        "--owner-agent-id", "ag_x",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=mock,
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert "/admin/accounts" in r.stdout
    assert "CAPTURED_POST_BODY_ACCOUNT_ID: acct_x" in r.stdout
    _assert_no_sentinels(r.stdout, r.stderr)


def test_12_create_sends_x_admin_token_header_internally():
    """The X-Admin-Token header must be set on the request — but its
    value (the sentinel token) must NEVER appear in CLI output."""
    mock = """
import httpx
class _R:
    status_code = 200; text = ""
    def json(self): return {"ok": True, "account_id": "x",
                            "account_type": "developer", "status": "active"}
def _post(self, url, *args, **kwargs):
    headers = kwargs.get('headers', {})
    # Header presence is required for the request — but we MUST NOT
    # echo the token. So we only assert the header KEY exists.
    assert 'X-Admin-Token' in headers, f"missing header in {list(headers.keys())}"
    print('HEADER_KEY_PRESENT')
    return _R()
httpx.Client.post = _post
"""
    r = _run_cli(
        "admin", "account", "create",
        "--account-id", "acct_x",
        "--account-type", "developer",
        "--owner-agent-id", "ag_x",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=mock,
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert "HEADER_KEY_PRESENT" in r.stdout
    _assert_no_sentinels(r.stdout, r.stderr)


def test_13_create_validates_account_type():
    """argparse choices reject invalid account_type before network."""
    r = _run_cli(
        "admin", "account", "create",
        "--account-id", "acct_x",
        "--account-type", "bogus_type",
        "--owner-agent-id", "ag_x",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
    )
    assert r.returncode != 0
    combined = (r.stdout + r.stderr).lower()
    assert "invalid choice" in combined or "account-type" in combined
    _assert_no_sentinels(r.stdout, r.stderr)


def test_14_create_validates_status():
    """argparse choices reject invalid --status."""
    r = _run_cli(
        "admin", "account", "create",
        "--account-id", "acct_x",
        "--account-type", "developer",
        "--owner-agent-id", "ag_x",
        "--status", "bogus_status",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
    )
    assert r.returncode != 0
    _assert_no_sentinels(r.stdout, r.stderr)


def test_15_create_supports_base_url_override():
    """--base-url overrides the runtime URL. Captured URL must contain
    the override host."""
    mock = """
import httpx
class _R:
    status_code = 200; text = ""
    def json(self): return {"ok": True, "account_id": "x",
                            "account_type": "developer", "status": "active"}
def _post(self, url, *args, **kwargs):
    print('CAPTURED_URL:', url)
    return _R()
httpx.Client.post = _post
"""
    r = _run_cli(
        "admin", "account", "create",
        "--account-id", "acct_x",
        "--account-type", "developer",
        "--owner-agent-id", "ag_x",
        "--base-url", "https://example.test:9999",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=mock,
    )
    assert r.returncode == 0
    assert "CAPTURED_URL: https://example.test:9999/admin/accounts" in r.stdout


def test_16_create_handles_http_403():
    r = _run_cli(
        "admin", "account", "create",
        "--account-id", "acct_x",
        "--account-type", "developer",
        "--owner-agent-id", "ag_x",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=_MOCK_HTTPX_403,
    )
    assert r.returncode != 0
    assert "403" in r.stderr
    _assert_no_sentinels(r.stdout, r.stderr)


def test_17_create_prints_sanitized_json_on_success():
    r = _run_cli(
        "admin", "account", "create",
        "--account-id", "acct_x",
        "--account-type", "developer",
        "--owner-agent-id", "ag_x",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=_MOCK_HTTPX_200,
    )
    assert r.returncode == 0
    # Output must be parseable JSON with ok=True.
    parsed = json.loads(r.stdout)
    assert parsed.get("ok") is True
    _assert_no_sentinels(r.stdout, r.stderr)


# ---------------------------------------------------------------------------
# List + get + filter behavior (18-21)
# ---------------------------------------------------------------------------


def test_18_list_sends_get_to_admin_accounts():
    mock = """
import httpx
class _R:
    status_code = 200; text = ""
    def json(self): return {"ok": True, "accounts": [], "count": 0,
                            "filters_applied": {}}
def _get(self, url, *args, **kwargs):
    print('CAPTURED_GET_URL:', url)
    return _R()
httpx.Client.get = _get
"""
    r = _run_cli(
        "admin", "account", "list",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=mock,
    )
    assert r.returncode == 0
    assert "/admin/accounts" in r.stdout
    _assert_no_sentinels(r.stdout, r.stderr)


def test_19_list_passes_filters_correctly():
    mock = """
import httpx
class _R:
    status_code = 200; text = ""
    def json(self): return {"ok": True, "accounts": [], "count": 0,
                            "filters_applied": {}}
def _get(self, url, *args, **kwargs):
    print('CAPTURED_PARAMS:', kwargs.get('params'))
    return _R()
httpx.Client.get = _get
"""
    r = _run_cli(
        "admin", "account", "list",
        "--enterprise-id", "ent_TEST",
        "--status", "active",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=mock,
    )
    assert r.returncode == 0
    assert "ent_TEST" in r.stdout
    assert "active" in r.stdout
    _assert_no_sentinels(r.stdout, r.stderr)


def test_20_get_sends_get_to_admin_accounts_id():
    mock = """
import httpx
class _R:
    status_code = 200; text = ""
    def json(self): return {"ok": True, "account": {"account_id": "acct_z"}}
def _get(self, url, *args, **kwargs):
    print('CAPTURED_URL:', url)
    return _R()
httpx.Client.get = _get
"""
    r = _run_cli(
        "admin", "account", "get",
        "--account-id", "acct_z",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=mock,
    )
    assert r.returncode == 0
    assert "/admin/accounts/acct_z" in r.stdout
    _assert_no_sentinels(r.stdout, r.stderr)


def test_21_get_handles_404():
    r = _run_cli(
        "admin", "account", "get",
        "--account-id", "acct_missing",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=_MOCK_HTTPX_404,
    )
    assert r.returncode != 0
    assert "404" in r.stderr
    _assert_no_sentinels(r.stdout, r.stderr)


# ---------------------------------------------------------------------------
# Status updates: suspend / disable / activate (22-24)
# ---------------------------------------------------------------------------


def _capture_status_call_mock():
    return """
import httpx
class _R:
    status_code = 200; text = ""
    def json(self): return {"ok": True, "account_id": "acct_x",
                            "status": "suspended", "account": {}}
def _post(self, url, *args, **kwargs):
    body = kwargs.get('json') or {}
    print('CAPTURED_URL:', url)
    print('CAPTURED_STATUS:', body.get('status'))
    return _R()
httpx.Client.post = _post
"""


def test_22_suspend_sends_post_status_with_suspended():
    r = _run_cli(
        "admin", "account", "suspend",
        "--account-id", "acct_x",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=_capture_status_call_mock(),
    )
    assert r.returncode == 0
    assert "/admin/accounts/acct_x/status" in r.stdout
    assert "CAPTURED_STATUS: suspended" in r.stdout
    _assert_no_sentinels(r.stdout, r.stderr)


def test_23_disable_sends_post_status_with_disabled():
    r = _run_cli(
        "admin", "account", "disable",
        "--account-id", "acct_x",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=_capture_status_call_mock(),
    )
    assert r.returncode == 0
    assert "/admin/accounts/acct_x/status" in r.stdout
    assert "CAPTURED_STATUS: disabled" in r.stdout
    _assert_no_sentinels(r.stdout, r.stderr)


def test_24_activate_sends_post_status_with_active():
    r = _run_cli(
        "admin", "account", "activate",
        "--account-id", "acct_x",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=_capture_status_call_mock(),
    )
    assert r.returncode == 0
    assert "/admin/accounts/acct_x/status" in r.stdout
    assert "CAPTURED_STATUS: active" in r.stdout
    _assert_no_sentinels(r.stdout, r.stderr)


# ---------------------------------------------------------------------------
# Sentinel-token leakage guards (25-29)
# ---------------------------------------------------------------------------


def test_25_sentinel_ops_token_absent_from_stdout_on_success():
    r = _run_cli(
        "admin", "account", "create",
        "--account-id", "acct_x",
        "--account-type", "developer",
        "--owner-agent-id", "ag_x",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=_MOCK_HTTPX_200,
    )
    assert _no_token_anywhere(SENTINEL_OPS_TOKEN, r.stdout)


def test_26_sentinel_ops_token_absent_from_stderr_on_error():
    r = _run_cli(
        "admin", "account", "create",
        "--account-id", "acct_x",
        "--account-type", "developer",
        "--owner-agent-id", "ag_x",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=_MOCK_HTTPX_403,
    )
    assert _no_token_anywhere(SENTINEL_OPS_TOKEN, r.stderr)
    assert _no_token_anywhere(SENTINEL_OPS_TOKEN, r.stdout)


def test_27_pypi_sentinel_absent_from_output():
    """Confirm pypi-shaped tokens never appear (defense in depth — the
    CLI doesn't deal in PyPI tokens, but if a developer environment had
    leaked one, our redactor would catch it via the broad pattern set)."""
    env = {
        "OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN,
        "TWINE_PASSWORD": SENTINEL_PYPI_TOKEN,
    }
    r = _run_cli(
        "admin", "account", "create",
        "--account-id", "acct_x",
        "--account-type", "developer",
        "--owner-agent-id", "ag_x",
        env_extra=env,
        mock_httpx_script=_MOCK_HTTPX_200,
    )
    assert _no_token_anywhere(SENTINEL_PYPI_TOKEN, r.stdout)
    assert _no_token_anywhere(SENTINEL_PYPI_TOKEN, r.stderr)


def test_28_npm_sentinel_absent_from_output():
    env = {
        "OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN,
        "NPM_TOKEN": SENTINEL_NPM_TOKEN,
    }
    r = _run_cli(
        "admin", "account", "list",
        env_extra=env,
        mock_httpx_script=_MOCK_HTTPX_200,
    )
    assert _no_token_anywhere(SENTINEL_NPM_TOKEN, r.stdout)
    assert _no_token_anywhere(SENTINEL_NPM_TOKEN, r.stderr)


def test_29_x_admin_token_literal_absent_from_output():
    """The string 'X-Admin-Token' is reserved for internal header use.
    It must not appear in any CLI output (which would suggest header
    structure leaked into a message)."""
    r = _run_cli(
        "admin", "account", "suspend",
        "--account-id", "acct_x",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=_capture_status_call_mock(),
    )
    assert "X-Admin-Token" not in r.stdout
    assert "X-Admin-Token" not in r.stderr


# ---------------------------------------------------------------------------
# Existing tests still pass + non-mutation invariants (30-32)
# ---------------------------------------------------------------------------


def test_30_admin_owner_bound_command_still_registered():
    """The 79C account family additions MUST NOT regress 78I owner-bound."""
    r = _run_cli("admin", "owner-bound", "--help")
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    for flag in ("--deal-id", "--agent-id", "--scope-type"):
        assert flag in combined


def test_31_admin_no_subcommand_lists_both_families_in_usage():
    """When `aigentsy admin` is called with no subcommand, the usage
    message MUST mention BOTH owner-bound and account so operators
    discover them."""
    r = _run_cli("admin")
    combined = r.stdout + r.stderr
    assert "owner-bound" in combined
    assert "account" in combined


def test_32_required_args_enforced_for_all_status_subcommands():
    """suspend / disable / activate all require --account-id."""
    for sub in ("suspend", "disable", "activate"):
        r = _run_cli(
            "admin", "account", sub,
            env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        )
        assert r.returncode != 0, f"{sub} should fail without --account-id"
        combined = (r.stdout + r.stderr).lower()
        assert "account-id" in combined or "required" in combined
