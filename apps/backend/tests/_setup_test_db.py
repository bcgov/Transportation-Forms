"""One-time script to set up the test database user and database.

Reads connection details from existing environment variables:
    POSTGRES_USER      Superuser name
    POSTGRES_PASSWORD  Superuser password
    PG_HOST            Postgres host          (default: localhost)
    PG_PORT            Postgres port          (default: 5432)
"""
import os
import psycopg2

conn = psycopg2.connect(
    host=os.getenv("PG_HOST", "localhost"),
    port=int(os.getenv("PG_PORT", "5432")),
    user=os.environ["POSTGRES_USER"],
    password=os.environ["POSTGRES_PASSWORD"],
    dbname="postgres",
)
conn.autocommit = True
cur = conn.cursor()

postgres_user = os.environ["POSTGRES_USER"]
postgres_password = os.environ["POSTGRES_PASSWORD"]
postgres_db = os.environ.get("POSTGRES_DB", "transportation_forms")

# Create user if not exists
cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (postgres_user,))
if not cur.fetchone():
    cur.execute(f"CREATE USER {postgres_user} WITH PASSWORD %s CREATEDB", (postgres_password,))
    print(f"Created user '{postgres_user}'")
else:
    print(f"User '{postgres_user}' already exists")

# Create test database if not exists
test_db_name = f"{postgres_db}_test"
cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (test_db_name,))
if not cur.fetchone():
    cur.execute(f"CREATE DATABASE {test_db_name} OWNER {postgres_user}")
    print(f"Created database '{test_db_name}'")
else:
    print(f"Database '{test_db_name}' already exists")

# Grant privileges
cur.execute(f"GRANT ALL PRIVILEGES ON DATABASE {postgres_db} TO {postgres_user}")
cur.execute(f"GRANT ALL PRIVILEGES ON DATABASE {test_db_name} TO {postgres_user}")
print("Privileges granted")

cur.close()
conn.close()
print("Done!")
