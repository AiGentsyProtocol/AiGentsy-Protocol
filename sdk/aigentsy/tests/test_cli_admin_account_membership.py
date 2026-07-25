"""Pass 79F Stage 2 — Tests for `aigentsy admin account membership` CLI.

Subcommands tested: add, list, status.

Mirrors the 79C test pattern (subprocess + httpx mock). Same sentinel-
token discipline: admin-key-shaped, PyPI-token-shaped, npm-token-shaped,
and X-Admin-Token literal must never appear in CLI output.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


SDK_ROOT = Path(__file__).parent.parent
SDK_SRC = SDK_ROOT / "src"


SENTINEL_OPS_TOKEN = "ops_SENTINEL_79F_SHOULD_NOT_PRINT_in_output_xxxx"
SENTINEL_PYPI_TOKEN = "pypi-AgEISENTINEL_79F_SHOULD_NOT_PRINT_xxxx"
SENTINEL_NPM_TOKEN = "npm_SENTINEL79FSHOULDNOTPRINTxxxxxxxxxxxxxxxxxxxxxx"
SENTINEL_V77 = "V77D3_SENTINEL_SHOULD_NOT_PRINT_xxxx"


def _run_cli(*args, env_extra=None, mock_httpx_script=None, cwd=None):
    cwd = cwd or SDK_ROOT
    env = os.environ.copy()
    env.pop("OPS_ADMIN_KEY", None)
    env["PYTHONPATH"] = str(SDK_SRC) + os.pathsep + env.get("PYTHONPATH", "")
    if env_extra:
        env.update(env_extra)

    if mock_httpx_script:
        import tempfile
        wrapper_dir = tempfile.mkdtemp(prefix="aigentsy_cli_mb_wrapper_")
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
    for sentinel in (
        SENTINEL_OPS_TOKEN, SENTINEL_PYPI_TOKEN, SENTINEL_NPM_TOKEN, SENTINEL_V77
    ):
        assert _no_token_anywhere(sentinel, stdout, stderr), (
            f"sentinel '{sentinel[:30]}…' leaked"
        )
    assert "X-Admin-Token" not in stdout
    assert "X-Admin-Token" not in stderr


_MOCK_HTTPX_200_ADD = """
import httpx
class _R:
    status_code = 200; text = ""
    def json(self): return {"ok": True, "membership": {
        "membership_id": "mb_test", "account_id": "a1",
        "agent_id": "ag1", "role": "auditor", "status": "active",
        "enterprise_id": None, "workspace_id": None,
        "created_at": 1.0, "updated_at": 1.0,
        "source": "admin_api", "attested": True,
        "binding_quality": "platform_attested",
    }}
def _post(self, url, *args, **kwargs):
    print('CAPTURED_URL:', url)
    body = kwargs.get('json') or {}
    print('CAPTURED_ROLE:', body.get('role'))
    print('CAPTURED_AGENT:', body.get('agent_id'))
    return _R()
httpx.Client.post = _post
"""


_MOCK_HTTPX_200_LIST = """
import httpx
class _R:
    status_code = 200; text = ""
    def json(self): return {"ok": True, "account_id": "a1",
                            "memberships": [], "count": 0,
                            "filters_applied": {}}
def _get(self, url, *args, **kwargs):
    print('CAPTURED_URL:', url)
    print('CAPTURED_PARAMS:', kwargs.get('params'))
    return _R()
httpx.Client.get = _get
"""


_MOCK_HTTPX_200_STATUS = """
import httpx
class _R:
    status_code = 200; text = ""
    def json(self): return {"ok": True, "membership_id": "mb_test",
                            "status": "suspended", "updated_at": 2.0,
                            "membership": {}}
def _post(self, url, *args, **kwargs):
    body = kwargs.get('json') or {}
    print('CAPTURED_URL:', url)
    print('CAPTURED_STATUS:', body.get('status'))
    return _R()
httpx.Client.post = _post
"""


_MOCK_HTTPX_403 = """
import httpx
class _R:
    status_code = 403; text = "forbidden"
    def json(self): return {"detail": "forbidden"}
def _post(self, url, *args, **kwargs): return _R()
def _get(self, url, *args, **kwargs): return _R()
httpx.Client.post = _post
httpx.Client.get = _get
"""


# ── Help / discovery (1-4) ────────────────────────────────────────────


def test_01_membership_help_works():
    r = _run_cli("admin", "account", "membership", "--help")
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    for sub in ("add", "list", "status"):
        assert sub in combined


def test_02_add_help_shows_args():
    r = _run_cli("admin", "account", "membership", "add", "--help")
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    for flag in (
        "--account-id", "--agent-id", "--role", "--enterprise-id",
        "--workspace-id", "--status", "--base-url",
    ):
        assert flag in combined


def test_03_list_help_shows_args():
    r = _run_cli("admin", "account", "membership", "list", "--help")
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    for flag in ("--account-id", "--status", "--base-url"):
        assert flag in combined


def test_04_status_help_shows_args():
    r = _run_cli("admin", "account", "membership", "status", "--help")
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    for flag in ("--account-id", "--membership-id", "--status", "--base-url"):
        assert flag in combined


# ── No --admin-token flag (5) ─────────────────────────────────────────


def test_05_no_membership_command_exposes_admin_token_flag():
    for sub in ("add", "list", "status"):
        r = _run_cli("admin", "account", "membership", sub, "--help")
        combined = r.stdout + r.stderr
        assert "--admin-token" not in combined


# ── Missing OPS_ADMIN_KEY (6-7) ───────────────────────────────────────


def test_06_missing_ops_admin_key_add_fails_clearly():
    r = _run_cli(
        "admin", "account", "membership", "add",
        "--account-id", "a1", "--agent-id", "ag1", "--role", "auditor",
    )
    assert r.returncode != 0
    assert "OPS_ADMIN_KEY" in r.stderr


def test_07_missing_ops_admin_key_does_not_leak_secret_patterns():
    r = _run_cli(
        "admin", "account", "membership", "add",
        "--account-id", "a1", "--agent-id", "ag1", "--role", "auditor",
    )
    _assert_no_sentinels(r.stdout, r.stderr)


# ── Add (8-14) ────────────────────────────────────────────────────────


def test_08_add_sends_post_to_memberships_endpoint():
    r = _run_cli(
        "admin", "account", "membership", "add",
        "--account-id", "a1", "--agent-id", "ag1", "--role", "auditor",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=_MOCK_HTTPX_200_ADD,
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert "/admin/accounts/a1/memberships" in r.stdout
    assert "CAPTURED_ROLE: auditor" in r.stdout
    assert "CAPTURED_AGENT: ag1" in r.stdout
    _assert_no_sentinels(r.stdout, r.stderr)


def test_09_add_sends_x_admin_token_header_internally():
    mock = """
import httpx
class _R:
    status_code = 200; text = ""
    def json(self): return {"ok": True, "membership": {}}
def _post(self, url, *args, **kwargs):
    headers = kwargs.get('headers', {})
    assert 'X-Admin-Token' in headers
    print('HEADER_KEY_PRESENT')
    return _R()
httpx.Client.post = _post
"""
    r = _run_cli(
        "admin", "account", "membership", "add",
        "--account-id", "a1", "--agent-id", "ag1", "--role", "auditor",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=mock,
    )
    assert r.returncode == 0
    assert "HEADER_KEY_PRESENT" in r.stdout
    _assert_no_sentinels(r.stdout, r.stderr)


def test_10_add_validates_role():
    r = _run_cli(
        "admin", "account", "membership", "add",
        "--account-id", "a1", "--agent-id", "ag1", "--role", "superuser",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
    )
    assert r.returncode != 0
    combined = (r.stdout + r.stderr).lower()
    assert "invalid choice" in combined or "role" in combined
    _assert_no_sentinels(r.stdout, r.stderr)


def test_11_add_validates_status():
    r = _run_cli(
        "admin", "account", "membership", "add",
        "--account-id", "a1", "--agent-id", "ag1", "--role", "auditor",
        "--status", "bogus_status",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
    )
    assert r.returncode != 0
    _assert_no_sentinels(r.stdout, r.stderr)


def test_12_add_supports_base_url_override():
    mock = """
import httpx
class _R:
    status_code = 200; text = ""
    def json(self): return {"ok": True, "membership": {}}
def _post(self, url, *args, **kwargs):
    print('CAPTURED_URL:', url)
    return _R()
httpx.Client.post = _post
"""
    r = _run_cli(
        "admin", "account", "membership", "add",
        "--account-id", "a1", "--agent-id", "ag1", "--role", "auditor",
        "--base-url", "https://example.test:9999",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=mock,
    )
    assert r.returncode == 0
    assert "CAPTURED_URL: https://example.test:9999/admin/accounts/a1/memberships" in r.stdout


def test_13_add_handles_http_403():
    r = _run_cli(
        "admin", "account", "membership", "add",
        "--account-id", "a1", "--agent-id", "ag1", "--role", "auditor",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=_MOCK_HTTPX_403,
    )
    assert r.returncode != 0
    assert "403" in r.stderr
    _assert_no_sentinels(r.stdout, r.stderr)


def test_14_add_prints_sanitized_json_on_success():
    r = _run_cli(
        "admin", "account", "membership", "add",
        "--account-id", "a1", "--agent-id", "ag1", "--role", "auditor",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=_MOCK_HTTPX_200_ADD,
    )
    assert r.returncode == 0
    # The output includes both the captured-URL print AND the JSON. The last
    # line of stdout is the JSON payload's closing brace; the JSON payload is
    # somewhere in stdout.
    assert '"ok"' in r.stdout and "true" in r.stdout.lower()
    _assert_no_sentinels(r.stdout, r.stderr)


# ── List (15-17) ──────────────────────────────────────────────────────


def test_15_list_sends_get_to_memberships_endpoint():
    r = _run_cli(
        "admin", "account", "membership", "list",
        "--account-id", "a1",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=_MOCK_HTTPX_200_LIST,
    )
    assert r.returncode == 0
    assert "CAPTURED_URL: https://" in r.stdout
    assert "/admin/accounts/a1/memberships" in r.stdout
    _assert_no_sentinels(r.stdout, r.stderr)


def test_16_list_handles_http_403():
    r = _run_cli(
        "admin", "account", "membership", "list",
        "--account-id", "a1",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=_MOCK_HTTPX_403,
    )
    assert r.returncode != 0
    assert "403" in r.stderr
    _assert_no_sentinels(r.stdout, r.stderr)


def test_17_list_prints_sanitized_json_on_success():
    r = _run_cli(
        "admin", "account", "membership", "list",
        "--account-id", "a1",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=_MOCK_HTTPX_200_LIST,
    )
    assert r.returncode == 0
    assert '"ok"' in r.stdout and "true" in r.stdout.lower()
    _assert_no_sentinels(r.stdout, r.stderr)


# ── Status (18-21) ────────────────────────────────────────────────────


def test_18_status_sends_post_to_status_endpoint():
    r = _run_cli(
        "admin", "account", "membership", "status",
        "--account-id", "a1", "--membership-id", "mb_test",
        "--status", "suspended",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=_MOCK_HTTPX_200_STATUS,
    )
    assert r.returncode == 0
    assert "/admin/accounts/a1/memberships/mb_test/status" in r.stdout
    assert "CAPTURED_STATUS: suspended" in r.stdout
    _assert_no_sentinels(r.stdout, r.stderr)


def test_19_status_validates_status():
    r = _run_cli(
        "admin", "account", "membership", "status",
        "--account-id", "a1", "--membership-id", "mb_test",
        "--status", "not_a_status",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
    )
    assert r.returncode != 0
    _assert_no_sentinels(r.stdout, r.stderr)


def test_20_status_handles_http_403():
    r = _run_cli(
        "admin", "account", "membership", "status",
        "--account-id", "a1", "--membership-id", "mb_test",
        "--status", "suspended",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=_MOCK_HTTPX_403,
    )
    assert r.returncode != 0
    assert "403" in r.stderr
    _assert_no_sentinels(r.stdout, r.stderr)


def test_21_status_prints_sanitized_json_on_success():
    r = _run_cli(
        "admin", "account", "membership", "status",
        "--account-id", "a1", "--membership-id", "mb_test",
        "--status", "suspended",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=_MOCK_HTTPX_200_STATUS,
    )
    assert r.returncode == 0
    assert '"ok"' in r.stdout and "true" in r.stdout.lower()
    _assert_no_sentinels(r.stdout, r.stderr)


# ── Sentinel-token leakage (22-26) ────────────────────────────────────


def test_22_sentinel_ops_absent_from_stdout():
    r = _run_cli(
        "admin", "account", "membership", "add",
        "--account-id", "a1", "--agent-id", "ag1", "--role", "auditor",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=_MOCK_HTTPX_200_ADD,
    )
    assert _no_token_anywhere(SENTINEL_OPS_TOKEN, r.stdout)


def test_23_sentinel_ops_absent_from_stderr():
    r = _run_cli(
        "admin", "account", "membership", "add",
        "--account-id", "a1", "--agent-id", "ag1", "--role", "auditor",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=_MOCK_HTTPX_403,
    )
    assert _no_token_anywhere(SENTINEL_OPS_TOKEN, r.stderr)


def test_24_pypi_sentinel_absent_from_output():
    env = {
        "OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN,
        "TWINE_PASSWORD": SENTINEL_PYPI_TOKEN,
    }
    r = _run_cli(
        "admin", "account", "membership", "list",
        "--account-id", "a1",
        env_extra=env,
        mock_httpx_script=_MOCK_HTTPX_200_LIST,
    )
    assert _no_token_anywhere(SENTINEL_PYPI_TOKEN, r.stdout, r.stderr)


def test_25_npm_sentinel_absent_from_output():
    env = {
        "OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN,
        "NPM_TOKEN": SENTINEL_NPM_TOKEN,
    }
    r = _run_cli(
        "admin", "account", "membership", "list",
        "--account-id", "a1",
        env_extra=env,
        mock_httpx_script=_MOCK_HTTPX_200_LIST,
    )
    assert _no_token_anywhere(SENTINEL_NPM_TOKEN, r.stdout, r.stderr)


def test_26_x_admin_token_literal_absent_from_output():
    r = _run_cli(
        "admin", "account", "membership", "status",
        "--account-id", "a1", "--membership-id", "mb_test",
        "--status", "suspended",
        env_extra={"OPS_ADMIN_KEY": SENTINEL_OPS_TOKEN},
        mock_httpx_script=_MOCK_HTTPX_200_STATUS,
    )
    assert "X-Admin-Token" not in r.stdout
    assert "X-Admin-Token" not in r.stderr


# ── Existing CLI families still work (27-28) ──────────────────────────


def test_27_admin_account_create_help_still_works():
    """The 79C account subcommand family must remain intact."""
    r = _run_cli("admin", "account", "create", "--help")
    assert r.returncode == 0
    assert "--account-id" in (r.stdout + r.stderr)


def test_28_admin_owner_bound_still_registered():
    """The 78I owner-bound CLI must remain intact."""
    r = _run_cli("admin", "owner-bound", "--help")
    assert r.returncode == 0
    assert "--deal-id" in (r.stdout + r.stderr)
    assert "--agent-id" in (r.stdout + r.stderr)


def test_29_admin_no_subcommand_lists_account_and_owner_bound():
    """`aigentsy admin` with no subcommand still lists both families."""
    r = _run_cli("admin")
    combined = r.stdout + r.stderr
    assert "owner-bound" in combined
    assert "account" in combined


# ── Account subcommand discovery still includes membership (extra) ──


def test_30_admin_account_no_subcommand_lists_membership():
    r = _run_cli("admin", "account")
    combined = r.stdout + r.stderr
    assert "membership" in combined.lower()
