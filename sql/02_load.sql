-- =====================================================================
-- 02_load.sql -- loads the generated CSV files into the ledger.
-- /lab-data is the ./data folder of this lab pack, mounted read-only.
-- Order matters: parents before children (foreign keys).
-- =====================================================================
COPY customers       FROM '/lab-data/customers.csv'       WITH (FORMAT csv, HEADER true);
COPY accounts        FROM '/lab-data/accounts.csv'        WITH (FORMAT csv, HEADER true);
COPY merchants       FROM '/lab-data/merchants.csv'       WITH (FORMAT csv, HEADER true);
COPY devices         FROM '/lab-data/devices.csv'         WITH (FORMAT csv, HEADER true);
COPY account_devices FROM '/lab-data/account_devices.csv' WITH (FORMAT csv, HEADER true);
COPY transactions    FROM '/lab-data/transactions.csv'    WITH (FORMAT csv, HEADER true);
COPY disputes        FROM '/lab-data/disputes.csv'        WITH (FORMAT csv, HEADER true);
ANALYZE;
