FROM python:3.12-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends ffmpeg curl jq ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml /app/pyproject.toml
COPY calewood_qbit_sync /app/calewood_qbit_sync
COPY check_qbit_vs_calewood.sh /app/check_qbit_vs_calewood.sh
COPY check_archiviste.sh /app/check_archiviste.sh

RUN pip install --no-cache-dir .

ENTRYPOINT ["calewood-toolbox"]

