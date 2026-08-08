FROM python:3.11-slim

WORKDIR /app

# System deps for cryptography (if real ecdsa is added later)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        git \
    && rm -rf /var/lib/apt/lists/*

# Copy project
COPY . /app

# Install
RUN pip install --no-cache-dir -e ".[dev]"

# Default: run mock mode
ENV EOH_LEDGER=/data/earn_or_halt.db
ENV EOH_LOG_LEVEL=INFO

VOLUME ["/data"]

ENTRYPOINT ["python", "-m", "earn_or_halt.runtime"]
CMD ["--mock", "--loops", "5"]
