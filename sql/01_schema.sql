-- =====================================================================
-- 01_schema.sql -- the Pesa Platform LEDGER (the system of record)
--
-- This runs automatically the first time the PostgreSQL container starts
-- (files in /docker-entrypoint-initdb.d are executed once, in name order,
-- when the data volume is empty).
--
-- Design note for the whole module: the ledger stays in a relational,
-- ACID database. Every other store you meet in these labs holds a copy or a
-- summary of ledger data, shaped for one particular access pattern.
-- =====================================================================

CREATE TABLE customers (
    customer_id        text PRIMARY KEY,
    full_name          text     NOT NULL,
    phone              text     NOT NULL UNIQUE,
    county             text     NOT NULL,
    kyc_level          smallint NOT NULL CHECK (kyc_level BETWEEN 1 AND 3),
    joined_on          date     NOT NULL,
    preferred_language text,                 -- optional: only some customers have it
    marketing_opt_in   boolean              -- optional: only some customers have it
);

CREATE TABLE accounts (
    account_id   text PRIMARY KEY,
    customer_id  text     NOT NULL REFERENCES customers (customer_id),
    account_type text     NOT NULL CHECK (account_type IN ('WALLET', 'BUSINESS')),
    currency     char(3)  NOT NULL,
    balance_kes  bigint   NOT NULL CHECK (balance_kes >= 0)   -- whole shillings
);

CREATE TABLE merchants (
    merchant_id text PRIMARY KEY,
    name        text NOT NULL,
    category    text NOT NULL,
    county      text NOT NULL
);

CREATE TABLE devices (
    device_id  text PRIMARY KEY,
    model      text NOT NULL,
    first_seen date NOT NULL
);

CREATE TABLE account_devices (
    account_id text NOT NULL REFERENCES accounts (account_id),
    device_id  text NOT NULL REFERENCES devices (device_id),
    PRIMARY KEY (account_id, device_id)
);

-- to_id is a merchant id OR an account id, depending on to_kind, so it cannot
-- carry a foreign key. (Polymorphic references are a classic relational
-- compromise; keep it in mind when you see how document stores handle it.)
CREATE TABLE transactions (
    txn_id       text PRIMARY KEY,
    ts           timestamptz NOT NULL,
    from_account text   NOT NULL REFERENCES accounts (account_id),
    to_kind      text   NOT NULL CHECK (to_kind IN ('ACCOUNT', 'MERCHANT')),
    to_id        text   NOT NULL,
    amount_kes   bigint NOT NULL CHECK (amount_kes > 0),
    channel      text   NOT NULL CHECK (channel IN ('app', 'ussd', 'card')),
    device_id    text,                       -- empty for card payments
    status       text   NOT NULL CHECK (status IN ('SETTLED', 'FAILED', 'REVERSED'))
);
CREATE INDEX transactions_from_ts ON transactions (from_account, ts DESC);
CREATE INDEX transactions_to      ON transactions (to_kind, to_id);

CREATE TABLE disputes (
    dispute_id  text PRIMARY KEY,
    txn_id      text        NOT NULL REFERENCES transactions (txn_id),
    customer_id text        NOT NULL REFERENCES customers (customer_id),
    opened_at   timestamptz NOT NULL,
    category    text        NOT NULL,        -- the "right answer" label; used only to check search quality
    description text        NOT NULL
);

-- The transactional OUTBOX (used in the Lab 4 capstone). A payment writes its
-- ledger rows and one outbox row in the SAME transaction; a separate relay
-- process publishes outbox rows to the other stores.
CREATE TABLE outbox (
    id           bigserial PRIMARY KEY,
    aggregate_id text        NOT NULL,       -- e.g. the transaction id
    event_type   text        NOT NULL,       -- e.g. 'PaymentSettled'
    payload      jsonb       NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz                 -- NULL until the relay has published it
);
CREATE INDEX outbox_unpublished ON outbox (id) WHERE published_at IS NULL;
