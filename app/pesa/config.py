"""
config.py -- where each store lives.

Inside the workbench container the stores are reached by their Docker Compose
service names (redis, postgres, mongo, cass1, neo4j ...). The values below are
read from environment variables that docker-compose.yml sets, so every lab
script finds the right host without any editing.
"""
import os

PG_DSN = os.environ.get("PG_DSN", "postgresql://pesa:pesa_lab_password@postgres:5432/pesa")
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://mongo:27017/?replicaSet=rs0")
CASS_HOSTS = [h.strip() for h in os.environ.get("CASS_HOSTS", "cass1").split(",") if h.strip()]
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "pesa-lab-password")
KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092")

# The ./data folder of the lab pack (mounted at /lab/data in the workbench).
DATA_DIR = os.environ.get("PESA_DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data"))
