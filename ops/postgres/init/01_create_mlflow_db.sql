-- ClusterOps PostgreSQL bootstrap
-- Runs exactly once, on first initialisation of the postgres_data volume.
-- All application data is 100% synthetic.

-- Dedicated database for the MLflow tracking server (model registry + experiments).
SELECT 'CREATE DATABASE mlflow'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mlflow')\gexec

-- gen_random_uuid() is built into PostgreSQL 13+, but pgcrypto is installed
-- explicitly so the function resolves identically on managed/older images.
CREATE EXTENSION IF NOT EXISTS pgcrypto;