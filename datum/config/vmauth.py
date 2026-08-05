from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from string import Template

# Query paths are absent on purpose: a token that can write must not be able to
# read every tenant's series.
WRITE_PATHS = ("/api/v1/write", "/api/v1/import")

PUBLIC_KEY = "public_key"
OIDC = "oidc"
SKIP_VERIFY = "skip_verify"

# Written into datum-api's unit here, read back by `TokenVerifier.from_env`.
PUBLIC_KEY_PATH_VARIABLE = "DATUM_JWT_PUBLIC_KEY_FILE"
OIDC_ISSUER_VARIABLE = "DATUM_OIDC_ISSUER"


# `$` substitution, not str.format: `{{.MetricsExtraLabels}}` is vmauth's own
# placeholder and braces would need doubling to survive.
CONFIG = Template("""# Written by bootstrap.py. Re-run it to change this; edits here are lost.
users:
- jwt:
$verification$match_claims  url_map:
  - src_paths:
$write_paths    url_prefix: "$upstream/?extra_label={{.MetricsExtraLabels}}"
""")

OIDC_KEYS = Template('    oidc:\n      issuer: "$issuer"\n')
KEY_FILE = Template('    public_key_files:\n    - "$path"\n')
NO_VERIFICATION = "    skip_verify: true\n"
MATCH_CLAIMS = Template('    match_claims:\n      scope: "$scope"\n')

# Central signs bench and enrolment tokens with this same key, so without a scope
# any of them could write. Sibling of the key block: vmauth has no match_claims
# inside `oidc`.


@dataclass(frozen=True)
class VmauthSettings:
    """How vmauth verifies producers and where it sends them.

    The key is a path, not its text: vmauth reads the file itself, and Datum
    reads the same one, so the two can never drift apart.
    """

    victoria_url: str
    listen: str = "127.0.0.1:8427"
    public_key_path: Path | None = None
    oidc_issuer: str = ""
    skip_verify: bool = False
    write_paths: tuple[str, ...] = WRITE_PATHS
    scope: str = "datum"

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
    def config(self) -> str:
        """The whole `-auth.config`, from one set of settings."""
        return CONFIG.substitute(
            verification=self._verification,
            match_claims=MATCH_CLAIMS.substitute(scope=self.scope) if self.scope else "",
            write_paths="".join(f'    - "{path}"\n' for path in self.write_paths),
            upstream=self.victoria_url.rstrip("/"),
        )

    @property
    def _verification(self) -> str:
        """The one block that decides whether a signature is checked."""
        if self.mode == OIDC:
            return OIDC_KEYS.substitute(issuer=self.oidc_issuer)
        if self.mode == PUBLIC_KEY:
            return KEY_FILE.substitute(path=self.public_key_path)
        return NO_VERIFICATION

    @property
    def api_environment(self) -> str:
        """The `Environment=` line datum-api needs to verify what vmauth verifies.

        skip_verify has nothing to give it, so reads stay closed while writes
        are open -- deliberate for a local testing mode.
        """
        if self.mode == PUBLIC_KEY:
            return f"Environment={PUBLIC_KEY_PATH_VARIABLE}={self.public_key_path}\n"
        if self.mode == OIDC:
            return f"Environment={OIDC_ISSUER_VARIABLE}={self.oidc_issuer}\n"
        return ""
