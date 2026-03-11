"""One-time script to set up the test database user and database."""
import psycopg2

conn = psycopg2.connect(
    host="localhost", port=6432, user="postgres", password="password", dbname="postgres"
)
conn.autocommit = True
cur = conn.cursor()

# Create user if not exists
cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'transportation'")
if not cur.fetchone():
    cur.execute("CREATE USER transportation WITH PASSWORD 'password' CREATEDB")
    print("Created user 'transportation'")
else:
    print("User 'transportation' already exists")

# Create test database if not exists
cur.execute("SELECT 1 FROM pg_database WHERE datname = 'transportation_forms_test'")
if not cur.fetchone():
    cur.execute("CREATE DATABASE transportation_forms_test OWNER transportation")
    print("Created database 'transportation_forms_test'")
else:
    print("Database 'transportation_forms_test' already exists")

# Grant privileges
cur.execute("GRANT ALL PRIVILEGES ON DATABASE transportation_forms TO transportation")
cur.execute("GRANT ALL PRIVILEGES ON DATABASE transportation_forms_test TO transportation")
print("Privileges granted")

cur.close()
conn.close()
print("Done!")
