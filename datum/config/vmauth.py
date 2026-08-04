from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_LISTEN = "127.0.0.1:8427"

# What a producer may reach. Query paths are deliberately absent: a token that
# can write must not be able to read every tenant's series.
WRITE_PATHS = ("/api/v1/write", "/api/v1/import")

PUBLIC_KEY = "public_key"
OIDC = "oidc"
SKIP_VERIFY = "skip_verify"

# What datum-api reads to verify the same tokens vmauth does. Named here so one
# mode decides both sides at once.
PUBLIC_KEY_FILE_VARIABLE = "DATUM_JWT_PUBLIC_KEY_FILE"
ISSUER_VARIABLE = "DATUM_OIDC_ISSUER"


@dataclass(frozen=True)
class VmauthSettings:
    """How vmauth verifies producers and where it sends them.

    The key is a path, not its text: vmauth reads the file itself, and Datum
    reads the same one, so the two can never drift apart.
    """

    victoria_url: str
    listen: str = DEFAULT_LISTEN
    public_key_path: Path | None = None
    oidc_issuer: str = ""
    skip_verify: bool = False
    write_paths: tuple[str, ...] = WRITE_PATHS

    @property
    def mode(self) -> str:
        """Which verification vmauth will do. Raises rather than guessing."""
        chosen = [
            name
            for name, picked in (
                (OIDC, bool(self.oidc_issuer)),
                (PUBLIC_KEY, self.public_key_path is not None),
                (SKIP_VERIFY, self.skip_verify),
            )
            if picked
        ]
        if not chosen:
            raise RuntimeError(
                "No JWT verification configured. Pass --public-key, --oidc-issuer, "
                "or --skip-verify for local testing."
            )
        if len(chosen) > 1:
            raise RuntimeError(
                f"{' and '.join(chosen)} are both set, and vmauth accepts one. "
                "Drop the one you are migrating away from."
            )
        return chosen[0]

    @property
    def is_verifying(self) -> bool:
        """False only when signatures are not checked at all."""
        return self.mode != SKIP_VERIFY

    @property
    def api_environment(self) -> str:
        """The `Environment=` line datum-api needs to verify what vmauth verifies.

        skip_verify has nothing to give it, so reads stay closed while writes
        are open -- deliberate for a local testing mode.
        """
        if self.mode == PUBLIC_KEY:
            return f"Environment={PUBLIC_KEY_FILE_VARIABLE}={self.public_key_path}\n"
        if self.mode == OIDC:
            return f"Environment={ISSUER_VARIABLE}={self.oidc_issuer}\n"
        return ""


# vmauth reads `vm_access.metrics_extra_labels` off the token and VictoriaMetrics
# applies them over whatever the producer sent, so a spoofed tenant_id loses.
EXTRA_LABELS = "{{.MetricsExtraLabels}}"


def build_vmauth_config(settings: VmauthSettings) -> str:
    """The whole `-auth.config`, from one set of settings."""
    return "".join(
        [
            "# Written by bootstrap.py. Re-run it to change this; edits here are lost.\n",
            "users:\n",
            "- jwt:\n",
            _verification(settings),
            "  url_map:\n",
            "  - src_paths:\n",
            *(f'    - "{path}"\n' for path in settings.write_paths),
            f'    url_prefix: "{_upstream(settings)}"\n',
        ]
    )


def _verification(settings: VmauthSettings) -> str:
    """The one block that decides whether a signature is checked."""
    mode = settings.mode
    if mode == OIDC:
        return f'    oidc:\n      issuer: "{settings.oidc_issuer}"\n'
    if mode == PUBLIC_KEY:
        return f'    public_key_files:\n    - "{settings.public_key_path}"\n'
    return "    skip_verify: true\n"


def _upstream(settings: VmauthSettings) -> str:
    return f"{settings.victoria_url.rstrip('/')}/?extra_label={EXTRA_LABELS}"
