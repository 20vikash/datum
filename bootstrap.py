"""Run this script to bootstrap the datum service."""

import os
import platform
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent
SERVICES = Path.home() / "services"
SYSTEMD = Path.home() / ".config" / "systemd" / "user"
DATA = Path.home() / ".local" / "share" / "datum" / "victoria-metrics"
ENV_FILE = SERVICES / "datum.env"

VICTORIA_ADDRESS = "127.0.0.1:8428"
DATUM_ADDRESS = "127.0.0.1"
DATUM_PORT = 8000
RETENTION = "12"
MEMORY_PERCENT = "40"
WORKERS = "2"

# Cardinality limiter. `-1` counts new series and publishes the counters without
# dropping anything, because over the limit VictoriaMetrics discards silently:
# the writer still gets 204 and only vm_hourly_series_limit_rows_dropped_total
# moves. Watch those counters, then set a real number once the normal rate is
# known. See datum_client's README for why series churn is the thing to watch.
HOURLY_SERIES = "-1"
DAILY_SERIES = "-1"

VictoriaMetricsUnit = """[Unit]
Description=VictoriaMetrics for Datum
After=network.target

[Service]
Type=simple
ExecStart={binary} \\
  -httpListenAddr={address} \\
  -storageDataPath={data} \\
  -retentionPeriod={retention} \\
  -memory.allowedPercent={memory} \\
  -storage.maxHourlySeries={hourly} \\
  -storage.maxDailySeries={daily}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""

DatumApiUnit = """[Unit]
Description=Datum API
After=victoria-metrics.service
Wants=victoria-metrics.service

[Service]
Type=simple
WorkingDirectory={repo}
EnvironmentFile={env_file}
ExecStart={uvicorn} datum:create_app --factory \\
  --host {host} --port {port} --workers {workers}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""

def require_linux():
    if platform.system() != "Linux":
        raise RuntimeError("Datum requires a Linux host to run.")


def run_command(command: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a command, showing its output when it fails."""
    print(f"Running command: {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode and check:
        print(f"stdout: {result.stdout}")
        print(f"stderr: {result.stderr}")
        raise RuntimeError(f"Command {' '.join(command)} failed.")
    return result


def find_binary(name: str, hint: str) -> str:
    """Locate a required executable, saying how to get it when it is missing."""
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"{name} is not on PATH. {hint}")
    return found


def install_unit(name: str, unit: str) -> bool:
    """Write the unit under ~/services and link it where systemd --user looks.

    Returns whether anything changed, so an unchanged run restarts nothing.
    """
    SERVICES.mkdir(parents=True, exist_ok=True)
    SYSTEMD.mkdir(parents=True, exist_ok=True)

    path = SERVICES / f"{name}.service"
    changed = not path.exists() or path.read_text() != unit
    if changed:
        path.write_text(unit)

    link = SYSTEMD / f"{name}.service"
    if not link.is_symlink() or link.readlink() != path:
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(path)
        changed = True

    print(f"{'Installed' if changed else 'Unchanged'} {name} -> {path}")
    return changed


def require_env_file() -> None:
    """The env file holds tokens, so it is yours to write. Fail here, not at systemd start."""
    if not ENV_FILE.exists():
        raise RuntimeError(
            f"{ENV_FILE} is missing. Create it with DATUM_URL and DATUM_TOKENS, "
            "then chmod 600 it and run this again."
        )
    if ENV_FILE.stat().st_mode & 0o077:
        raise RuntimeError(f"{ENV_FILE} is readable by others. Run: chmod 600 {ENV_FILE}")


def build_units() -> dict[str, str]:
    victoria = find_binary(
        "victoria-metrics",
        "Install it from https://github.com/VictoriaMetrics/VictoriaMetrics/releases",
    )
    uvicorn = REPO / ".venv" / "bin" / "uvicorn"
    if not uvicorn.exists():
        raise RuntimeError(f"{uvicorn} is missing. Run `uv sync --all-groups` in {REPO} first.")

    return {
        "victoria-metrics": VictoriaMetricsUnit.format(
            binary=victoria,
            address=VICTORIA_ADDRESS,
            data=DATA,
            retention=RETENTION,
            memory=MEMORY_PERCENT,
            hourly=HOURLY_SERIES,
            daily=DAILY_SERIES,
        ),
        "datum-api": DatumApiUnit.format(
            repo=REPO,
            env_file=ENV_FILE,
            uvicorn=uvicorn,
            host=DATUM_ADDRESS,
            port=DATUM_PORT,
            workers=WORKERS,
        ),
    }


def enable_linger() -> None:
    """Without this, user services stop the moment you log out."""
    result = run_command(["loginctl", "enable-linger", os.environ.get("USER", "")], check=False)
    if result.returncode:
        print("Could not enable linger. Run: sudo loginctl enable-linger $USER")


def start(names: list[str], changed: set[str]) -> None:
    """Enable everything; restart only what changed, so a repeat run is a no-op."""
    run_command(["systemctl", "--user", "daemon-reload"])
    for name in names:
        run_command(["systemctl", "--user", "enable", "--now", f"{name}.service"])
        if name in changed:
            run_command(["systemctl", "--user", "restart", f"{name}.service"])
            print(f"Restarted {name}.")
        else:
            print(f"{name} already running with this unit.")


def main() -> None:
    """Bootstrap the datum service."""
    require_linux()
    print("Bootstrapping datum service...")

    SERVICES.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    require_env_file()
    units = build_units()

    changed = {name for name, unit in units.items() if install_unit(name, unit)}

    enable_linger()
    start(list(units), changed)

    print(f"\nDatum is on http://{DATUM_ADDRESS}:{DATUM_PORT}, VictoriaMetrics on loopback only.")
    print(f"After editing {ENV_FILE}: systemctl --user restart datum-api")
    print("Logs: journalctl --user -u datum-api -f")


if __name__ == "__main__":
    main()
