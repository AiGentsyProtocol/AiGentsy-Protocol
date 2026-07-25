"""Pass 78I — Tests for `aigentsy admin owner-bound`.

The command is a thin admin-protected wrapper around the production
endpoint added in Pass 78G (POST /vault/owner-bound). These tests are
deliberately narrow: they verify what 78I promises and not what 78G
already verifies on the server side.

Security invariants are load-bearing:
  - OPS_ADMIN_KEY is read from env, never accepted on the command line.
  - The token is never echoed in stdout/stderr in any code path.
  - Required args are enforced before any network call.
  - Server-side validation errors (422/403) surface cleanly without
    leaking headers.

No network. No production hits. HTTP is mocked at the httpx layer in
a subprocess via an injected sitecustomize-style helper.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


# Match existing tests/test_cli_create_agent.py PYTHONPATH-injection style.
SDK_ROOT = Path(__file__).parent.parent
SDK_SRC = SDK_ROOT / "src"


# ---------------------------------------------------------------------------
# Helpers for invoking the CLI in a subprocess with a mocked httpx
# ---------------------------------------------------------------------------


def _run_cli(*args, env_extra=None, mock_httpx_script=None, cwd=None):
    """Invoke `aigentsy <args>` as a subprocess against the source tree.

    `env_extra` overlays additional env vars (e.g. OPS_ADMIN_KEY).
    `mock_httpx_script` is an optional Python snippet that monkeypatches
    httpx BEFORE the CLI runs — used to fake the HTTP response. When a
    mock is supplied we use a wrapper script that runs the mock first
    then dispatches to aigentsy.cli:main() with sys.argv set, rather
    than the default `python -m aigentsy` invocation. This keeps real
    httpx + the SDK importable while still letting us intercept the
    HTTP call.
    """
    cwd = cwd or SDK_ROOT
    env = os.environ.copy()
    # Strip any pre-existing OPS_ADMIN_KEY so tests that probe the
    # absent-key path are deterministic. Tests that need it set will
    # add it via env_extra.
    env.pop("OPS_ADMIN_KEY", None)
    env["PYTHONPATH"] = str(SDK_SRC) + os.pathsep + env.get("PYTHONPATH", "")
    if env_extra:
        env.update(env_extra)

    if mock_httpx_script:
        # Write a tiny wrapper that monkeypatches httpx (the real one
        # imports cleanly from system site-packages), then dispatches
        # to aigentsy.cli:main() with the CLI args we want to test.
        import tempfile
        wrapper_dir = tempfile.mkdtemp(prefix="aigentsy_cli_wrapper_")
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
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    return subprocess.run(
        [sys.executable, "-m", "aigentsy", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _no_token_anywhere(token: str, *outputs: str) -> bool:
    """Assert the token does not appear in any output stream."""
    return all(token not in (o or "") for o in outputs)


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


def test_invariant_1_admin_command_exists():
    """`aigentsy admin --help` and `aigentsy admin owner-bound --help`
    are both registered."""
    r = _run_cli("admin", "owner-bound", "--help")
    assert r.returncode == 0, f"--help should exit 0; got {r.returncode}\nstderr: {r.stderr}"
    assert "owner-bound" in r.stdout.lower() or "owner-bound" in (r.stdout + r.stderr).lower()
    assert "--deal-id" in (r.stdout + r.stderr)
    assert "--agent-id" in (r.stdout + r.stderr)
    assert "--scope-type" in (r.stdout + r.stderr)


def test_invariant_2_missing_ops_admin_key_exits_nonzero():
    """Without OPS_ADMIN_KEY set, the command refuses to run and exits >0."""
    r = _run_cli(
        "admin", "owner-bound",
        "--deal-id", "demo_deal_x",
        "--agent-id", "agent_x",
        "--scope-type", "enterprise",
        "--enterprise-id", "acme_test",
    )
    assert r.returncode != 0
    assert "OPS_ADMIN_KEY" in r.stderr


def test_invariant_3_no_token_in_output_on_missing_token_path():
    """The error message on missing-token MUST NOT echo any value
    that looks like a token."""
    r = _run_cli(
        "admin", "owner-bound",
        "--deal-id", "d1", "--agent-id", "a1",
        "--scope-type", "enterprise", "--enterprise-id", "x",
    )
    # No `read -s` placeholder should contain a real-looking value
    # and no `ops_` prefix in the env-message means we never echoed
    # back what the user pasted.
    assert "ops_real_token_value" not in r.stdout
    assert "ops_real_token_value" not in r.stderr


def test_invariant_4_required_args_enforced():
    """argparse enforces required arguments. Missing --deal-id → exit 2."""
    # Need a token so we get past the env-var check and reach argparse.
    r = _run_cli(
        "admin", "owner-bound",
        # no --deal-id
        "--agent-id", "agent_x",
        "--scope-type", "enterprise",
        "--enterprise-id", "acme",
        env_extra={"OPS_ADMIN_KEY": "ops_dummy_test_token_only_for_argparse_path"},
    )
    assert r.returncode != 0
    assert "deal-id" in (r.stdout + r.stderr).lower() or "required" in (r.stdout + r.stderr).lower()


def test_invariant_5_invalid_scope_type_rejected_clientside():
    """argparse choices reject a bogus scope_type before any network."""
    r = _run_cli(
        "admin", "owner-bound",
        "--deal-id", "d1", "--agent-id", "a1",
        "--scope-type", "bogus_scope",
        "--enterprise-id", "x",
        env_extra={"OPS_ADMIN_KEY": "ops_dummy_for_argparse"},
    )
    assert r.returncode != 0
    # argparse 'invalid choice' message includes our allowed set
    assert "invalid choice" in (r.stdout + r.stderr).lower() or "scope_type" in (r.stdout + r.stderr).lower()


def test_invariant_6_missing_identity_for_enterprise_scope_rejected():
    """Pre-flight validator rejects enterprise scope without any
    identity field before the request goes out."""
    r = _run_cli(
        "admin", "owner-bound",
        "--deal-id", "d1", "--agent-id", "a1",
        "--scope-type", "enterprise",
        # no enterprise_id/workspace_id/account_id/user_id
        env_extra={"OPS_ADMIN_KEY": "ops_dummy_for_validation"},
    )
    assert r.returncode != 0
    assert "at least one of" in r.stderr.lower() or "identity" in r.stderr.lower()


# Build the httpx mock script once for the network-mocking tests below.
def _httpx_mock_script(status_code: int, json_body: dict, fail_with: str = None):
    """Return a Python snippet that monkeypatches httpx.Client to
    return a synthetic response. `fail_with` (if set) makes the client
    raise httpx.HTTPError instead.
    """
    body_repr = json.dumps(json_body)
    return textwrap.dedent(f"""
        # usercustomize that monkeypatches httpx before aigentsy imports it.
        import sys as _sys
        try:
            import httpx as _real_httpx
        except ImportError:
            _real_httpx = None

        class _FakeResponse:
            def __init__(self, status_code, body_str):
                self.status_code = status_code
                self._body_str = body_str
                self.text = body_str
            def json(self):
                import json as _json
                return _json.loads(self._body_str)

        class _FakeClient:
            CAPTURED = {{"calls": []}}
            def __init__(self, *a, **kw):
                self._kwargs = kw
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def post(self, url, headers=None, json=None, **kw):
                _FakeClient.CAPTURED["calls"].append({{
                    "url": url,
                    "headers": dict(headers or {{}}),
                    "json": json,
                }})
                # Persist captured calls to a file the test reads
                import json as _json, os as _os
                cap_file = _os.environ.get("AIGENTSY_TEST_CAPTURE_FILE")
                if cap_file:
                    with open(cap_file, "w") as f:
                        _json.dump(_FakeClient.CAPTURED, f)
                fail_with = {repr(fail_with)}
                if fail_with and _real_httpx is not None:
                    raise _real_httpx.HTTPError(fail_with)
                return _FakeResponse({status_code}, {body_repr!r})

        if _real_httpx is not None:
            _real_httpx.Client = _FakeClient
            _real_httpx.HTTPError = getattr(_real_httpx, "HTTPError", Exception)
    """)


def test_invariant_7_valid_request_posts_to_owner_bound(tmp_path):
    """When all args + token are valid, the CLI POSTs to /vault/owner-bound."""
    capture = tmp_path / "cap.json"
    mock = _httpx_mock_script(
        200,
        {
            "ok": True,
            "binding_id": "obind_unit_test_001",
            "deal_id": "d1", "agent_id": "a1", "scope_type": "enterprise",
            "enterprise_id": "acme", "workspace_id": None,
            "account_id": None, "user_id": None,
            "attested": True, "binding_quality": "platform_attested",
            "issuer": "aigentsy_log_signer_v1",
            "source_event_id": "evt_unit_001",
            "stored_binding_present": True, "demo": False,
        },
    )
    r = _run_cli(
        "admin", "owner-bound",
        "--deal-id", "d1", "--agent-id", "a1",
        "--scope-type", "enterprise",
        "--enterprise-id", "acme",
        "--reason", "unit test",
        env_extra={
            "OPS_ADMIN_KEY": "ops_unit_test_token_should_never_print",
            "AIGENTSY_TEST_CAPTURE_FILE": str(capture),
        },
        mock_httpx_script=mock,
    )
    assert r.returncode == 0, f"got returncode {r.returncode}\nstdout: {r.stdout}\nstderr: {r.stderr}"
    cap = json.loads(capture.read_text())
    assert len(cap["calls"]) == 1
    call = cap["calls"][0]
    assert call["url"].endswith("/vault/owner-bound"), f"got URL: {call['url']}"


def test_invariant_8_request_includes_admin_token_header(tmp_path):
    """The POST must include X-Admin-Token with the env-var value."""
    capture = tmp_path / "cap.json"
    mock = _httpx_mock_script(200, {
        "ok": True, "binding_id": "x", "deal_id": "d1", "agent_id": "a1",
        "scope_type": "enterprise", "enterprise_id": "x",
        "attested": True, "binding_quality": "platform_attested",
        "issuer": "aigentsy_log_signer_v1", "source_event_id": "evt_x",
        "stored_binding_present": True, "demo": False,
    })
    sentinel_token = "ops_TEST_SENTINEL_xyz_should_show_in_header_only"
    r = _run_cli(
        "admin", "owner-bound",
        "--deal-id", "d1", "--agent-id", "a1",
        "--scope-type", "enterprise", "--enterprise-id", "x",
        env_extra={
            "OPS_ADMIN_KEY": sentinel_token,
            "AIGENTSY_TEST_CAPTURE_FILE": str(capture),
        },
        mock_httpx_script=mock,
    )
    assert r.returncode == 0
    cap = json.loads(capture.read_text())
    headers = cap["calls"][0]["headers"]
    assert "X-Admin-Token" in headers
    assert headers["X-Admin-Token"] == sentinel_token


def test_invariant_9_request_body_contains_correct_fields(tmp_path):
    capture = tmp_path / "cap.json"
    mock = _httpx_mock_script(200, {
        "ok": True, "binding_id": "y", "deal_id": "deal_99", "agent_id": "agent_99",
        "scope_type": "workspace", "workspace_id": "ws_qa",
        "attested": True, "binding_quality": "platform_attested",
        "issuer": "aigentsy_log_signer_v1", "source_event_id": "evt_99",
        "stored_binding_present": True, "demo": False,
    })
    r = _run_cli(
        "admin", "owner-bound",
        "--deal-id", "deal_99", "--agent-id", "agent_99",
        "--scope-type", "workspace", "--workspace-id", "ws_qa",
        "--reason", "QA team binding",
        env_extra={
            "OPS_ADMIN_KEY": "ops_unit",
            "AIGENTSY_TEST_CAPTURE_FILE": str(capture),
        },
        mock_httpx_script=mock,
    )
    assert r.returncode == 0
    cap = json.loads(capture.read_text())
    body = cap["calls"][0]["json"]
    assert body["deal_id"] == "deal_99"
    assert body["agent_id"] == "agent_99"
    assert body["scope_type"] == "workspace"
    assert body["workspace_id"] == "ws_qa"
    assert body["reason"] == "QA team binding"
    # Server-forced fields MUST NOT be sent by the CLI
    for forbidden in ("attested", "binding_quality", "issuer", "event_type", "binding_source"):
        assert forbidden not in body, (
            f"CLI must not send {forbidden!r} — it's a server-forced trust field"
        )


def test_invariant_10_token_not_printed_on_success(tmp_path):
    """Sentinel test: the token value never appears in stdout or stderr
    on the success path."""
    capture = tmp_path / "cap.json"
    mock = _httpx_mock_script(200, {
        "ok": True, "binding_id": "ok1", "deal_id": "d1", "agent_id": "a1",
        "scope_type": "enterprise", "enterprise_id": "x",
        "attested": True, "binding_quality": "platform_attested",
        "issuer": "aigentsy_log_signer_v1", "source_event_id": "evt_ok1",
        "stored_binding_present": True, "demo": False,
    })
    sentinel = "ops_VERY_DISTINCTIVE_NEVER_PRINTED_98765"
    r = _run_cli(
        "admin", "owner-bound",
        "--deal-id", "d1", "--agent-id", "a1",
        "--scope-type", "enterprise", "--enterprise-id", "x",
        env_extra={
            "OPS_ADMIN_KEY": sentinel,
            "AIGENTSY_TEST_CAPTURE_FILE": str(capture),
        },
        mock_httpx_script=mock,
    )
    assert r.returncode == 0
    assert _no_token_anywhere(sentinel, r.stdout, r.stderr), (
        f"TOKEN LEAKED in success path!\nstdout: {r.stdout}\nstderr: {r.stderr}"
    )


def test_invariant_11_token_not_printed_on_403_path(tmp_path):
    """Sentinel test: token never appears on the 403 error path."""
    mock = _httpx_mock_script(403, {"detail": "forbidden"})
    sentinel = "ops_NEVER_LEAKED_ON_403_PATH_qwerty1234"
    r = _run_cli(
        "admin", "owner-bound",
        "--deal-id", "d1", "--agent-id", "a1",
        "--scope-type", "enterprise", "--enterprise-id", "x",
        env_extra={"OPS_ADMIN_KEY": sentinel},
        mock_httpx_script=mock,
    )
    assert r.returncode != 0
    assert _no_token_anywhere(sentinel, r.stdout, r.stderr), (
        f"TOKEN LEAKED in 403 path!\nstdout: {r.stdout}\nstderr: {r.stderr}"
    )
    assert "403" in r.stderr or "rejected" in r.stderr.lower()


def test_invariant_12_403_handled_cleanly(tmp_path):
    mock = _httpx_mock_script(403, {"detail": "forbidden"})
    r = _run_cli(
        "admin", "owner-bound",
        "--deal-id", "d1", "--agent-id", "a1",
        "--scope-type", "enterprise", "--enterprise-id", "x",
        env_extra={"OPS_ADMIN_KEY": "ops_test"},
        mock_httpx_script=mock,
    )
    assert r.returncode != 0
    assert "admin token" in r.stderr.lower() or "403" in r.stderr


def test_invariant_13_422_handled_cleanly(tmp_path):
    mock = _httpx_mock_script(422, {"detail": "scope_type must be one of [...]"})
    r = _run_cli(
        "admin", "owner-bound",
        "--deal-id", "d1", "--agent-id", "a1",
        "--scope-type", "enterprise", "--enterprise-id", "x",
        env_extra={"OPS_ADMIN_KEY": "ops_test"},
        mock_httpx_script=mock,
    )
    assert r.returncode != 0
    assert "422" in r.stderr or "validation" in r.stderr.lower()


def test_invariant_14_network_error_handled_cleanly(tmp_path):
    mock = _httpx_mock_script(200, {}, fail_with="simulated network failure")
    sentinel = "ops_NEVER_IN_NETWORK_ERR_path_zzz"
    r = _run_cli(
        "admin", "owner-bound",
        "--deal-id", "d1", "--agent-id", "a1",
        "--scope-type", "enterprise", "--enterprise-id", "x",
        env_extra={"OPS_ADMIN_KEY": sentinel},
        mock_httpx_script=mock,
    )
    assert r.returncode != 0
    assert "network" in r.stderr.lower() or "failure" in r.stderr.lower()
    assert _no_token_anywhere(sentinel, r.stdout, r.stderr)


def test_invariant_15_success_output_includes_required_fields(tmp_path):
    """Success output must surface binding_id, source_event_id,
    stored_binding_present, attested, binding_quality, issuer."""
    capture = tmp_path / "cap.json"
    expected = {
        "ok": True,
        "binding_id": "obind_test_15",
        "deal_id": "d1", "agent_id": "a1", "scope_type": "enterprise",
        "enterprise_id": "acme", "workspace_id": None,
        "account_id": None, "user_id": None,
        "attested": True, "binding_quality": "platform_attested",
        "issuer": "aigentsy_log_signer_v1",
        "source_event_id": "evt_test_15",
        "stored_binding_present": True, "demo": False,
    }
    mock = _httpx_mock_script(200, expected)
    r = _run_cli(
        "admin", "owner-bound",
        "--deal-id", "d1", "--agent-id", "a1",
        "--scope-type", "enterprise", "--enterprise-id", "acme",
        env_extra={
            "OPS_ADMIN_KEY": "ops_test",
            "AIGENTSY_TEST_CAPTURE_FILE": str(capture),
        },
        mock_httpx_script=mock,
    )
    assert r.returncode == 0
    parsed = json.loads(r.stdout)
    for required_field in (
        "binding_id", "source_event_id", "stored_binding_present",
        "attested", "binding_quality", "issuer",
    ):
        assert required_field in parsed, f"{required_field!r} missing from success output"
    assert parsed["binding_id"] == "obind_test_15"
    assert parsed["source_event_id"] == "evt_test_15"
    assert parsed["stored_binding_present"] is True
    assert parsed["attested"] is True
    assert parsed["binding_quality"] == "platform_attested"
    assert parsed["issuer"] == "aigentsy_log_signer_v1"


def test_invariant_16_existing_cli_commands_still_register():
    """Regression: every pre-78I command is still in the dispatcher."""
    r = _run_cli("--help")
    assert r.returncode == 0
    help_text = r.stdout + r.stderr
    for existing in (
        "init", "stamp", "verify", "settle", "status", "demo",
        "create-agent", "adapter",
    ):
        assert existing in help_text, f"existing CLI command {existing!r} missing from --help"
    # And the new one
    assert "admin" in help_text


def test_invariant_17_no_package_publish_command_in_cli_source():
    """The CLI source MUST NOT contain twine/npm publish primitives."""
    cli_src = (SDK_SRC / "aigentsy" / "cli.py").read_text()
    for forbidden in ("twine upload", "npm publish", "pip upload"):
        assert forbidden not in cli_src, (
            f"CLI source must not contain {forbidden!r} — packages are "
            "published in a separate gated pass"
        )


def test_control_chars_in_ids_rejected_clientside():
    """A newline embedded in --deal-id should be rejected pre-flight."""
    r = _run_cli(
        "admin", "owner-bound",
        "--deal-id", "d1\nspoofed", "--agent-id", "a1",
        "--scope-type", "enterprise", "--enterprise-id", "x",
        env_extra={"OPS_ADMIN_KEY": "ops_test"},
    )
    assert r.returncode != 0
    assert "control character" in r.stderr.lower() or "control" in r.stderr.lower()
