"""Tests for aigentsy-verify CLI."""

import json
import os
import subprocess
import sys

import pytest

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_BUNDLE = os.path.join(FIXTURE_DIR, "sample_bundle.json")
CLI_MODULE = [sys.executable, "-m", "aigentsy_verify"]


def test_help():
    r = subprocess.run(CLI_MODULE + ["--help"], capture_output=True, text=True)
    assert r.returncode == 0 or r.returncode == 2
    assert "aigentsy-verify" in r.stdout or "aigentsy-verify" in r.stderr


def test_version():
    r = subprocess.run(CLI_MODULE + ["--version"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "aigentsy-verify" in r.stdout


@pytest.mark.skipif(not os.path.exists(SAMPLE_BUNDLE), reason="no sample bundle fixture")
def test_bundle_verify():
    r = subprocess.run(CLI_MODULE + ["bundle", SAMPLE_BUNDLE], capture_output=True, text=True)
    assert "bundle_hash:" in r.stdout
    assert "event_chain:" in r.stdout


@pytest.mark.skipif(not os.path.exists(SAMPLE_BUNDLE), reason="no sample bundle fixture")
def test_bundle_json_output():
    r = subprocess.run(CLI_MODULE + ["bundle", SAMPLE_BUNDLE, "--json"], capture_output=True, text=True)
    result = json.loads(r.stdout)
    assert "verified" in result
    assert "steps" in result
    assert "deal_id" in result


def test_missing_file():
    r = subprocess.run(CLI_MODULE + ["bundle", "nonexistent.json"], capture_output=True, text=True)
    assert r.returncode == 2
    assert "not found" in r.stderr


def test_invalid_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json {{{")
    r = subprocess.run(CLI_MODULE + ["bundle", str(bad)], capture_output=True, text=True)
    assert r.returncode == 2
    assert "invalid JSON" in r.stderr


def test_bare_file_shortcut(tmp_path):
    bundle = {"deal_id": "test", "proofs": [], "events": [], "merkle_inclusion": None, "bundle_hash": "wrong"}
    f = tmp_path / "test.json"
    f.write_text(json.dumps(bundle))
    r = subprocess.run(CLI_MODULE + [str(f)], capture_output=True, text=True)
    assert "bundle_hash:" in r.stdout
