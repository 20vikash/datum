"""Generate the config for datum's services, then install and start them.

Everything this writes lives under one directory. There is no env file: what a
service needs is baked into its unit, and the JWT public key stays a file on
disk that both vmauth and datum-api read.
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from datum.config import units
from datum.config.paths import DATA, LOGS, REPO, SERVICES, SYSTEMD, UVICORN, VMAUTH_CONFIG
from datum.config.units import ApiSettings
from datum.config.victoria import VictoriaSettings
from datum.config.vmauth import VmauthSettings, build_vmauth_config


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bootstrap.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    verification = parser.add_argument_group(
        "verification", "How vmauth checks the JWTs producers send. Pick exactly one."
    )
    verification.add_argument(
        "--public-key",
        type=Path,
        metavar="PATH",
        help="PEM file holding Central's public key. Both services read it.",
    )
    verification.add_argument(
        "--oidc-issuer",
        metavar="URL",
        help="Fetch keys from {issuer}/.well-known/openid-configuration instead.",
    )
    verification.add_argument(
        "--skip-verify",
        action="store_true",
        help="Accept unsigned tokens. Local testing only: anyone can write as anyone.",
    )

    store = VictoriaSettings()
    api = ApiSettings()
    parser.add_argument("--victoria-listen", default=store.listen)
    parser.add_argument("--vmauth-listen", default=VmauthSettings.listen)
    parser.add_argument("--datum-host", default=api.host)
    parser.add_argument("--datum-port", type=int, default=api.port)
    parser.add_argument("--workers", default=api.workers)
    parser.add_argument("--retention", default=store.retention, help="Months the store keeps.")
    parser.add_argument("--memory-percent", default=store.memory_percent)
    parser.add_argument("--config-dir", type=Path, default=SERVICES)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written, touch nothing, start nothing.",
    )
    parser.add_argument(
        "--config-only",
        action="store_true",
        help="Write the vmauth config and print how to run the three processes. "
        "No units, no systemd, so it works anywhere.",
    )
    return parser.parse_args(argv)


def ask_for_verification(arguments: argparse.Namespace) -> None:
    """Fill in the verification choice when no flag gave one."""
    if arguments.public_key or arguments.oidc_issuer or arguments.skip_verify:
        return
    if not sys.stdin.isatty():
        raise RuntimeError(
            "No verification configured. Pass --public-key, --oidc-issuer or --skip-verify."
        )

    print("How should vmauth verify the tokens producers send?")
    print("  1. A public key file  (Central signs, you hold the public half)")
    print("  2. OIDC discovery     (Central serves a JWKS endpoint)")
    print("  3. Skip verification  (local testing; accepts forged tokens)")
    match input("Choose 1, 2 or 3: ").strip():
        case "1":
            arguments.public_key = Path(input("Path to the PEM file: ").strip()).expanduser()
        case "2":
            arguments.oidc_issuer = input("Issuer URL: ").strip()
        case "3":
            arguments.skip_verify = True
        case other:
            raise RuntimeError(f"{other!r} is not one of 1, 2 or 3.")


def build_vmauth_settings(arguments: argparse.Namespace) -> VmauthSettings:
    """Resolve the key path here, so a missing file fails before anything is written."""
    key = arguments.public_key
    if key is not None:
        key = key.expanduser().resolve()
        if not key.is_file():
            raise RuntimeError(f"{key} is not a file. Point --public-key at Central's PEM.")

    settings = VmauthSettings(
        victoria_url=VictoriaSettings(listen=arguments.victoria_listen).url,
        listen=arguments.vmauth_listen,
        public_key_path=key,
        oidc_issuer=arguments.oidc_issuer or "",
        skip_verify=arguments.skip_verify,
    )
    settings.mode  # noqa: B018 -- raises on a missing or ambiguous choice
    return settings


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


def find_binary(name: str, hint: str, required: bool = True) -> str:
    """Locate a required executable, saying how to get it when it is missing.

    A preview only prints, so it names the binary rather than refusing on a
    host where nothing is installed yet.
    """
    found = shutil.which(name)
    if found:
        return found
    if required:
        raise RuntimeError(f"{name} is not on PATH. {hint}")
    return name


def write_once(path: Path, content: str, mode: int = 0o644) -> bool:
    """Write only when the content differs, so a repeat run restarts nothing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    changed = not path.exists() or path.read_text() != content
    if changed:
        path.write_text(content)
    path.chmod(mode)
    return changed


def install_unit(name: str, unit: str, config_dir: Path) -> bool:
    """Write the unit under the config dir and link it where systemd looks."""
    SYSTEMD.mkdir(parents=True, exist_ok=True)
    path = config_dir / f"{name}.service"
    changed = write_once(path, unit)

    link = SYSTEMD / f"{name}.service"
    if not link.is_symlink() or link.readlink() != path:
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(path)
        changed = True

    print(f"{'Installed' if changed else 'Unchanged'} {name} -> {path}")
    return changed


def find_binaries(required: bool = True) -> tuple[str, str]:
    victoria = find_binary(
        "victoria-metrics",
        "Install it from https://github.com/VictoriaMetrics/VictoriaMetrics/releases",
        required,
    )
    vmauth = find_binary(
        "vmauth",
        "It ships in the vmutils archive on the VictoriaMetrics releases page.",
        required,
    )
    if required and not UVICORN.exists():
        raise RuntimeError(f"{UVICORN} is missing. Run `uv sync --all-groups` in {REPO} first.")
    return victoria, vmauth


def store_of(arguments: argparse.Namespace) -> VictoriaSettings:
    return VictoriaSettings(
        listen=arguments.victoria_listen,
        retention=arguments.retention,
        memory_percent=arguments.memory_percent,
    )


def build_units(arguments: argparse.Namespace, settings: VmauthSettings) -> dict[str, str]:
    victoria, vmauth = find_binaries(required=not arguments.dry_run)
    store = store_of(arguments)
    return {
        "victoria-metrics": units.VICTORIA_METRICS.format(
            binary=victoria,
            listen=store.listen,
            data=DATA,
            retention=store.retention,
            memory=store.memory_percent,
            hourly=store.hourly_series,
            daily=store.daily_series,
        ),
        "vmauth": units.VMAUTH.format(
            binary=vmauth,
            config=arguments.config_dir / VMAUTH_CONFIG,
            listen=settings.listen,
            access_log=LOGS / "vmauth-access.log",
            error_log=LOGS / "vmauth-error.log",
        ),
        "datum-api": units.DATUM_API.format(
            repo=REPO,
            victoria_url=store.url,
            key_environment=settings.api_environment,
            uvicorn=UVICORN,
            host=arguments.datum_host,
            port=arguments.datum_port,
            workers=arguments.workers,
            access_log=LOGS / "access.log",
            error_log=LOGS / "error.log",
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


def report(settings: VmauthSettings, arguments: argparse.Namespace) -> None:
    print(f"\nWrites: vmauth on {settings.listen}, verifying by {settings.mode}.")
    print(f"Reads:  http://{arguments.datum_host}:{arguments.datum_port}")
    print("VictoriaMetrics stays on loopback; nothing reaches it directly.")
    print(f"Logs:   {LOGS}/access.log, error.log, vmauth-*.log")

    if not settings.is_verifying:
        print("\nWARNING: skip_verify is on. Signatures are not checked, so anyone")
        print("who reaches the write port can push as any tenant.")
    if not settings.is_verifying:
        print("Reads stay closed: datum-api has no key, so every read is a 401.")


def print_local_commands(arguments: argparse.Namespace, settings: VmauthSettings) -> None:
    """Everything needed to run the three processes by hand, in order."""
    victoria, vmauth = find_binaries(required=False)
    store = store_of(arguments)
    environment = settings.api_environment.replace("Environment=", "").strip()

    print("\nRun these in three terminals:\n")
    print(f"  {victoria} \\\n    -httpListenAddr={store.listen} \\")
    print(f"    -storageDataPath={DATA} -retentionPeriod={store.retention}\n")
    print(f"  {vmauth} \\\n    -auth.config={arguments.config_dir / VMAUTH_CONFIG} \\")
    print(f"    -httpListenAddr={settings.listen}\n")
    print(f"  DATUM_URL={store.url} \\")
    if environment:
        print(f"  {environment} \\")
    print(
        f"    uv run uvicorn datum:create_app --factory "
        f"--host {arguments.datum_host} --port {arguments.datum_port}"
    )
    print(f"\nWrites go to {settings.listen}, reads to {arguments.datum_host}:{arguments.datum_port}.")


def main(argv: list[str] | None = None) -> None:
    arguments = parse_arguments(argv)
    ask_for_verification(arguments)
    settings = build_vmauth_settings(arguments)
    config = build_vmauth_config(settings)

    if arguments.dry_run:
        print(f"--- {arguments.config_dir / VMAUTH_CONFIG} ---\n{config}")
        for name, unit in build_units(arguments, settings).items():
            print(f"--- {arguments.config_dir / f'{name}.service'} ---\n{unit}")
        return

    if arguments.config_only:
        path = arguments.config_dir / VMAUTH_CONFIG
        write_once(path, config, mode=0o600)
        print(f"Wrote {path} ({settings.mode})")
        print_local_commands(arguments, settings)
        return

    require_linux()
    units = build_units(arguments, settings)
    DATA.mkdir(parents=True, exist_ok=True)
    # systemd will not create the directory an `append:` path lives in.
    LOGS.mkdir(parents=True, exist_ok=True)

    changed = {
        name for name, unit in units.items() if install_unit(name, unit, arguments.config_dir)
    }
    if write_once(arguments.config_dir / VMAUTH_CONFIG, config, mode=0o600):
        changed.add("vmauth")
        print(f"Installed vmauth config ({settings.mode})")

    enable_linger()
    start(list(units), changed)
    report(settings, arguments)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as refused:
        # These messages are written for whoever ran the script; a traceback
        # would only bury them.
        print(f"\n{refused}", file=sys.stderr)
        raise SystemExit(1) from None
