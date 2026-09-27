package sharepatch

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"math/big"
	"time"

	"github.com/shopspring/decimal"
)

type Blocker struct {
	Code  string `json:"code"`
	Count int64  `json:"count,omitempty"`
	Text  string `json:"text"`
}

type BackfillUser struct {
	UserID       int64  `json:"user_id"`
	Email        string `json:"email"`
	Status       string `json:"status"`
	CreatedAt    string `json:"created_at"`
	BalanceNow   string `json:"balance_now"`
	BalanceAfter string `json:"balance_after_activation"`
	LogCount     int64  `json:"usage_log_count"`
	USDUsage     string `json:"usd_usage"`
}

type ActivationPreview struct {
	Active               bool           `json:"active"`
	StartsAt             time.Time      `json:"starts_at"`
	CutoffAt             time.Time      `json:"cutoff_at"`
	TotalCNY             string         `json:"total_cny"`
	Users                []BackfillUser `json:"users"`
	Blockers             []Blocker      `json:"blockers"`
	RequiresConfirmation bool           `json:"requires_usage_log_integrity_confirmation"`
}

type backfillUser struct {
	BackfillUser
	units     *big.Int
	createdAt time.Time
}

func (s *Store) PreviewActivation(ctx context.Context, startsAt time.Time, amountCents int64) (*ActivationPreview, error) {
	if amountCents < 0 {
		return nil, errors.New("CNY total must be nonnegative")
	}
	tx, err := s.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelRepeatableRead, ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	active, _, _, err := readState(ctx, tx)
	if err != nil {
		return nil, err
	}
	var cutoff time.Time
	if err := tx.QueryRowContext(ctx, `SELECT clock_timestamp()`).Scan(&cutoff); err != nil {
		return nil, err
	}
	if !startsAt.Before(cutoff) {
		return nil, errors.New("cycle start must be before the database clock")
	}
	users, err := loadBackfillUsers(ctx, tx, startsAt, cutoff)
	if err != nil {
		return nil, err
	}
	blockers, err := checkActivationBlockers(ctx, tx, startsAt, cutoff, int64(len(users)), true)
	if err != nil {
		return nil, err
	}
	for _, user := range users {
		if user.units.Cmp(mustMeterUnits()) >= 0 {
			blockers = append(blockers, Blocker{
				Code:  "backfill_exceeds_meter",
				Count: 1,
				Text:  fmt.Sprintf("用户 %s 的区间余额用量已达到或超过固定电表起值，无法激活。", user.Email),
			})
		}
	}
	preview := &ActivationPreview{
		Active: active, StartsAt: startsAt.UTC(), CutoffAt: cutoff.UTC(),
		TotalCNY: formatCNY(amountCents), Blockers: blockers,
		RequiresConfirmation: true, Users: make([]BackfillUser, 0, len(users)),
	}
	for _, user := range users {
		preview.Users = append(preview.Users, user.BackfillUser)
	}
	return preview, nil
}

func (s *Store) Activate(ctx context.Context, startsAt time.Time, amountCents int64, confirmLogIntegrity bool) (*Cycle, error) {
	if !confirmLogIntegrity {
		return nil, errors.New("confirm that logs are complete, cleanup is paused, the old instance is stopped, and a backup is available")
	}
	preview, err := s.PreviewActivation(ctx, startsAt, amountCents)
	if err != nil {
		return nil, err
	}
	if preview.Active {
		return nil, errors.New("sharepatch has already been activated")
	}
	if len(preview.Blockers) != 0 {
		return nil, formatBlockers(preview.Blockers)
	}

	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	var active bool
	if err := tx.QueryRowContext(ctx, `SELECT active FROM sharepatch_state WHERE id = $1 FOR UPDATE`, stateRowID).Scan(&active); err != nil {
		return nil, err
	}
	if active {
		return nil, errors.New("sharepatch has already been activated")
	}
	// Lock immediately after the state row. Billing touches usage_billing_dedup
	// before users; balance triggers only read sharepatch_state, so this order
	// cannot form a cycle with the billing transaction.
	lockStarted := time.Now()
	sharepatchLogger.Info("activation waiting for users table lock")
	if _, err := tx.ExecContext(ctx, `LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE`); err != nil {
		return nil, err
	}
	sharepatchLogger.Info("activation acquired users table lock", "wait_ms", time.Since(lockStarted).Milliseconds())
	var cutoff time.Time
	if err := tx.QueryRowContext(ctx, `SELECT clock_timestamp()`).Scan(&cutoff); err != nil {
		return nil, err
	}
	blockers, err := checkActivationBlockers(ctx, tx, startsAt, cutoff, -1, false)
	if err != nil {
		return nil, err
	}
	if len(blockers) != 0 {
		return nil, formatBlockers(blockers)
	}
	users, err := lockedBackfillUsers(ctx, tx, preview, startsAt, cutoff)
	if err != nil {
		return nil, err
	}
	if len(users) == 0 {
		return nil, errors.New("activation requires at least one account")
	}
	if _, err := tx.ExecContext(ctx, `SELECT set_config('sharepatch.initializing', 'on', TRUE)`); err != nil {
		return nil, err
	}
	var cycleID int64
	if err := tx.QueryRowContext(ctx, `
		INSERT INTO sharepatch_cycles (starts_at, amount_cents, status)
		VALUES ($1, $2, 'current') RETURNING id
	`, startsAt.UTC(), amountCents).Scan(&cycleID); err != nil {
		return nil, err
	}
	meter := decimal.RequireFromString(meterStart)
	for _, user := range users {
		balance := meter.Sub(decimal.NewFromBigInt(user.units, -8)).StringFixed(8)
		if _, err := tx.ExecContext(ctx, `
			UPDATE users SET balance = $1::numeric, updated_at = clock_timestamp()
			WHERE id = $2 AND deleted_at IS NULL
		`, balance, user.UserID); err != nil {
			return nil, fmt.Errorf("set initial meter for user %d: %w", user.UserID, err)
		}
		if _, err := tx.ExecContext(ctx, `
			INSERT INTO sharepatch_boundaries
				(cycle_id, boundary, user_id, email_snapshot, status_snapshot, created_at_snapshot, balance, captured_at)
			VALUES ($1, 'start', $2, $3, $4, $5, $6::numeric, $7)
			`, cycleID, user.UserID, user.Email, user.Status, user.createdAt, meterStart, cutoff); err != nil {
			return nil, err
		}
	}
	if _, err := tx.ExecContext(ctx, `
		UPDATE sharepatch_state SET active = TRUE, current_cycle_id = $1, activated_at = $2
		WHERE id = $3
	`, cycleID, cutoff, stateRowID); err != nil {
		return nil, err
	}
	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return s.cycle(ctx, s.db, cycleID)
}

func loadBackfillUsers(ctx context.Context, q queryer, startsAt, cutoff time.Time) ([]backfillUser, error) {
	rows, err := q.QueryContext(ctx, `
		SELECT u.id, u.email, u.status, u.created_at, u.balance::text,
		       COUNT(ul.id), COALESCE(SUM(ROUND(ul.actual_cost, 8)), 0)::text
		FROM users u
		LEFT JOIN usage_logs ul
		  ON ul.user_id = u.id AND ul.billing_type = 0
		 AND ul.created_at >= $1 AND ul.created_at < $2
		WHERE u.deleted_at IS NULL
		GROUP BY u.id, u.email, u.status, u.created_at, u.balance
		ORDER BY u.id
	`, startsAt.UTC(), cutoff.UTC())
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var users []backfillUser
	for rows.Next() {
		var user backfillUser
		var balance, usage string
		if err := rows.Scan(&user.UserID, &user.Email, &user.Status, &user.createdAt, &balance, &user.LogCount, &usage); err != nil {
			return nil, err
		}
		user.units, err = decimalUnits(usage)
		if err != nil {
			return nil, fmt.Errorf("round backfill for user %d: %w", user.UserID, err)
		}
		if user.units.Sign() < 0 {
			return nil, fmt.Errorf("user %d has negative backfill usage", user.UserID)
		}
		balanceAfter := decimal.RequireFromString(meterStart).Sub(decimal.NewFromBigInt(user.units, -8))
		user.BalanceNow = balance
		user.BalanceAfter = balanceAfter.StringFixed(8)
		user.USDUsage = unitsDecimal(user.units)
		user.CreatedAt = user.createdAt.UTC().Format(time.RFC3339Nano)
		users = append(users, user)
	}
	return users, rows.Err()
}

func checkActivationBlockers(ctx context.Context, q queryer, startsAt, cutoff time.Time, knownUserCount int64, includeDeletedUsage bool) ([]Blocker, error) {
	blockers := make([]Blocker, 0, 5)
	addCount := func(code, text, query string, args ...any) error {
		var count int64
		if err := q.QueryRowContext(ctx, query, args...).Scan(&count); err != nil {
			return err
		}
		if count > 0 {
			blockers = append(blockers, Blocker{Code: code, Count: count, Text: text})
		}
		return nil
	}
	if knownUserCount == 0 {
		blockers = append(blockers, Blocker{Code: "no_users", Text: "至少需要一个未删除用户。"})
	}
	if err := addCount("frozen_balance", "存在冻结余额；请先结清或解除冻结。", `
		SELECT COUNT(*) FROM users WHERE COALESCE(frozen_balance, 0) <> 0
	`); err != nil {
		return nil, err
	}
	if err := addCount("active_subscription", "存在有效订阅计费路径；请先结束所有订阅。", `
		SELECT COUNT(*) FROM user_subscriptions
		WHERE status = 'active' AND starts_at <= $1 AND expires_at > $1
	`, cutoff.UTC()); err != nil {
		return nil, err
	}
	if err := addCount("pending_batch_image", "存在尚未结清的批量图片任务或冻结金额。", `
		SELECT COUNT(*) FROM batch_image_jobs
		WHERE settled_at IS NULL AND status IN ('created','uploading','submitted','running','indexing','settling')
	`); err != nil {
		return nil, err
	}
	if err := addCount("usage_cleanup_running", "存在待执行或执行中的使用记录清理任务；请等待结束并暂停清理。", `
		SELECT COUNT(*) FROM usage_cleanup_tasks WHERE status IN ('pending', 'running')
	`); err != nil {
		return nil, err
	}
	if includeDeletedUsage {
		if err := addCount("deleted_user_usage", "所选区间内存在已软删除用户的余额计费日志，无法安全回填。", `
			SELECT COUNT(DISTINCT u.id)
			FROM users u JOIN usage_logs ul ON ul.user_id = u.id
			WHERE u.deleted_at IS NOT NULL AND ul.billing_type = 0
			  AND ul.created_at >= $1 AND ul.created_at < $2
		`, startsAt.UTC(), cutoff.UTC()); err != nil {
			return nil, err
		}
	}
	return blockers, nil
}

func lockedBackfillUsers(ctx context.Context, tx *sql.Tx, preview *ActivationPreview, startsAt, cutoff time.Time) ([]backfillUser, error) {
	preflight := make(map[int64]backfillUser, len(preview.Users))
	for _, row := range preview.Users {
		units, err := decimalUnits(row.USDUsage)
		if err != nil {
			return nil, err
		}
		preflight[row.UserID] = backfillUser{BackfillUser: row, units: units}
	}
	lateUsage := make(map[int64]struct {
		units *big.Int
		count int64
	})
	rows, err := tx.QueryContext(ctx, `
		SELECT user_id, COUNT(*), COALESCE(SUM(ROUND(actual_cost, 8)), 0)::text
		FROM usage_logs
		WHERE billing_type = 0 AND created_at >= $1 AND created_at < $2
		GROUP BY user_id
	`, preview.CutoffAt.UTC(), cutoff.UTC())
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var userID, count int64
		var usage string
		if err := rows.Scan(&userID, &count, &usage); err != nil {
			_ = rows.Close()
			return nil, err
		}
		units, err := decimalUnits(usage)
		if err != nil {
			_ = rows.Close()
			return nil, err
		}
		lateUsage[userID] = struct {
			units *big.Int
			count int64
		}{units: units, count: count}
	}
	if err := rows.Err(); err != nil {
		_ = rows.Close()
		return nil, err
	}
	if err := rows.Close(); err != nil {
		return nil, err
	}
	var lateDeleted int64
	if err := tx.QueryRowContext(ctx, `
		SELECT COUNT(DISTINCT u.id)
		FROM users u JOIN usage_logs ul ON ul.user_id = u.id
		WHERE u.deleted_at >= $1 AND ul.billing_type = 0
		  AND ul.created_at >= $2 AND ul.created_at < $3
	`, preview.CutoffAt.UTC(), startsAt.UTC(), cutoff.UTC()).Scan(&lateDeleted); err != nil {
		return nil, err
	}
	if lateDeleted > 0 {
		return nil, fmt.Errorf("activation blocked: %d recently deleted account(s) have balance-billing logs in the migration interval", lateDeleted)
	}

	users, err := loadCurrentRoster(ctx, tx)
	if err != nil {
		return nil, err
	}
	currentIDs := make(map[int64]struct{}, len(users))
	result := make([]backfillUser, 0, len(users))
	meterUnits := mustMeterUnits()
	for _, current := range users {
		currentIDs[current.ID] = struct{}{}
		base, ok := preflight[current.ID]
		if !ok {
			base = backfillUser{units: new(big.Int), BackfillUser: BackfillUser{UserID: current.ID}}
		}
		if late, ok := lateUsage[current.ID]; ok {
			base.units.Add(base.units, late.units)
			base.LogCount += late.count
		}
		if base.units.Cmp(meterUnits) >= 0 {
			return nil, fmt.Errorf("activation blocked: user %d backfill usage is at least the fixed meter start", current.ID)
		}
		base.Email = current.Email
		base.Status = current.Status
		base.createdAt = current.CreatedAt
		base.CreatedAt = current.CreatedAt.UTC().Format(time.RFC3339Nano)
		base.BalanceNow = current.Current
		base.USDUsage = unitsDecimal(base.units)
		base.BalanceAfter = decimal.RequireFromString(meterStart).
			Sub(decimal.NewFromBigInt(base.units, -8)).StringFixed(8)
		result = append(result, base)
	}
	for userID, old := range preflight {
		if _, remains := currentIDs[userID]; remains {
			continue
		}
		var count int64
		if err := tx.QueryRowContext(ctx, `
			SELECT COUNT(*) FROM usage_logs
			WHERE user_id = $1 AND billing_type = 0 AND created_at >= $2 AND created_at < $3
		`, userID, startsAt.UTC(), cutoff.UTC()).Scan(&count); err != nil {
			return nil, err
		}
		if count > 0 || old.units.Sign() > 0 {
			return nil, fmt.Errorf("activation blocked: deleted user %d has balance-billing usage in the migration interval", userID)
		}
	}
	return result, nil
}

func loadCurrentRoster(ctx context.Context, q queryer) ([]userBalance, error) {
	rows, err := q.QueryContext(ctx, `
		SELECT id, email, status, created_at, balance::text
		FROM users WHERE deleted_at IS NULL ORDER BY id
	`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var users []userBalance
	for rows.Next() {
		var user userBalance
		if err := rows.Scan(&user.ID, &user.Email, &user.Status, &user.CreatedAt, &user.Current); err != nil {
			return nil, err
		}
		users = append(users, user)
	}
	return users, rows.Err()
}

func mustMeterUnits() *big.Int {
	units, _ := decimalUnits(meterStart)
	return units
}

func formatBlockers(blockers []Blocker) error {
	message := "activation blocked"
	for _, blocker := range blockers {
		message += "; " + blocker.Text
	}
	return errors.New(message)
}
