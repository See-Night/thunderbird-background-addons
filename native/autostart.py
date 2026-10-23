#!/usr/bin/python3
"""Start Thunderbird normally; its early Experiment hook suppresses the window."""
import os
from datetime import datetime
from pathlib import Path


def main():
    directory = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "thunderbird-background"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(directory / "autostart.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.write(descriptor, f"\n{datetime.now().isoformat()} login autostart\n".encode())
    os.dup2(descriptor, 1)
    os.dup2(descriptor, 2)
    if descriptor > 2:
        os.close(descriptor)
    # -silent can trigger shutdown before asynchronous extension startup runs.
    # Keep the normal startup lifecycle and suppress the window in the add-on.
    os.environ["THUNDERBIRD_BACKGROUND_AUTOSTART"] = "1"
    os.execv("/usr/bin/thunderbird", ["/usr/bin/thunderbird"])


if __name__ == "__main__":
    main()
