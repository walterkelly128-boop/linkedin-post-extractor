# Base official slim Python image
FROM python:3.11-slim

# Prevent python from writing pyc files to disc and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8

WORKDIR /app

# Install runtime dependencies
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    httpx>=0.24.0 \
    pydantic>=2.0.0 \
    rich>=13.0.0 \
    typer>=0.9.0 \
    openpyxl>=3.1.0 \
    python-dotenv>=1.0.0 \
    fastapi>=0.100.0 \
    uvicorn>=0.23.0 \
    jinja2>=3.1.0

# Copy source code, templates and entrypoints
COPY src/ ./src/
COPY templates/ ./templates/
COPY main.py .
COPY web_server.py .

# Create outputs directory
RUN mkdir -p /app/outputs

# Expose Web Console port for Docker Desktop
EXPOSE 8000

# Default: start Web Dashboard directly
CMD ["python", "web_server.py"]
