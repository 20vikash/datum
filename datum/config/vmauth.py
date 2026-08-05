from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

WRITE_PATHS = ("/api/v1/write", "/api/v1/import")

READ_PATHS = (
    "/api/v1/query",
    "/api/v1/query_range",
    "/api/v1/series",
    "/api/v1/labels",
    "/api/v1/label/[^/]+/values",
)

PUBLIC_KEY = "public_key"
OIDC = "oidc"
SKIP_VERIFY = "skip_verify"

# Written into datum-api's unit here, read back by `TokenVerifier.from_env`.
PUBLIC_KEY_PATH_VARIABLE = "DATUM_JWT_PUBLIC_KEY_FILE"
OIDC_ISSUER_VARIABLE = "DATUM_OIDC_ISSUER"


HEADER = "# Written by bootstrap.py. Re-run it to change this; edits here are lost.\n"

EXTRA_LABELS = "{{.MetricsExtraLabels}}"
EXTRA_FILTERS = "{{.MetricsExtraFilters}}"


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
    # PromQL straight from a caller, bypassing datum-api. Off by default: it is
    # a second read path, and one is easier to reason about than two.
    direct_reads: bool = False
    read_paths: tuple[str, ...] = READ_PATHS

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
        """The whole `-auth.config`. Serialised rather than templated, so the
        nesting cannot be got wrong by hand."""
        user = {"jwt": self._jwt, "url_map": self._url_maps}
        return HEADER + yaml.safe_dump({"users": [user]}, sort_keys=False)

    @property
    def _url_maps(self) -> list[dict]:
        """Writes first. vmauth takes the first entry whose paths match, and the
        two sets do not overlap, so the order is for the reader."""
        if not self.direct_reads:
            return [self._url_map]
        return [self._url_map, self._read_map]

    @property
    def _jwt(self) -> dict:
        """How a token is checked: its signature, then its claims."""
        # Central signs bench and enrolment tokens with the same key, so without
        # a scope any of them could write.
        claims = {"match_claims": {"scope": self.scope}} if self.scope else {}
        return self._verification | claims

    @property
    def _verification(self) -> dict:
        """The one key that decides whether a signature is checked."""
        if self.mode == OIDC:
            return {"oidc": {"issuer": self.oidc_issuer}}
        if self.mode == PUBLIC_KEY:
            return {"public_key_files": [str(self.public_key_path)]}
        return {"skip_verify": True}

    @property
    def _url_map(self) -> dict:
        upstream = self.victoria_url.rstrip("/")
        return {
            "src_paths": list(self.write_paths),
            "url_prefix": f"{upstream}/?extra_label={EXTRA_LABELS}",
        }

    @property
    def _read_map(self) -> dict:
        """PromQL in, one tenant's series out.

        `extra_filters` is applied by VictoriaMetrics to the selector the caller
        sent, so it narrows and can never widen. Metadata endpoints honour it
        too: a caller listing label values sees only its own.
        """
        upstream = self.victoria_url.rstrip("/")
        return {
            "src_paths": list(self.read_paths),
            "url_prefix": f"{upstream}/?extra_filters={EXTRA_FILTERS}",
        }

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
