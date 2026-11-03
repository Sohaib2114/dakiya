import os

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "dakiya")
DB_USER = os.getenv("DB_USER", "dakiya")
# No default: the password comes from the environment at run time (.env, a Kubernetes Secret).
DB_PASSWORD = os.getenv("DB_PASSWORD")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
QUEUE_NAME = "scans"

LOG_FILE = os.getenv("LOG_FILE", "logs/api.log")
