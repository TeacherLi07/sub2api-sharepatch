package sharepatch

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"math/big"
	"strings"
	"time"

	"github.com/shopspring/decimal"
)

func (s *Store) SetCurrentAmount(ctx context.Context, amountCents int64) (*Cycle, error) {
	if amountCents < 0 {
		return nil, errors.New("CNY total must be nonnegative")
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	active, cycleID, _, err := readState(ctx, tx)
	if err != nil {
		return nil, err
	}
	if !active || cycleID == 0 {
		return nil, errors.New("sharepatch is not active")
	}
	var status string
	if err := tx.QueryRowContext(ctx, `SELECT status FROM sharepatch_cycles WHERE id = $1 FOR UPDATE`, cycleID).Scan(&status); err != nil {
		return nil, err
	}
	if status != "current" {
		return nil, errors.New("current billing cycle is already settled")
	}
	if _, err := tx.ExecContext(ctx, `UPDATE sharepatch_cycles SET amount_cents = $1 WHERE id = $2`, amountCents, cycleID); err != nil {
		return nil, err
	}
	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return s.cycle(ctx, s.db, cycleID)
}

func (s *Store) Settle(ctx context.Context, idempotencyKey string) (*PeriodLedger, error) {
	idempotencyKey = strings.TrimSpace(idempotencyKey)
	if idempotencyKey == "" || len(idempotencyKey) > 128 {
		return nil, errors.New("Idempotency-Key is required and must be at most 128 characters")
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	var claimed string
	err = tx.QueryRowContext(ctx, `
		INSERT INTO sharepatch_settlement_keys (idempotency_key, status)
		VALUES ($1, 'pending')
		ON CONFLICT (idempotency_key) DO NOTHING
		RETURNING idempotency_key
	`, idempotencyKey).Scan(&claimed)
	if errors.Is(err, sql.ErrNoRows) {
		var cycleID sql.NullInt64
		var status string
		if err := tx.QueryRowContext(ctx, `
			SELECT cycle_id, status FROM sharepatch_settlement_keys WHERE idempotency_key = $1
		`, idempotencyKey).Scan(&cycleID, &status); err != nil {
			return nil, err
		}
		if status != "complete" || !cycleID.Valid {
			return nil, errors.New("settlement idempotency key is pending without a committed bill")
		}
		ledger, err := loadPeriodLedger(ctx, tx, cycleID.Int64)
		if err != nil {
			return nil, err
		}
		return ledger, tx.Commit()
	}
	if err != nil {
		return nil, err
	}

	active, cycleID, _, err := readState(ctx, tx)
	if err != nil {
		return nil, err
	}
	if !active || cycleID == 0 {
		return nil, errors.New("sharepatch is not active")
	}
	var amountCents int64
	var status string
	if err := tx.QueryRowContext(ctx, `
		SELECT amount_cents, status FROM sharepatch_cycles WHERE id = $1 FOR UPDATE
	`, cycleID).Scan(&amountCents, &status); err != nil {
		return nil, err
	}
	if status != "current" {
		return nil, errors.New("current cycle has already been settled")
	}
	// SHARE blocks all user table writes, placing concurrent deductions and
	// roster changes wholly before or after the database-clock boundary.
	if _, err := tx.ExecContext(ctx, `LOCK TABLE users IN SHARE MODE`); err != nil {
		return nil, err
	}
	var boundary time.Time
	if err := tx.QueryRowContext(ctx, `SELECT clock_timestamp()`).Scan(&boundary); err != nil {
		return nil, err
	}
	users, err := s.loadUsers(ctx, tx, cycleID)
	if err != nil {
		return nil, err
	}
	if len(users) == 0 {
		return nil, errors.New("cannot settle a cycle without participants")
	}
	inputs := make([]allocationInput, 0, len(users))
	usageByID := make(map[int64]*big.Int, len(users))
	for _, user := range users {
		units, err := usageUnits(user)
		if err != nil {
			return nil, err
		}
		inputs = append(inputs, allocationInput{UserID: user.ID, Units: units})
		usageByID[user.ID] = units
	}
	allocations, totalUnits, err := allocateCents(inputs, amountCents)
	if err != nil {
		return nil, err
	}
	allocationByID := make(map[int64]allocation, len(allocations))
	for _, row := range allocations {
		allocationByID[row.UserID] = row
	}
	for _, user := range users {
		row := allocationByID[user.ID]
		ratio := "0.00000000000000000000"
		if totalUnits.Sign() > 0 {
			ratio = decimal.NewFromBigInt(usageByID[user.ID], 0).
				DivRound(decimal.NewFromBigInt(totalUnits, 0), 20).StringFixed(20)
		}
		if _, err := tx.ExecContext(ctx, `
			INSERT INTO sharepatch_lines
				(cycle_id, user_id, email_snapshot, usd_usage, share_ratio, amount_cents)
			VALUES ($1, $2, $3, $4::numeric, $5::numeric, $6)
		`, cycleID, user.ID, user.Email, unitsDecimal(usageByID[user.ID]), ratio, row.Cents); err != nil {
			return nil, err
		}
		if _, err := tx.ExecContext(ctx, `
			INSERT INTO sharepatch_boundaries
				(cycle_id, boundary, user_id, email_snapshot, status_snapshot, created_at_snapshot, balance, captured_at)
			VALUES ($1, 'end', $2, $3, $4, $5, $6::numeric, $7)
		`, cycleID, user.ID, user.Email, user.Status, user.CreatedAt, user.Current, boundary); err != nil {
			return nil, err
		}
	}
	if _, err := tx.ExecContext(ctx, `
		UPDATE sharepatch_cycles SET status = 'settled', ends_at = $1, settled_at = $1 WHERE id = $2
	`, boundary, cycleID); err != nil {
		return nil, err
	}
	var nextCycleID int64
	if err := tx.QueryRowContext(ctx, `
		INSERT INTO sharepatch_cycles (starts_at, amount_cents, status)
		VALUES ($1, $2, 'current') RETURNING id
	`, boundary, amountCents).Scan(&nextCycleID); err != nil {
		return nil, err
	}
	for _, user := range users {
		if _, err := tx.ExecContext(ctx, `
			INSERT INTO sharepatch_boundaries
				(cycle_id, boundary, user_id, email_snapshot, status_snapshot, created_at_snapshot, balance, captured_at)
			VALUES ($1, 'start', $2, $3, $4, $5, $6::numeric, $7)
		`, nextCycleID, user.ID, user.Email, user.Status, user.CreatedAt, user.Current, boundary); err != nil {
			return nil, err
		}
	}
	if _, err := tx.ExecContext(ctx, `UPDATE sharepatch_state SET current_cycle_id = $1 WHERE id = $2`, nextCycleID, stateRowID); err != nil {
		return nil, err
	}
	if _, err := tx.ExecContext(ctx, `
		UPDATE sharepatch_settlement_keys
		SET cycle_id = $1, status = 'complete', completed_at = $2
		WHERE idempotency_key = $3
	`, cycleID, boundary, idempotencyKey); err != nil {
		return nil, err
	}
	ledger, err := loadPeriodLedger(ctx, tx, cycleID)
	if err != nil {
		return nil, err
	}
	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return ledger, nil
}

func loadPeriodLedger(ctx context.Context, q queryer, cycleID int64) (*PeriodLedger, error) {
	var cycle Cycle
	var end sql.NullTime
	var cents int64
	if err := q.QueryRowContext(ctx, `
		SELECT id, starts_at, ends_at, amount_cents, status
		FROM sharepatch_cycles WHERE id = $1
	`, cycleID).Scan(&cycle.ID, &cycle.StartsAt, &end, &cents, &cycle.Status); err != nil {
		return nil, err
	}
	cycle.AmountCNY = formatCNY(cents)
	if end.Valid {
		cycle.EndsAt = &end.Time
	}
	rows, err := q.QueryContext(ctx, `
		SELECT user_id, email_snapshot, usd_usage::text, share_ratio::text, amount_cents
		FROM sharepatch_lines WHERE cycle_id = $1 ORDER BY user_id
	`, cycleID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	ledger := &PeriodLedger{Cycle: cycle, Lines: []BillLine{}}
	for rows.Next() {
		var line BillLine
		var ratio string
		var lineCents int64
		if err := rows.Scan(&line.UserID, &line.Email, &line.USDUsage, &ratio, &lineCents); err != nil {
			return nil, err
		}
		d, err := decimal.NewFromString(ratio)
		if err != nil {
			return nil, err
		}
		line.SharePercent = d.Mul(decimal.NewFromInt(100)).StringFixed(8)
		line.AmountCNY = formatCNY(lineCents)
		ledger.Lines = append(ledger.Lines, line)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return ledger, nil
}

func (s *Store) Status(ctx context.Context) (bool, string, error) {
	active, _, timezone, err := s.state(ctx)
	return active, timezone, err
}

func (s *Store) ActivationStatusError(ctx context.Context) error {
	active, _, _, err := s.state(ctx)
	if err != nil {
		return err
	}
	if !active {
		return errors.New("sharepatch is pending activation")
	}
	return nil
}

func (s *Store) currentCycleStart(ctx context.Context) (time.Time, error) {
	active, cycleID, _, err := s.state(ctx)
	if err != nil {
		return time.Time{}, err
	}
	if !active || cycleID == 0 {
		return time.Time{}, errors.New("sharepatch is not active")
	}
	var startsAt time.Time
	err = s.db.QueryRowContext(ctx, `SELECT starts_at FROM sharepatch_cycles WHERE id = $1`, cycleID).Scan(&startsAt)
	return startsAt, err
}

func checkAmountString(raw string) (int64, error) {
	cents, err := parseCNYCents(raw)
	if err != nil {
		return 0, fmt.Errorf("invalid total_cny: %w", err)
	}
	return cents, nil
}
