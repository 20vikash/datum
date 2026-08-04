from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Everything generated lands here. One directory, so there is one thing to read
# when a service will not start and one thing to back up.
SERVICES = Path.home() / "services"
SYSTEMD = Path.home() / ".config" / "systemd" / "user"

DATA = Path.home() / ".local" / "share" / "datum" / "victoria-metrics"
LOGS = Path.home() / ".local" / "share" / "datum" / "logs"

VMAUTH_CONFIG = "vmauth.yml"
UVICORN = REPO / ".venv" / "bin" / "uvicorn"


def log(name: str) -> Path:
    return LOGS / name
