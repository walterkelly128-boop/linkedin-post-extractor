FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements-local.txt .
RUN python -m pip install --no-cache-dir -r requirements-local.txt

COPY local_chrome_server.py .

ENV CHROME_CDP_ADDRESS=host.docker.internal:9222

EXPOSE 8766

CMD ["python", "local_chrome_server.py"]
