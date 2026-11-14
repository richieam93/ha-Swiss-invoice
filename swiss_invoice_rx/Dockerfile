# Verwendet ein offizielles multiarch Python-Image (amd64/aarch64).
# Kein BUILD_FROM erforderlich (Home Assistant Supervisor 2026.04+).
FROM python:3.12-slim-bookworm

ARG BUILD_VERSION=2.9.0
ARG BUILD_ARCH=amd64
LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    org.opencontainers.image.title="Swiss-invoice-RX" \
    org.opencontainers.image.description="Schweizer Rechnungssoftware fuer Home Assistant" \
    org.opencontainers.image.source="https://github.com/richieam93/ha-Swiss-invoice"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    SWISS_INVOICE_DATA_DIR=/data \
    SWISS_INVOICE_INGRESS=1

WORKDIR /opt/swiss-invoice-rx
RUN apt-get update && \
    apt-get install --no-install-recommends -y fonts-dejavu-core ca-certificates && \
    rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt && python -m pip check
COPY app/ ./app/
COPY import_backup.py backup_cli.py run.sh ./
RUN chmod 0755 run.sh

EXPOSE 8765
HEALTHCHECK --interval=45s --timeout=8s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=4).read()" || exit 1

CMD ["/opt/swiss-invoice-rx/run.sh"]
