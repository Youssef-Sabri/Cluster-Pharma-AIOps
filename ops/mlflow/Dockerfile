# MLflow tracking server for ClusterOps.
#
# The published `ghcr.io/mlflow/mlflow` image ships without a PostgreSQL driver,
# so the backend store (`--backend-store-uri postgresql://...`) fails to start.
# Installing the pinned psycopg2 build here — rather than running `pip install`
# inside the container command — keeps startup deterministic and offline-safe.
#
# The pinned version matches backend/requirements.txt (psycopg2-binary==2.9.9).
FROM ghcr.io/mlflow/mlflow:v2.14.0

RUN pip install --no-cache-dir "psycopg2-binary==2.9.9"

EXPOSE 5000