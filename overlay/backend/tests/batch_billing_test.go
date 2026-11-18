//go:build integration

package sharepatch_test

import (
	"testing"
	"time"

	"github.com/Wei-Shaw/sub2api/internal/repository"
	"github.com/Wei-Shaw/sub2api/internal/service"
	"github.com/Wei-Shaw/sub2api/internal/sharepatch"
	"github.com/Wei-Shaw/sub2api/migrations"
	"github.com/stretchr/testify/require"
)

func TestPostgresBatchBillingWithSharepatch(t *testing.T) {
	ctx, db := sharepatch.OpenPostgresTestFixture(t)
	// Reuse the physical connection to catch any marker leaking past commit.
	db.SetMaxOpenConns(1)
	for _, name := range []string{"071_add_usage_billing_dedup.sql", "073_add_usage_billing_dedup_archive.sql"} {
		migration, err := migrations.FS.ReadFile(name)
		require.NoError(t, err)
		_, err = db.ExecContext(ctx, string(migration))
		require.NoError(t, err)
	}
	var userID int64
	require.NoError(t, db.QueryRowContext(ctx, `
		INSERT INTO users (email, status) VALUES ('batch@example.test', 'active') RETURNING id
	`).Scan(&userID))
	store, err := sharepatch.NewStore(ctx, db)
	require.NoError(t, err)
	_, err = store.Activate(ctx, time.Now().Add(-time.Hour), 100, true)
	require.NoError(t, err)

	repo := repository.NewUsageBillingRepository(nil, db)
	commands := []*service.UsageBillingCommand{
		{RequestID: "batch-first", APIKeyID: 1, UserID: userID, BalanceCost: 0.10000001},
		{RequestID: "batch-second", APIKeyID: 1, UserID: userID, BalanceCost: 0.20000002},
	}
	outcomes, err := repo.ApplyBatch(ctx, commands)
	require.NoError(t, err)
	require.Len(t, outcomes, len(commands))
	for _, outcome := range outcomes {
		require.NoError(t, outcome.Err)
		require.True(t, outcome.Result.Applied)
	}

	outcomes, err = repo.ApplyBatch(ctx, commands)
	require.NoError(t, err)
	require.Len(t, outcomes, len(commands))
	for _, outcome := range outcomes {
		require.NoError(t, outcome.Err)
		require.False(t, outcome.Result.Applied)
	}
	var balance string
	require.NoError(t, db.QueryRowContext(ctx, `SELECT balance::text FROM users WHERE id = $1`, userID).Scan(&balance))
	require.Equal(t, "9999999.69999997", balance)
	_, err = db.ExecContext(ctx, `UPDATE users SET balance = balance - 1 WHERE id = $1`, userID)
	require.ErrorContains(t, err, "sharepatch permits only metered billing deductions")

	bill, err := store.Settle(ctx, "batch-cycle")
	require.NoError(t, err)
	require.Len(t, bill.Lines, 1)
	require.Equal(t, "0.30000003", bill.Lines[0].USDUsage)
}
