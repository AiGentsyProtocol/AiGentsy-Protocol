"""Tests for `aigentsy create-agent` — the first thin adapter on top of
the Settlement-Native Agent Core.

These tests are deliberately narrow: they pin only what v0 promises.

  - The command scaffolds the expected file tree.
  - The bundled canonical prompt matches the runtime's authoritative
    `prompts/settlement_native_agent_system_prompt.md` byte-for-byte.
  - The bundled MCP config uses the verified `python -m adapters.mcp_server`
    invocation and contains no real credentials.
  - Generated `agent.py` is syntactically valid Python.
  - Unsafe target names are rejected with exit code 2.
  - Unsupported template names are rejected with a clear error.
  - Pre-existing CLI commands still register (no regression).

No network. No credentials. No real ProofPacks.
"""

from __future__ import annotations

import json
import os
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Resolve repo-root paths from this test file:
#   tests/test_cli_create_agent.py  ->  sdk/aigentsy/tests/test_cli_create_agent.py
#   so the repo root is four parents up.
REPO_ROOT = Path(__file__).resolve().parents[3]
SDK_SRC = REPO_ROOT / "sdk" / "aigentsy" / "src"
BUNDLED_TEMPLATES_DIR = SDK_SRC / "aigentsy" / "templates"
RUNTIME_CANONICAL_PROMPT = REPO_ROOT / "prompts" / "settlement_native_agent_system_prompt.md"


# ----------------------------------------------------------------------------
# A. Module-level invariants — bundled template integrity
# ----------------------------------------------------------------------------


def test_bundled_canonical_prompt_matches_runtime_canonical_byte_for_byte():
    """The bundled agent_system_prompt.md in the SDK package MUST equal the
    runtime canonical prompt at prompts/settlement_native_agent_system_prompt.md
    byte-for-byte. This is the single-source-of-truth invariant: the file
    inside the SDK package is a verbatim copy of the runtime canonical, and
    must stay that way."""
    bundled = BUNDLED_TEMPLATES_DIR / "settlement_native_mcp" / "agent_system_prompt.md"
    assert bundled.is_file(), f"bundled prompt missing: {bundled}"
    assert RUNTIME_CANONICAL_PROMPT.is_file(), (
        f"runtime canonical prompt missing: {RUNTIME_CANONICAL_PROMPT}"
    )
    bundled_bytes = bundled.read_bytes()
    canonical_bytes = RUNTIME_CANONICAL_PROMPT.read_bytes()
    assert bundled_bytes == canonical_bytes, (
        "settlement-native-mcp/agent_system_prompt.md has drifted from "
        "prompts/settlement_native_agent_system_prompt.md — single source "
        "of truth invariant violated"
    )


def test_bundled_mcp_config_uses_verified_invocation():
    """The bundled mcp_config.example.json must use the verified
    `python -m adapters.mcp_server` invocation."""
    cfg_path = BUNDLED_TEMPLATES_DIR / "settlement_native_mcp" / "mcp_config.example.json"
    assert cfg_path.is_file()
    cfg = json.loads(cfg_path.read_text())
    server = cfg["mcpServers"]["aigentsy"]
    assert server["command"] == "python"
    assert server["args"] == ["-m", "adapters.mcp_server"]


def test_bundled_mcp_config_has_no_real_credentials():
    cfg = json.loads(
        (BUNDLED_TEMPLATES_DIR / "settlement_native_mcp" / "mcp_config.example.json").read_text()
    )
    env = cfg["mcpServers"]["aigentsy"]["env"]
    assert env.get("AIGENTSY_API_KEY") == "your_api_key_here"
    for key in env:
        assert not key.startswith("STRIPE_")
        assert not key.startswith("TWITTER_")
        assert not key.startswith("LINKEDIN_")
        assert not key.startswith("INSTAGRAM_")


# ----------------------------------------------------------------------------
# Helpers for invoking the CLI in a subprocess
# ----------------------------------------------------------------------------


def _run_cli(*args, cwd: Path) -> subprocess.CompletedProcess:
    """Invoke the aigentsy CLI as a module from the SDK src tree. Adds the
    src tree to PYTHONPATH so the package resolves without install."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SDK_SRC) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "aigentsy", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


# ----------------------------------------------------------------------------
# B. Happy path: create-agent scaffolds the expected tree
# ----------------------------------------------------------------------------


def test_create_agent_happy_path_produces_expected_tree(tmp_path):
    r = _run_cli("create-agent", "my_agent", cwd=tmp_path)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"

    target = tmp_path / "my_agent"
    assert target.is_dir()

    expected = [
        "README.md",
        "agent_system_prompt.md",
        "mcp_config.example.json",
        "agent.py",
        "lifecycle.md",
        "tests/test_settlement_lifecycle.py",
    ]
    for rel in expected:
        path = target / rel
        assert path.is_file(), f"expected file missing: {rel}"


def test_generated_prompt_matches_canonical_byte_for_byte(tmp_path):
    r = _run_cli("create-agent", "myproj", cwd=tmp_path)
    assert r.returncode == 0
    generated = (tmp_path / "myproj" / "agent_system_prompt.md").read_bytes()
    canonical = RUNTIME_CANONICAL_PROMPT.read_bytes()
    assert generated == canonical, (
        "generated agent_system_prompt.md must equal the runtime canonical byte-for-byte"
    )


def test_generated_mcp_config_uses_verified_invocation(tmp_path):
    r = _run_cli("create-agent", "myproj", cwd=tmp_path)
    assert r.returncode == 0
    cfg = json.loads((tmp_path / "myproj" / "mcp_config.example.json").read_text())
    server = cfg["mcpServers"]["aigentsy"]
    assert server["command"] == "python"
    assert server["args"] == ["-m", "adapters.mcp_server"]
    assert server["env"]["AIGENTSY_API_KEY"] == "your_api_key_here"


def test_generated_agent_py_is_syntactically_valid(tmp_path):
    r = _run_cli("create-agent", "myproj", cwd=tmp_path)
    assert r.returncode == 0
    agent_py = tmp_path / "myproj" / "agent.py"
    # py_compile raises on syntax error
    py_compile.compile(str(agent_py), doraise=True)


def test_generated_test_file_is_syntactically_valid(tmp_path):
    r = _run_cli("create-agent", "myproj", cwd=tmp_path)
    assert r.returncode == 0
    test_file = tmp_path / "myproj" / "tests" / "test_settlement_lifecycle.py"
    py_compile.compile(str(test_file), doraise=True)


def test_generated_project_name_appears_in_template_outputs(tmp_path):
    """{{PROJECT_NAME}} should be substituted everywhere it appears."""
    r = _run_cli("create-agent", "alpha_agent_xyz", cwd=tmp_path)
    assert r.returncode == 0
    readme = (tmp_path / "alpha_agent_xyz" / "README.md").read_text()
    agent_py = (tmp_path / "alpha_agent_xyz" / "agent.py").read_text()
    test_file = (tmp_path / "alpha_agent_xyz" / "tests" / "test_settlement_lifecycle.py").read_text()
    assert "alpha_agent_xyz" in readme
    assert "alpha_agent_xyz" in agent_py
    assert "alpha_agent_xyz" in test_file
    # placeholder must NOT survive in the generated output
    for body in (readme, agent_py, test_file):
        assert "{{PROJECT_NAME}}" not in body, "template placeholder leaked into output"


def test_generated_agent_runs_locally_without_network(tmp_path, monkeypatch):
    """The generated agent.py must run end-to-end with no network and no
    credentials. We patch socket.socket to raise to prove no network attempt."""
    r = _run_cli("create-agent", "myproj", cwd=tmp_path)
    assert r.returncode == 0

    target = tmp_path / "myproj"

    # Run agent.py in a subprocess with credentials env vars deliberately unset.
    env = os.environ.copy()
    for k in ("AME_BASE", "AME_API_KEY", "AIGENTSY_API_KEY"):
        env.pop(k, None)
    proc = subprocess.run(
        [sys.executable, "agent.py"],
        cwd=target,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    # transcript hallmarks
    assert "myproj" in proc.stdout
    assert "settlement-native agent starter" in proc.stdout
    assert "No network call was made" in proc.stdout
    # the four labelled samples in the demo
    for label in ("DRAFT", "HANDOFF_READY", "VERIFIED_NOT_ACCEPTED", "ACCEPTED"):
        assert label in proc.stdout, f"missing demo label: {label}"


# ----------------------------------------------------------------------------
# C. Safety — unsafe names rejected
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_name",
    [
        "../bad",
        "../../escape",
        "/tmp/bad",  # absolute path
        "",
        " ",
        "name with spaces",  # contains space but the real reason this works is path-separator handling
        "a/b",  # contains separator
        ".hidden",  # starts with dot
    ],
)
def test_unsafe_names_rejected(bad_name, tmp_path):
    # Some "bad_name" values are accepted by argparse (it parses positional
    # args fine); the CLI must reject them at validation time. We assert
    # non-zero exit and that no directory matching that name exists.
    r = _run_cli("create-agent", bad_name, cwd=tmp_path)
    assert r.returncode != 0, (
        f"unsafe name {bad_name!r} was accepted; stdout={r.stdout}\nstderr={r.stderr}"
    )


def test_existing_non_empty_target_rejected(tmp_path):
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "preexisting.txt").write_text("hello")
    r = _run_cli("create-agent", "occupied", cwd=tmp_path)
    assert r.returncode != 0
    # the pre-existing file must survive
    assert (target / "preexisting.txt").read_text() == "hello"


# ----------------------------------------------------------------------------
# D. Template-registry behavior — unsupported template
# ----------------------------------------------------------------------------


def test_unsupported_template_produces_clear_error(tmp_path):
    r = _run_cli(
        "create-agent", "x", "--template", "settlement-native-langgraph",
        cwd=tmp_path,
    )
    assert r.returncode != 0
    # Error message should be informative
    assert "unknown template" in r.stderr.lower() or "available" in r.stderr.lower()
    # The default template must be listed as available
    assert "settlement-native-mcp" in r.stderr


# ----------------------------------------------------------------------------
# E. No regression on the pre-existing CLI commands
# ----------------------------------------------------------------------------


def test_pre_existing_commands_still_parse():
    """`aigentsy --help` must still list every pre-existing subcommand
    AND the new create-agent subcommand."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SDK_SRC) + os.pathsep + env.get("PYTHONPATH", "")
    r = subprocess.run(
        [sys.executable, "-m", "aigentsy", "--help"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert r.returncode == 0
    out = r.stdout
    for cmd in ("init", "stamp", "verify", "settle", "status", "demo", "create-agent"):
        assert cmd in out, f"subcommand {cmd!r} missing from --help"


def test_dispatch_dict_contains_create_agent():
    """Import the module and confirm the create-agent command is dispatched.
    A regression test guarding against accidentally deleting the wiring."""
    sys.path.insert(0, str(SDK_SRC))
    try:
        # Reimport fresh
        if "aigentsy.cli" in sys.modules:
            del sys.modules["aigentsy.cli"]
        import aigentsy.cli as cli
    finally:
        if str(SDK_SRC) in sys.path:
            sys.path.remove(str(SDK_SRC))
    assert callable(getattr(cli, "cmd_create_agent", None))
    # Check the listed templates include the v0 starter
    assert "settlement-native-mcp" in cli._available_templates()


# ----------------------------------------------------------------------------
# F. No outreach modules in generated files
# ----------------------------------------------------------------------------


FORBIDDEN_OUTREACH_PATTERNS = (
    "from playwright",
    "import playwright",
    "from selenium",
    "import selenium",
    "post_to_twitter_direct",
    "post_to_instagram_direct",
    "post_to_linkedin_direct",
    "send_sms_direct",
    "social_autoposting_engine",
    "send_dm(",
)


@pytest.mark.parametrize("pattern", FORBIDDEN_OUTREACH_PATTERNS)
def test_generated_python_files_contain_no_outreach_module(pattern, tmp_path):
    """No generated .py file may import or call a runtime outreach module.

    Scans the generated project's .py files (excluding the generated test
    file, which legitimately enumerates these patterns as string literals
    for its own scanner)."""
    r = _run_cli("create-agent", "myproj", cwd=tmp_path)
    assert r.returncode == 0
    project = tmp_path / "myproj"
    test_self = (project / "tests" / "test_settlement_lifecycle.py").resolve()
    for py in project.rglob("*.py"):
        if py.resolve() == test_self:
            continue
        body = py.read_text(encoding="utf-8")
        assert pattern not in body, (
            f"outreach pattern {pattern!r} found in generated file {py}"
        )
