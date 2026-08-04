ARG UV_VERSION=0.11.8
ARG UV_INDEX_URL=https://pypi.org/simple

# Keep the runtime aligned with CI and pin uv for reproducible server builds.
FROM python:3.12-slim

ARG UV_VERSION
ARG UV_INDEX_URL

# Set working directory
WORKDIR /app

# Install a fixed package-manager version. Deployments may override the package
# index at build time when the public registry is slow from their region.
RUN python -m pip install --no-cache-dir --index-url "${UV_INDEX_URL}" "uv==${UV_VERSION}"

RUN groupadd --system --gid 10001 horizon \
    && useradd --system --uid 10001 --gid horizon \
        --home-dir /home/horizon --create-home horizon

# Copy project files
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY data ./data
COPY .env.example .env.example

# Export exact versions from uv.lock, then let pip perform the regional mirror
# downloads. This avoids parallel-download stalls on some domestic networks.
RUN uv export --frozen --no-dev --no-hashes --no-emit-project \
        --format requirements.txt --output-file /tmp/requirements.txt \
    && python -m pip install --no-cache-dir --index-url "${UV_INDEX_URL}" \
        --requirement /tmp/requirements.txt \
    && python -m pip install --no-cache-dir --index-url "${UV_INDEX_URL}" \
        --no-deps . \
    && rm -f /tmp/requirements.txt \
    && chown -R horizon:horizon /app/data /home/horizon

# Create volume mount points
VOLUME ["/app/data"]

# Run the one-shot aggregation job without root privileges.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/horizon

USER horizon

# Run the application
ENTRYPOINT ["horizon"]
CMD []
