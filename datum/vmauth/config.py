from __future__ import annotations

from datum.vmauth.settings import OIDC, PUBLIC_KEY, VmauthSettings

# vmauth reads `vm_access.metrics_extra_labels` off the token and VictoriaMetrics
# applies them over whatever the producer sent, so a spoofed tenant_id loses.
EXTRA_LABELS = "{{.MetricsExtraLabels}}"


def build(settings: VmauthSettings) -> str:
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
