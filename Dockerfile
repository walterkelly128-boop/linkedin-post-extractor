FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Selenium Manager downloads Linux ChromeDriver inside the container.
# The slim Python image needs the runtime libraries required by ChromeDriver.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates \
       curl \
       libasound2 \
       libatk-bridge2.0-0 \
       libatk1.0-0 \
       libatspi2.0-0 \
       libcups2 \
       libdbus-1-3 \
       libdrm2 \
       libexpat1 \
       libfontconfig1 \
       libgbm1 \
       libglib2.0-0 \
       libgtk-3-0 \
       libnspr4 \
       libnss3 \
       libu2f-udev \
       libvulkan1 \
       libx11-6 \
       libx11-xcb1 \
       libxcb1 \
       libxcomposite1 \
       libxdamage1 \
       libxext6 \
       libxfixes3 \
       libxkbcommon0 \
       libxrandr2 \
       libxshmfence1 \
       xdg-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-local.txt .
RUN python -m pip install --no-cache-dir -r requirements-local.txt

COPY local_chrome_server.py .

ENV CHROME_CDP_ADDRESS=host.docker.internal:9222

EXPOSE 8766

CMD ["python", "local_chrome_server.py"]
