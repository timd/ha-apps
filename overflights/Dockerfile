FROM python:3.13-alpine
RUN pip install --no-cache-dir "aiohttp>=3.9,<4"
COPY app /app
WORKDIR /app
CMD ["python", "-u", "main.py"]
