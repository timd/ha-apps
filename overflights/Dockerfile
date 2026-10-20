FROM python:3.13-alpine
RUN apk add --no-cache tzdata \
 && pip install --no-cache-dir "aiohttp>=3.9,<4" "aiomqtt>=2,<3"
COPY app /app
WORKDIR /app
CMD ["python", "-u", "main.py"]
