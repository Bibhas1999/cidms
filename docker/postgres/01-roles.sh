#!/bin/sh
# Runs once, when the database volume is first created.
# supreme_app is what the application connects as: it can read and write rows but not change tables, and it
# never bypasses row-level security, so every query only ever sees the current client's rows.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
  CREATE ROLE supreme_app LOGIN PASSWORD '${APP_DB_PASSWORD}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO supreme_app;
  GRANT USAGE ON SCHEMA public TO supreme_app;
  ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO supreme_app;
  ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO supreme_app;
  ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO supreme_app;
  -- A separate database for the automated tests, set up the same way.
  CREATE DATABASE supreme_test OWNER ${POSTGRES_USER};
SQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname supreme_test <<-SQL
  GRANT CONNECT ON DATABASE supreme_test TO supreme_app;
  GRANT USAGE ON SCHEMA public TO supreme_app;
  ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO supreme_app;
  ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO supreme_app;
  ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO supreme_app;
SQL
