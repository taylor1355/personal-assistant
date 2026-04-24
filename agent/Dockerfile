FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install uv for fast dependency resolution.
RUN pip install --no-cache-dir uv

# Copy manifest first for layer caching.
COPY pyproject.toml /app/

# Copy source and install. `uv pip install .` builds the wheel from the
# working tree, registering the `personal-assistant-agent` entrypoint.
COPY src /app/src
RUN uv pip install --system .

ENTRYPOINT ["personal-assistant-agent"]
