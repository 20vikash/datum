"""The systemd units bootstrap.py writes, and the defaults they are filled with."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8000
DEFAULT_WORKERS = "2"


@dataclass(frozen=True)
class ApiSettings:
    """Where datum-api listens and how many workers serve it."""

    host: str = DEFAULT_API_HOST
    port: int = DEFAULT_API_PORT
    workers: str = DEFAULT_WORKERS


VMAUTH = """[Unit]
Description=vmauth for Datum
After=victoria-metrics.service
Wants=victoria-metrics.service

[Service]
Type=simple
ExecStart={binary} \\
  -auth.config={config} \\
  -httpListenAddr={listen}
StandardOutput=append:{access_log}
StandardError=append:{error_log}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""

VICTORIA_METRICS = """[Unit]
Description=VictoriaMetrics for Datum
After=network.target

[Service]
Type=simple
ExecStart={binary} \\
  -httpListenAddr={listen} \\
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

DATUM_API = """[Unit]
Description=Datum API
After=victoria-metrics.service
Wants=victoria-metrics.service

[Service]
Type=simple
WorkingDirectory={repo}
Environment=DATUM_URL={victoria_url}
{key_environment}ExecStart={uvicorn} datum:create_app --factory \\
  --host {host} --port {port} --workers {workers}
# Uvicorn puts access lines on stdout and everything else on stderr.
StandardOutput=append:{access_log}
StandardError=append:{error_log}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""
