FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[gcp]"
COPY config/actions.yaml ./config/actions.yaml

# Run as an unprivileged user. The config and state come from a mounted bucket.
RUN useradd --uid 10001 --no-create-home app
USER app

ENTRYPOINT ["anomaly-alerts"]
