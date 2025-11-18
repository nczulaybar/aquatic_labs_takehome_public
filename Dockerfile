# Build stage - install Poetry and dependencies
FROM python:3.12-slim AS builder

WORKDIR /app

# Install Poetry
RUN pip install --no-cache-dir poetry

# Copy dependency files
COPY pyproject.toml poetry.lock* ./

# Install dependencies to a virtual environment
ENV POETRY_VIRTUALENVS_IN_PROJECT=true 
RUN poetry install --only main --no-root

# Uncomment for debugging
# ENTRYPOINT /bin.sh

# Runtime stage - no Poetry
FROM python:3.12-slim

RUN apt-get update && apt-get install -y curl

WORKDIR /app

# Copy installed dependencies
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY server.py .
COPY helpers.py .
COPY timer.py .
COPY data_models.py .

# Expose port 8000 for FastAPI
EXPOSE 8000

# Run using the virtual environment
CMD ["/app/.venv/bin/uvicorn", "server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
