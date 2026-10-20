FROM python:3.13-alpine
RUN apk add --no-cache tzdata \
 && pip install --no-cache-dir "aiohttp>=3.9,<4" "aiomqtt>=2,<3"
COPY app /app
WORKDIR /app
# Unhealthy when the receiver has not been read for 2 minutes. The
# Supervisor's watchdog restarts the App when it is unhealthy.
HEALTHCHECK --interval=60s --timeout=10s --start-period=120s \
  CMD wget -qO- http://127.0.0.1:8099/api/health || exit 1
CMD ["python", "-u", "main.py"]
