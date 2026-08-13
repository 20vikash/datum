-- Passwords are substituted by the runner from the env file, which generated them.
-- The user datum-api connects as. It writes; it issues no DDL, because migrations do.
CREATE USER IF NOT EXISTS datum IDENTIFIED BY '${DATUM_PASSWORD}';
REVOKE ALL ON *.* FROM datum;
GRANT SELECT, INSERT ON datum.* TO datum;

-- The user Insights reads with, direct. Datum never uses it.
CREATE USER IF NOT EXISTS insights IDENTIFIED BY '${INSIGHTS_PASSWORD}';
REVOKE ALL ON *.* FROM insights;
GRANT SELECT, CREATE VIEW, DROP VIEW ON datum.* TO insights;
