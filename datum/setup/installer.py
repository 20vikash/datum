from __future__ import annotations

import shutil
from pathlib import Path

from datum.config import units
from datum.config.paths import LOGS, REPO, UVICORN
from datum.config.vmauth import VmauthSettings
from datum.setup.options import Options
from datum.setup.systemd import Systemd

BINARIES = {
    "victoria-metrics": "Install it from https://github.com/VictoriaMetrics/VictoriaMetrics/releases",
    "vmauth": "It ships in the vmutils archive on the VictoriaMetrics releases page.",
}


class Installer:
    """Renders what `datum.config` describes, then puts it on the host.

    Nothing is written until `install` or `write_vmauth_config` is called, so a bad
    key path or an ambiguous verification choice fails while it is still cheap.
    """

    def __init__(self, options: Options, systemd: Systemd | None = None):
        self.options = options
        self.systemd = systemd or Systemd()

    @property
    def vmauth(self) -> VmauthSettings:
        return self.options.vmauth

    def find_binary(self, name: str, required: bool = True) -> str:
        """A preview only prints, so it names the binary rather than refusing
        on a host where nothing is installed yet."""
        found = shutil.which(name)
        if found:
            return found
        if required:
            raise RuntimeError(f"{name} is not on PATH. {BINARIES[name]}")
        return name

    def units(self, required: bool = True) -> dict[str, str]:
        if required and not UVICORN.exists():
            raise RuntimeError(f"{UVICORN} is missing. Run `uv sync --all-groups` in {REPO} first.")

        options, store = self.options, self.options.store
        return {
            "victoria-metrics": units.VICTORIA_METRICS.format(
                binary=self.find_binary("victoria-metrics", required),
                listen=store.listen,
                data=options.data_dir,
                retention=store.retention,
                memory=store.memory_percent,
                hourly=store.hourly_series,
                daily=store.daily_series,
            ),
            "vmauth": units.VMAUTH.format(
                binary=self.find_binary("vmauth", required),
                config=options.vmauth_config,
                listen=self.vmauth.listen,
                access_log=LOGS / "vmauth-access.log",
                error_log=LOGS / "vmauth-error.log",
            ),
            "datum-api": units.DATUM_API.format(
                repo=REPO,
                victoria_url=store.url,
                key_environment=self.vmauth.api_environment,
                uvicorn=UVICORN,
                host=options.datum_host,
                port=options.datum_port,
                workers=options.workers,
                access_log=LOGS / "access.log",
                error_log=LOGS / "error.log",
            ),
        }

    @staticmethod
    def write_once(path: Path, content: str, mode: int = 0o644) -> bool:
        """Write only when the content differs, so a repeat run restarts nothing."""
        path.parent.mkdir(parents=True, exist_ok=True)
        changed = not path.exists() or path.read_text() != content
        if changed:
            path.write_text(content)
        path.chmod(mode)
        return changed

    def preview(self) -> None:
        """Print every file, write none of them."""
        print(f"--- {self.options.vmauth_config} ---\n{self.vmauth.config}")
        for name, unit in self.units(required=False).items():
            print(f"--- {self.options.config_dir / f'{name}.service'} ---\n{unit}")

    def write_vmauth_config(self) -> bool:
        """The auth config on its own. All `--config-only` needs."""
        return self.write_once(self.options.vmauth_config, self.vmauth.config, mode=0o600)

    def install(self) -> None:
        """Write everything, then hand the changed set to systemd."""
        self.systemd.require_linux()
        built = self.units()
        self.options.data_dir.mkdir(parents=True, exist_ok=True)
        # systemd will not create the directory an `append:` path lives in.
        LOGS.mkdir(parents=True, exist_ok=True)

        changed = set()
        for name, unit in built.items():
            path = self.options.config_dir / f"{name}.service"
            written = self.write_once(path, unit)
            linked = self.systemd.link(name, path)
            if written or linked:
                changed.add(name)
            print(f"{'Installed' if written or linked else 'Unchanged'} {name} -> {path}")

        if self.write_vmauth_config():
            changed.add("vmauth")
            print(f"Installed vmauth config ({self.vmauth.mode})")

        self.systemd.enable_linger()
        self.systemd.apply(list(built), changed)

    def report(self) -> None:
        options, vmauth = self.options, self.vmauth
        print(f"\nWrites: vmauth on {vmauth.listen}, verifying by {vmauth.mode}.")
        print(f"Reads:  http://{options.datum_host}:{options.datum_port}")
        print("VictoriaMetrics stays on loopback; nothing reaches it directly.")
        print(f"Logs:   {LOGS}/access.log, error.log, vmauth-*.log")

        if not vmauth.is_verifying:
            print("\nWARNING: skip_verify is on. Signatures are not checked, so anyone")
            print("who reaches the write port can push as any tenant.")
        if not vmauth.api_environment:
            print("\nReads stay closed: datum-api has no key, so every read is a 401.")

    def run(self) -> None:
        """What the command line asked for."""
        if self.options.dry_run:
            self.preview()
            return
        if self.options.config_only:
            self.write_vmauth_config()
            print(f"Wrote {self.options.vmauth_config} ({self.vmauth.mode})")
            return
        self.install()
        self.report()
