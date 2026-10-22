#!/usr/bin/python3
"""Restore a background window, or start Thunderbird with the supplied arguments."""
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else list(arguments)
    if not arguments:
        host = Path(__file__).resolve().with_name("host.py")
        try:
            result = subprocess.run([str(host), "--show"], check=False, timeout=5)
            if result.returncode == 0:
                return 0
        except (OSError, subprocess.TimeoutExpired):
            pass
    # Preserve mailto URLs, files, -compose and other explicit launch requests.
    thunderbird = shutil.which("thunderbird") or "/usr/bin/thunderbird"
    os.execv(thunderbird, [thunderbird, *arguments])


if __name__ == "__main__":
    sys.exit(main())
