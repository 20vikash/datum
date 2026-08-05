from __future__ import annotations

import os
import platform
import subprocess

from datum.config.paths import SYSTEMD


class Systemd:
    """Everything that talks to systemd, kept in one place.

    It is the only part of setup that needs Linux, so a preview or a
    `--config-only` run never touches it.
    """

    @staticmethod
    def require_linux() -> None:
        if platform.system() != "Linux":
            raise RuntimeError("Datum requires a Linux host to run.")

    @staticmethod
    def run(command: list[str], check: bool = True) -> subprocess.CompletedProcess:
        """Run a command, showing its output when it fails."""
        print(f"Running command: {' '.join(command)}")
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode and check:
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
            raise RuntimeError(f"Command {' '.join(command)} failed.")
        return result

    def enable_linger(self) -> None:
        """Without this, user services stop the moment you log out."""
        result = self.run(["loginctl", "enable-linger", os.environ.get("USER", "")], check=False)
        if result.returncode:
            print("Could not enable linger. Run: sudo loginctl enable-linger $USER")

    def link(self, name: str, unit_path) -> bool:
        """Point systemd at the unit. Returns whether the link had to change."""
        SYSTEMD.mkdir(parents=True, exist_ok=True)
        link = SYSTEMD / f"{name}.service"
        if link.is_symlink() and link.readlink() == unit_path:
            return False
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(unit_path)
        return True

    def apply(self, names: list[str], changed: set[str]) -> None:
        """Enable everything; restart only what changed, so a repeat run is a no-op."""
        self.run(["systemctl", "--user", "daemon-reload"])
        for name in names:
            self.run(["systemctl", "--user", "enable", "--now", f"{name}.service"])
            if name in changed:
                self.run(["systemctl", "--user", "restart", f"{name}.service"])
                print(f"Restarted {name}.")
            else:
                print(f"{name} already running with this unit.")
