CREATE TABLE IF NOT EXISTS sharepatch_schema_migrations (
    version TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS sharepatch_state (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    active BOOLEAN NOT NULL DEFAULT FALSE,
    current_cycle_id BIGINT,
    activated_at TIMESTAMPTZ,
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai'
);
INSERT INTO sharepatch_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS sharepatch_cycles (
    id BIGSERIAL PRIMARY KEY,
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ,
    amount_cents BIGINT NOT NULL CHECK (amount_cents >= 0),
    status TEXT NOT NULL CHECK (status IN ('current', 'settled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    settled_at TIMESTAMPTZ,
    CHECK (ends_at IS NULL OR ends_at > starts_at)
);
CREATE UNIQUE INDEX IF NOT EXISTS sharepatch_one_current_cycle
    ON sharepatch_cycles ((status)) WHERE status = 'current';

CREATE TABLE IF NOT EXISTS sharepatch_boundaries (
    cycle_id BIGINT NOT NULL,
    boundary TEXT NOT NULL CHECK (boundary IN ('start', 'end')),
    user_id BIGINT NOT NULL,
    email_snapshot TEXT NOT NULL,
    status_snapshot TEXT NOT NULL,
    created_at_snapshot TIMESTAMPTZ NOT NULL,
    balance NUMERIC(20,8) NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (cycle_id, boundary, user_id)
);

CREATE TABLE IF NOT EXISTS sharepatch_lines (
    cycle_id BIGINT NOT NULL REFERENCES sharepatch_cycles(id),
    user_id BIGINT NOT NULL,
    email_snapshot TEXT NOT NULL,
    usd_usage NUMERIC(20,8) NOT NULL CHECK (usd_usage >= 0),
    share_ratio NUMERIC(38,20) NOT NULL CHECK (share_ratio >= 0),
    amount_cents BIGINT NOT NULL CHECK (amount_cents >= 0),
    PRIMARY KEY (cycle_id, user_id)
);

CREATE TABLE IF NOT EXISTS sharepatch_settlement_keys (
    idempotency_key TEXT PRIMARY KEY,
    cycle_id BIGINT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'complete')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    completed_at TIMESTAMPTZ
);

CREATE OR REPLACE FUNCTION sharepatch_guard_user_balance() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_active BOOLEAN;
    v_start_balance NUMERIC(20,8);
BEGIN
    SELECT active INTO v_active FROM sharepatch_state WHERE id = 1;

    IF TG_OP = 'INSERT' THEN
        IF COALESCE(v_active, FALSE) THEN
            -- New accounts begin at the shared meter's fixed initial reading.
            NEW.balance := 10000000.00000000;
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.balance IS DISTINCT FROM OLD.balance THEN
        IF current_setting('sharepatch.initializing', TRUE) = 'on' THEN
            RETURN NEW;
        END IF;
        IF NOT COALESCE(v_active, FALSE) THEN
            RAISE EXCEPTION 'sharepatch is pending activation; balance changes are disabled'
                USING ERRCODE = '55000';
        END IF;
        IF current_setting('sharepatch.billing', TRUE) = 'on'
           AND NEW.balance < OLD.balance THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'sharepatch permits only metered billing deductions'
            USING ERRCODE = '55000';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS sharepatch_users_balance_guard ON users;
CREATE TRIGGER sharepatch_users_balance_guard
    BEFORE INSERT OR UPDATE OF balance ON users
    FOR EACH ROW EXECUTE FUNCTION sharepatch_guard_user_balance();

CREATE OR REPLACE FUNCTION sharepatch_guard_user_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_active BOOLEAN;
    v_cycle_id BIGINT;
    v_start_balance NUMERIC(20,8);
BEGIN
    IF OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL THEN
        SELECT active, current_cycle_id INTO v_active, v_cycle_id
        FROM sharepatch_state WHERE id = 1;
        IF COALESCE(v_active, FALSE) THEN
            SELECT balance INTO v_start_balance
            FROM sharepatch_boundaries
            WHERE cycle_id = v_cycle_id AND boundary = 'start' AND user_id = OLD.id;
            IF OLD.balance < COALESCE(v_start_balance, 10000000.00000000) THEN
                RAISE EXCEPTION 'user has current-cycle usage; disable the account instead of deleting it'
                    USING ERRCODE = '55000';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS sharepatch_users_delete_guard ON users;
CREATE TRIGGER sharepatch_users_delete_guard
    BEFORE UPDATE OF deleted_at ON users
    FOR EACH ROW EXECUTE FUNCTION sharepatch_guard_user_delete();
