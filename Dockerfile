# syntax=docker/dockerfile:1
FROM python:3.12-slim

LABEL org.opencontainers.image.title="PrivateCinema" \
      org.opencontainers.image.description="Self-hosted film library: federated search, streaming, downloads" \
      org.opencontainers.image.source="https://github.com/qigexiaoqi/PrivateCinema" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PRIVATECINEMA_HOST=0.0.0.0 \
    PRIVATECINEMA_PORT=8426 \
    TZ=Asia/Shanghai

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN mkdir -p /app/data /app/media/assets

VOLUME ["/app/data", "/app/media"]
EXPOSE 8426

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8426/api/health',timeout=3).status==200 else 1)"

CMD ["python", "app.py"]
