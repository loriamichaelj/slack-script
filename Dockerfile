# One image source for every cloud. Pick the host with --target and the cloud's libraries with
# EXTRAS (gcp, aws, azure, or all):
#
#   docker build --target cli    --build-arg EXTRAS=gcp   .   Cloud Run jobs
#   docker build --target cli    --build-arg EXTRAS=azure .   Azure Container Apps jobs
#   docker build --target lambda --build-arg EXTRAS=aws   .   AWS Lambda
#
# Config and secrets are chosen by the environment at run time (see src/anomaly_alerts/runtime.py).

# ---- Cloud Run and Azure Container Apps: run the command line tool.
FROM python:3.12-slim AS cli

ARG EXTRAS=all
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[${EXTRAS}]"
COPY config/actions.yaml ./config/actions.yaml

# Run as an unprivileged user. Config and secrets come from the host, state from a bucket or blob.
RUN useradd --uid 10001 --no-create-home app
USER app

ENTRYPOINT ["anomaly-alerts"]

# ---- AWS Lambda: the same code behind Lambda's runtime, with the handler as the command.
FROM public.ecr.aws/lambda/python:3.12 AS lambda

ARG EXTRAS=aws
COPY pyproject.toml README.md ${LAMBDA_TASK_ROOT}/
COPY src ${LAMBDA_TASK_ROOT}/src
RUN pip install --no-cache-dir "${LAMBDA_TASK_ROOT}[${EXTRAS}]" && rm -rf "${LAMBDA_TASK_ROOT}/src" "${LAMBDA_TASK_ROOT}/pyproject.toml" "${LAMBDA_TASK_ROOT}/README.md"
COPY config/actions.yaml ${LAMBDA_TASK_ROOT}/config/actions.yaml

CMD ["anomaly_alerts.handler.lambda_handler"]

# The cli stage is last, so a plain `docker build .` still gives the Cloud Run image.
FROM cli
