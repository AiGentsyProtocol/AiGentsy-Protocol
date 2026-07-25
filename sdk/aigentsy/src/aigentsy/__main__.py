"""Enable `python -m aigentsy` to dispatch to the CLI.

The `aigentsy` console-script entry point (registered in pyproject.toml)
already calls `aigentsy.cli:main`; this module makes the same dispatch
available via `python -m aigentsy` for environments where the console
script is not on PATH (e.g. a fresh checkout before `pip install`).
"""

from aigentsy.cli import main

if __name__ == "__main__":
    main()
