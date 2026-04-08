FROM python:3.12-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends curl jq ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml /app/pyproject.toml
COPY calewood_qbit_sync /app/calewood_qbit_sync

RUN pip install --no-cache-dir .

ENTRYPOINT ["calewood-toolbox"]
