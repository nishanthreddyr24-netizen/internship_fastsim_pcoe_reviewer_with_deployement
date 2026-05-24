"""Import helpers for the repository-bundled FASTSim Python package."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any


def import_fastsim() -> Any | None:
    """Return FASTSim, preferring the local repo package when it is available."""
    try:
        return importlib.import_module("fastsim")
    except ModuleNotFoundError:
        repo_root = Path(__file__).resolve().parents[2]
        python_source = repo_root / "python"
        if not python_source.exists():
            return None
        sys.path.insert(0, str(python_source))
        try:
            return importlib.import_module("fastsim")
        except ModuleNotFoundError:
            return None
