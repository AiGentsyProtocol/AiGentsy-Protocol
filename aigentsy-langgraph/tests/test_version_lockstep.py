"""Version lockstep — the G2-deploy lesson: __version__ string and
pyproject must agree, otherwise upgrade detection is broken."""
from __future__ import annotations

import re
from pathlib import Path

import aigentsy_langgraph


def test_version_string_and_pyproject_agree():
    """__version__ in __init__.py must match pyproject.toml's
    [project].version. Drift here is the bug that hit the rich SDK in
    its 1.8.0 release and that the rigid prompt explicitly calls out."""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    text = pyproject.read_text()
    m = re.search(r'version\s*=\s*"([^"]+)"', text)
    assert m, "pyproject.toml has no version line"
    pyproject_version = m.group(1)
    assert aigentsy_langgraph.__version__ == pyproject_version, (
        f"version drift: __version__={aigentsy_langgraph.__version__!r} "
        f"but pyproject.toml has {pyproject_version!r}"
    )


def test_version_is_040():
    assert aigentsy_langgraph.__version__ == "0.4.0"
