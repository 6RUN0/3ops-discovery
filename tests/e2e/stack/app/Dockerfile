FROM python:3.13-slim@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91

# Single source of tooling is uv: the mini-app installs its one runtime
# dependency with `uv pip` at the same version pinned in the project
# uv.lock, never pip + requirements.txt. The uv binary is copied from
# its own digest-pinned image.
COPY --from=ghcr.io/astral-sh/uv:0.11.29@sha256:eb2843a1e56fd9e30c7276ce1a52cba86e64c7b385f5e3279a0e08e02dd058fc /uv /usr/local/bin/uv

RUN uv pip install --system --no-cache \
    prometheus-client==0.25.0 \
    opentelemetry-sdk==1.44.0 \
    opentelemetry-exporter-otlp==1.44.0

COPY app.py /app/app.py

USER 65534:65534

# -u would be redundant: the app flushes explicitly after every write.
ENTRYPOINT ["python", "/app/app.py"]
