from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .config import REPO_ROOT


def run_capture(binary: str, args: list[str]) -> tuple[int, str]:
    command = [binary, *args]
    try:
        result = subprocess.run(command, text=True, capture_output=True, cwd=str(REPO_ROOT))
    except OSError as err:
        return 1, f"> {' '.join(command)}\nERROR: {err}"

    text = f"> {' '.join(command)}\n"
    if result.stdout:
        text += result.stdout
    if result.stderr:
        text += "\n[stderr]\n" + result.stderr
    if not result.stdout and not result.stderr:
        text += "(no output)\n"
    return result.returncode, text


def launch_interactive(binary: str, args: list[str]) -> tuple[bool, str]:
    command = [binary, *args]
    try:
        if os.name == "nt":
            subprocess.Popen(command, creationflags=subprocess.CREATE_NEW_CONSOLE, cwd=str(REPO_ROOT))
            return True, f"Launched interactive command in new console: {' '.join(command)}"
        subprocess.Popen(command, cwd=str(REPO_ROOT))
        return True, f"Launched interactive command: {' '.join(command)}"
    except OSError as err:
        return False, f"ERROR launching interactive command: {err}"
