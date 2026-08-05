from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from datum.config.paths import DATA, SERVICES, VMAUTH_CONFIG
from datum.config.units import ApiSettings
from datum.config.victoria import VictoriaSettings
from datum.config.vmauth import VmauthSettings

DESCRIPTION = """Generate the config for datum's services, then install and start them.

Everything this writes lives under one directory. There is no env file: what a
service needs is baked into its unit, and the JWT public key stays a file on
disk that both vmauth and datum-api read.
"""


def absolute_path(value: str) -> Path:
    """Resolved at parse time: systemd has no working directory to resolve
    against, and a relative path in the printed commands works from one place."""
    return Path(value).expanduser().resolve()


@dataclass(frozen=True)
class Options:
    """What the caller asked for, already resolved and checked."""

    public_key: Path | None = None
    oidc_issuer: str = ""
    skip_verify: bool = False
    scope: str = VmauthSettings.scope
    victoria_listen: str = VictoriaSettings.listen
    vmauth_listen: str = VmauthSettings.listen
    datum_host: str = ApiSettings.host
    datum_port: int = ApiSettings.port
    workers: str = ApiSettings.workers
    retention: str = VictoriaSettings.retention
    memory_percent: str = VictoriaSettings.memory_percent
    config_dir: Path = SERVICES
    data_dir: Path = DATA
    dry_run: bool = False

    @classmethod
    def from_argv(cls, argv: list[str] | None = None) -> Options:
        return cls(**vars(_parser().parse_args(argv)))

    @property
    def vmauth_config(self) -> Path:
        return self.config_dir / VMAUTH_CONFIG

    @property
    def store(self) -> VictoriaSettings:
        return VictoriaSettings(
            listen=self.victoria_listen,
            retention=self.retention,
            memory_percent=self.memory_percent,
        )

    @property
    def vmauth(self) -> VmauthSettings:
        """Raises on a key that is missing, or a verification choice that is not one."""
        if self.public_key is not None and not self.public_key.is_file():
            raise RuntimeError(
                f"{self.public_key} is not a file. Point --public-key at Central's PEM."
            )
        settings = VmauthSettings(
            victoria_url=self.store.url,
            listen=self.vmauth_listen,
            public_key_path=self.public_key,
            oidc_issuer=self.oidc_issuer,
            skip_verify=self.skip_verify,
            scope=self.scope,
        )
        settings.mode  # noqa: B018 -- raises on a missing or ambiguous choice
        return settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bootstrap.py",
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    default = Options()

    verification = parser.add_argument_group(
        "verification", "How vmauth checks the JWTs producers send. Pick exactly one."
    )
    verification.add_argument(
        "--public-key",
        type=absolute_path,
        metavar="PATH",
        help="PEM file holding Central's public key. Both services read it.",
    )
    verification.add_argument(
        "--oidc-issuer",
        default="",
        metavar="URL",
        help="Fetch keys from {issuer}/.well-known/openid-configuration instead.",
    )
    verification.add_argument(
        "--skip-verify",
        action="store_true",
        help="Accept unsigned tokens. Local testing only: anyone can write as anyone.",
    )
    verification.add_argument(
        "--scope",
        default=default.scope,
        help="Which tokens may write, matched on the JWT's `scope` claim. Central signs "
        "bench and enrolment tokens with the same key, so without this any of them "
        "could push metrics. Empty accepts anything that key signed.",
    )

    parser.add_argument("--victoria-listen", default=default.victoria_listen)
    parser.add_argument("--vmauth-listen", default=default.vmauth_listen)
    parser.add_argument("--datum-host", default=default.datum_host)
    parser.add_argument("--datum-port", type=int, default=default.datum_port)
    parser.add_argument("--workers", default=default.workers)
    parser.add_argument("--retention", default=default.retention, help="Months the store keeps.")
    parser.add_argument("--memory-percent", default=default.memory_percent)
    parser.add_argument("--config-dir", type=absolute_path, default=default.config_dir)
    parser.add_argument(
        "--data-dir",
        type=absolute_path,
        default=default.data_dir,
        help="Where the store keeps data.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written, touch nothing, start nothing.",
    )
    return parser
