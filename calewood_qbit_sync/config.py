"""
Project configuration.

This repository is intentionally anonymized: no real endpoints or credentials are committed.

Fill values via environment variables or by editing this file locally (do not commit secrets).
"""

from __future__ import annotations

import os


def _env(name: str, default: str) -> str:
    v = os.environ.get(name, default)
    return v if v != "" else default


# qBittorrent defaults
QBIT_REQUIRED_TRACKER_PREFIX = _env("QBIT_REQUIRED_TRACKER_PREFIX", "https://tracker.example/announce")
QBIT_CATEGORY = _env("QBIT_CATEGORY", "cross-seed")
QBIT_SUCCESS_TAG = _env("QBIT_SUCCESS_TAG", "pointé")

# Instances must be configured to use --qb-host.
# Example:
#   export QBIT_INSTANCES_JSON='[{"name":"box","base_url":"http://host:8080","username":"user","password":"pass"}]'
_QBIT_INSTANCES_JSON = os.environ.get("QBIT_INSTANCES_JSON", "").strip()
if _QBIT_INSTANCES_JSON:
    import json

    QBIT_INSTANCES = json.loads(_QBIT_INSTANCES_JSON)
else:
    QBIT_INSTANCES: list[dict[str, str]] = []


# Calewood API
CALEWOOD_BASE_URL = _env("CALEWOOD_BASE_URL", "https://calewood.example")
CALEWOOD_TOKEN = _env("CALEWOOD_TOKEN", "")

# Legacy archives default status
CALEWOOD_REQUIRED_STATUS = _env("CALEWOOD_REQUIRED_STATUS", "uploaded")

