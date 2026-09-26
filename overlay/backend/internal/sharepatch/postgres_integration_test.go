//go:build integration

package sharepatch

import (
	"context"
	"database/sql"
	"fmt"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"

	_ "github.com/lib/pq"
)

func TestPostgresLifecycleAndGuards(t *testing.T) {
	dsn := os.Getenv("SHAREPATCH_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("SHAREPATCH_TEST_DATABASE_URL is not set")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	adminDB, err := sql.Open("postgres", dsn)
	if err != nil {
		t.Fatal(err)
	}
	adminDB.SetMaxOpenConns(1)
	if err := adminDB.PingContext(ctx); err != nil {
		t.Fatal(err)
	}

	schema := fmt.Sprintf("sharepatch_it_%d", time.Now().UnixNano())
	if _, err := adminDB.ExecContext(ctx, "CREATE SCHEMA "+schema); err != nil {
		t.Fatal(err)
	}
	serviceDB, err := sql.Open("postgres", dsnWithSearchPath(dsn, schema))
	if err != nil {
		t.Fatal(err)
	}
	serviceDB.SetMaxOpenConns(5)
	serviceDB.SetMaxIdleConns(5)
	t.Cleanup(func() {
		_ = serviceDB.Close()
		_, _ = adminDB.ExecContext(context.Background(), "DROP SCHEMA "+schema+" CASCADE")
		_ = adminDB.Close()
	})
	if err := serviceDB.PingContext(ctx); err != nil {
		t.Fatal(err)
	}
	db := serviceDB
	fixture := []string{
		`CREATE TABLE users (
		id BIGSERIAL PRIMARY KEY, email TEXT NOT NULL, status TEXT NOT NULL,
			created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), deleted_at TIMESTAMPTZ,
			balance NUMERIC(20,8) NOT NULL DEFAULT 0, frozen_balance NUMERIC(20,8) NOT NULL DEFAULT 0
		)`,
		`CREATE TABLE usage_logs (
			id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, billing_type SMALLINT NOT NULL,
			actual_cost NUMERIC(20,10) NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
		)`,
		`CREATE INDEX usage_logs_created_at_idx ON usage_logs (created_at)`,
		`CREATE INDEX usage_logs_user_created_idx ON usage_logs (user_id, created_at)`,
		`CREATE TABLE user_subscriptions (
			id BIGSERIAL PRIMARY KEY, status TEXT NOT NULL, starts_at TIMESTAMPTZ NOT NULL,
			expires_at TIMESTAMPTZ NOT NULL
		)`,
		`CREATE TABLE batch_image_jobs (
			id BIGSERIAL PRIMARY KEY, status TEXT NOT NULL, settled_at TIMESTAMPTZ
		)`,
		`CREATE TABLE usage_cleanup_tasks (
			id BIGSERIAL PRIMARY KEY, status TEXT NOT NULL
		)`,
	}
	for _, statement := range fixture {
		if _, err := db.ExecContext(ctx, statement); err != nil {
			t.Fatal(err)
		}
	}
	var firstUser, disabledUser, removableUser int64
	for _, user := range []struct {
		email string
		id    *int64
	}{{"first@example.test", &firstUser}, {"disabled@example.test", &disabledUser}, {"removable@example.test", &removableUser}} {
		if err := db.QueryRowContext(ctx, `
			INSERT INTO users (email, status, balance) VALUES ($1, 'active', 7) RETURNING id
		`, user.email).Scan(user.id); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := db.ExecContext(ctx, `
		INSERT INTO usage_logs (user_id, billing_type, actual_cost, created_at)
		VALUES ($1, 0, 0.125000005, clock_timestamp())
	`, firstUser); err != nil {
		t.Fatal(err)
	}

	store, err := NewStore(ctx, db)
	if err != nil {
		t.Fatal(err)
	}
	simpleModeHandler, err := NewHandler(db, "simple")
	if err != nil {
		t.Fatal(err)
	}
	if simpleModeHandler.standardBilling {
		t.Fatal("simple mode was accepted as standard billing")
	}
	if !UnifiedBillingRequired() {
		t.Fatal("installing the sharepatch schema did not require unified billing")
	}
	if err := store.Migrate(ctx); err != nil {
		t.Fatalf("second migration run: %v", err)
	}
	var migrationCount int
	if err := db.QueryRowContext(ctx, `SELECT COUNT(*) FROM sharepatch_schema_migrations`).Scan(&migrationCount); err != nil {
		t.Fatal(err)
	}
	if migrationCount != 1 {
		t.Fatalf("migration rows = %d, want exactly one", migrationCount)
	}
	startsAt := time.Now().UTC().Add(-time.Hour)
	if _, err := db.ExecContext(ctx, `INSERT INTO usage_cleanup_tasks (status) VALUES ('pending')`); err != nil {
		t.Fatal(err)
	}
	blockedPreview, err := store.PreviewActivation(ctx, startsAt, 1)
	if err != nil {
		t.Fatal(err)
	}
	if !hasBlocker(blockedPreview.Blockers, "usage_cleanup_running") {
		t.Fatalf("pending cleanup task did not block activation: %#v", blockedPreview.Blockers)
	}
	if _, err := db.ExecContext(ctx, `DELETE FROM usage_cleanup_tasks`); err != nil {
		t.Fatal(err)
	}
	if _, err := db.ExecContext(ctx, `UPDATE users SET balance = balance + 1 WHERE id = $1`, disabledUser); err == nil {
		t.Fatal("pending activation allowed a balance mutation")
	}
	preview, err := store.PreviewActivation(ctx, startsAt, 1)
	if err != nil {
		t.Fatal(err)
	}
	if len(preview.Users) != 3 || preview.Users[0].USDUsage != "0.12500001" {
		t.Fatalf("unexpected backfill preview: %#v", preview.Users)
	}
	if _, err := store.Activate(ctx, startsAt, 1, true); err != nil {
		t.Fatal(err)
	}
	if _, err := store.Activate(ctx, startsAt, 1, true); err == nil {
		t.Fatal("repeat activation unexpectedly succeeded")
	}
	var balance string
	if err := db.QueryRowContext(ctx, `SELECT balance::text FROM users WHERE id = $1`, firstUser).Scan(&balance); err != nil {
		t.Fatal(err)
	}
	if balance != "9999999.87499999" {
		t.Fatalf("backfilled balance = %s", balance)
	}
	if _, err := db.ExecContext(ctx, `UPDATE users SET balance = balance + 1 WHERE id = $1`, disabledUser); err == nil {
		t.Fatal("active billing allowed a balance increase")
	}
	if _, err := db.ExecContext(ctx, `UPDATE users SET balance = balance - 1 WHERE id = $1`, disabledUser); err == nil {
		t.Fatal("active billing allowed an unmarked balance decrease")
	}
	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := tx.ExecContext(ctx, `SELECT set_config('sharepatch.billing', 'on', TRUE)`); err != nil {
		_ = tx.Rollback()
		t.Fatal(err)
	}
	if _, err := tx.ExecContext(ctx, `UPDATE users SET balance = balance - 0.00000001 WHERE id = $1`, firstUser); err != nil {
		_ = tx.Rollback()
		t.Fatal(err)
	}
	if err := tx.Commit(); err != nil {
		t.Fatal(err)
	}
	if _, err := db.ExecContext(ctx, `UPDATE users SET deleted_at = clock_timestamp() WHERE id = $1`, firstUser); err == nil {
		t.Fatal("a user with current-cycle usage was soft-deleted")
	}
	if _, err := db.ExecContext(ctx, `UPDATE users SET status = 'disabled' WHERE id = $1`, disabledUser); err != nil {
		t.Fatal(err)
	}
	if _, err := db.ExecContext(ctx, `UPDATE users SET deleted_at = clock_timestamp() WHERE id = $1`, removableUser); err != nil {
		t.Fatalf("an unused user could not be deleted: %v", err)
	}
	var createdUser int64
	if err := db.QueryRowContext(ctx, `
		INSERT INTO users (email, status, balance) VALUES ('new@example.test', 'active', 7) RETURNING id
	`).Scan(&createdUser); err != nil {
		t.Fatal(err)
	}
	if err := db.QueryRowContext(ctx, `SELECT balance::text FROM users WHERE id = $1`, createdUser).Scan(&balance); err != nil {
		t.Fatal(err)
	}
	if balance != meterStart {
		t.Fatalf("new user meter = %s, want %s", balance, meterStart)
	}
	if _, err := db.ExecContext(ctx, `UPDATE users SET deleted_at = clock_timestamp() WHERE id = $1`, createdUser); err != nil {
		t.Fatal(err)
	}

	// Keep a real metered deduction uncommitted while settlement requests wait
	// for the users SHARE lock. A duplicate key must wait for the first commit
	// and then return that same immutable bill.
	billingTx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := billingTx.ExecContext(ctx, `SELECT set_config('sharepatch.billing', 'on', TRUE)`); err != nil {
		_ = billingTx.Rollback()
		t.Fatal(err)
	}
	if _, err := billingTx.ExecContext(ctx, `UPDATE users SET balance = balance - 0.5 WHERE id = $1`, firstUser); err != nil {
		_ = billingTx.Rollback()
		t.Fatal(err)
	}
	type settlementResult struct {
		ledger *PeriodLedger
		err    error
	}
	results := make(chan settlementResult, 2)
	go func() {
		ledger, err := store.Settle(ctx, "cycle-one")
		results <- settlementResult{ledger: ledger, err: err}
	}()
	time.Sleep(50 * time.Millisecond)
	go func() {
		ledger, err := store.Settle(ctx, "cycle-one")
		results <- settlementResult{ledger: ledger, err: err}
	}()
	time.Sleep(50 * time.Millisecond)
	if err := billingTx.Commit(); err != nil {
		t.Fatal(err)
	}
	firstResult := <-results
	secondResult := <-results
	if firstResult.err != nil || secondResult.err != nil {
		t.Fatalf("concurrent settlement errors: first=%v second=%v", firstResult.err, secondResult.err)
	}
	firstBill := firstResult.ledger
	if secondResult.ledger.Cycle.ID != firstBill.Cycle.ID {
		t.Fatalf("concurrent idempotent retry returned cycle %d, want %d", secondResult.ledger.Cycle.ID, firstBill.Cycle.ID)
	}
	if len(firstBill.Lines) != 2 || firstBill.Lines[0].AmountCNY != "0.01" || firstBill.Lines[1].AmountCNY != "0.00" {
		t.Fatalf("usage-based bill = %#v", firstBill.Lines)
	}
	if firstBill.Lines[0].USDUsage != "0.62500002" {
		t.Fatalf("settlement missed a deduction serialized at the boundary: %s", firstBill.Lines[0].USDUsage)
	}
	if _, err := db.ExecContext(ctx, `UPDATE users SET email = 'renamed@example.test' WHERE id = $1`, firstUser); err != nil {
		t.Fatal(err)
	}
	dashboard, err := store.Dashboard(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if len(dashboard.History) == 0 || dashboard.History[0].Lines[0].Email != "first@example.test" {
		t.Fatalf("historical bill did not preserve the email snapshot: %#v", dashboard.History)
	}
	if _, err := store.SetCurrentAmount(ctx, 5); err != nil {
		t.Fatal(err)
	}
	zeroUsageBill, err := store.Settle(ctx, "cycle-two")
	if err != nil {
		t.Fatal(err)
	}
	if len(zeroUsageBill.Lines) != 2 || zeroUsageBill.Lines[0].AmountCNY != "0.03" || zeroUsageBill.Lines[1].AmountCNY != "0.02" {
		t.Fatalf("zero-usage bill did not split evenly by stable user ID: %#v", zeroUsageBill.Lines)
	}
	var distributed int64
	if err := db.QueryRowContext(ctx, `SELECT SUM(amount_cents) FROM sharepatch_lines WHERE cycle_id = $1`, zeroUsageBill.Cycle.ID).Scan(&distributed); err != nil {
		t.Fatal(err)
	}
	if distributed != 5 {
		t.Fatalf("distributed cents = %d, want 5", distributed)
	}
}

func hasBlocker(blockers []Blocker, code string) bool {
	for _, blocker := range blockers {
		if blocker.Code == code {
			return true
		}
	}
	return false
}

func dsnWithSearchPath(dsn, schema string) string {
	if strings.HasPrefix(dsn, "postgres://") || strings.HasPrefix(dsn, "postgresql://") {
		parsed, err := url.Parse(dsn)
		if err != nil {
			panic(err)
		}
		query := parsed.Query()
		query.Set("options", "-c search_path="+schema)
		parsed.RawQuery = query.Encode()
		return parsed.String()
	}
	return dsn + " options='-c search_path=" + schema + "'"
}
