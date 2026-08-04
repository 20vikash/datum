from __future__ import annotations

from datum.vmauth.settings import VmauthSettings

# vmauth reads `vm_access.metrics_extra_labels` off the token and VictoriaMetrics
# applies them over whatever the producer sent, so a spoofed tenant_id loses.
EXTRA_LABELS = "{{.MetricsExtraLabels}}"


def build(settings: VmauthSettings) -> str:
    """The whole `-auth.config`, from one set of settings."""
    return "".join(
        [
            "# Written by bootstrap.py. Edit the environment, not this file.\n",
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
    if mode == "oidc":
        return f'    oidc:\n      issuer: "{settings.oidc_issuer}"\n'
    if mode == "public_key":
        key = "\n".join(f"      {line}" for line in settings.public_key.strip().splitlines())
        return f"    public_keys:\n    - |\n{key}\n"
    return "    skip_verify: true\n"


def _upstream(settings: VmauthSettings) -> str:
    return f"{settings.victoria_url.rstrip('/')}/?extra_label={EXTRA_LABELS}"
