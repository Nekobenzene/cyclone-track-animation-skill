"""Paths shared by source and frozen maintenance tools."""
from pathlib import Path
import os
import shutil
import sys

def skill_root():
    return Path(os.environ.get('TYPHOON_SKILL_ROOT') or Path(__file__).resolve().parents[1])

def python_command(explicit=None):
    if explicit:
        return [str(Path(explicit).resolve())]
    if not getattr(sys, 'frozen', False):
        return [sys.executable]
    # A frozen application is not a Python CLI and cannot run `-m pip`.
    for name in ('python', 'py'):
        found = shutil.which(name)
        if found and 'WindowsApps' not in found:
            return [found] + (['-3.12'] if name == 'py' else [])
    raise SystemExit('Building requires an external Windows x64 Python 3.12 with pip; pass --python <python.exe>. Rendering does not require it.')
