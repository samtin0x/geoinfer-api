FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies required for the app
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Install uv for fast Python package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Create app directory and set permissions
WORKDIR /app

# Create non-root user early for security
RUN groupadd --gid 1000 app && \
    useradd --uid 1000 --gid app --shell /bin/bash --create-home app

# Create logs directory
RUN mkdir -p /app/logs && chown -R app:app /app
USER app

# Copy dependency files first for better Docker layer caching
COPY --chown=app:app pyproject.toml uv.lock* ./

# Install dependencies (production only by default)
ARG INSTALL_DEV=false
RUN if [ "$INSTALL_DEV" = "true" ]; then \
        uv sync --locked; \
    else \
        uv sync --locked --no-dev --no-cache; \
    fi && \
    # Clean up any cache directories to reduce image size
    find /home/app/.cache -type f -delete 2>/dev/null || true && \
    uv cache clean

# Copy application source code
COPY --chown=app:app . .

# Expose the application port
EXPOSE 8010

# Production command with better performance settings
CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "1", "--loop", "uvloop", "--http", "httptools"]