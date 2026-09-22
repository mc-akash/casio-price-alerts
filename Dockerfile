FROM python:3.12-slim

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY casio_watch/ ./casio_watch/

# A fresh named volume inherits ownership from the image's directory, so /data must
# already belong to the runtime user or the container cannot write its state file.
RUN mkdir -p /data && chown 10001:10001 /data

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STATE_PATH=/data/state.json \
    HEARTBEAT_PATH=/tmp/heartbeat

USER 10001
CMD ["python3", "-m", "casio_watch", "--loop"]
