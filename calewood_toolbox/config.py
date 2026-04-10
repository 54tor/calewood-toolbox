"""
Configuration du projet.

Ce dépôt est volontairement anonymisé : aucun endpoint privé ni identifiant n’est commité.

Tout se configure via variables d’environnement à l’exécution.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    # Charge `.env` si présent (exécution locale). En Docker, privilégier `--env-file`.
    load_dotenv()
except ModuleNotFoundError:  # pragma: no cover
    # Fallback minimal si python-dotenv n'est pas installé (exécution hors venv).
    def _load_dotenv_fallback() -> None:
        candidates = [Path.cwd() / ".env", Path(__file__).resolve().parents[1] / ".env"]
        for p in candidates:
            if not p.is_file():
                continue
            try:
                for raw in p.read_text(encoding="utf-8").splitlines():
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
            except Exception:  # noqa: BLE001
                continue
            break

    _load_dotenv_fallback()


def _env(name: str, default: str) -> str:
    v = os.environ.get(name, default)
    return v if v != "" else default


# qBittorrent defaults
QBIT_REQUIRED_TRACKER_PREFIX = _env("QBIT_REQUIRED_TRACKER_PREFIX", "https://tracker.example/announce")
QBIT_CATEGORY = _env("QBIT_CATEGORY", "cross-seed")
QBIT_SUCCESS_TAG = _env("QBIT_SUCCESS_TAG", "pointé")

# Les instances doivent être configurées pour utiliser --qb-host.
# Exemple :
#   export QBIT_INSTANCES_JSON='[{"name":"box","base_url":"http://host:8080","username":"user","password":"pass"}]'
_QBIT_INSTANCES_JSON = os.environ.get("QBIT_INSTANCES_JSON", "").strip()
if _QBIT_INSTANCES_JSON:
    import json

    QBIT_INSTANCES = json.loads(_QBIT_INSTANCES_JSON)
else:
    QBIT_INSTANCES: list[dict[str, str]] = []


# Calewood API
CALEWOOD_BASE_URL = _env("CALEWOOD_BASE_URL", "https://calewood.n0flow.io/api")
CALEWOOD_TOKEN = _env("CALEWOOD_TOKEN", "")
CALEWOOD_SEEDBOX_PASSPHRASE = _env("CALEWOOD_SEEDBOX_PASSPHRASE", "")

# Legacy archives default status
CALEWOOD_REQUIRED_STATUS = _env("CALEWOOD_REQUIRED_STATUS", "uploaded")
