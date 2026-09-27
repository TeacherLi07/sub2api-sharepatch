package sharepatch

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"embed"
	"encoding/hex"
	"errors"
	"fmt"
	"io/fs"
	"math/big"
	"sort"
	"strings"
	"time"

	"github.com/shopspring/decimal"
)

//go:embed migrations/*.sql
var migrationFiles embed.FS

const (
	stateRowID = 1
	lockName   = "sub2api-sharepatch-migrations-v1"
)

type Store struct {
	db *sql.DB
}

func NewStore(ctx context.Context, db *sql.DB) (*Store, error) {
	if db == nil {
		return nil, errors.New("sharepatch database is nil")
	}
	s := &Store{db: db}
	if err := s.Migrate(ctx); err != nil {
		return nil, fmt.Errorf("initialize sharepatch database: %w", err)
	}
	return s, nil
}

func (s *Store) Migrate(ctx context.Context) error {
	sharepatchLogger.Debug("checking database migrations")
	if _, err := s.db.ExecContext(ctx, `
		CREATE TABLE IF NOT EXISTS sharepatch_schema_migrations (
			version TEXT PRIMARY KEY,
			checksum TEXT NOT NULL,
			applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
		)
	`); err != nil {
		return err
	}
	entries, err := fs.ReadDir(migrationFiles, "migrations")
	if err != nil {
		return err
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].Name() < entries[j].Name() })
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".sql") {
			continue
		}
		version := strings.TrimSuffix(entry.Name(), ".sql")
		sharepatchLogger.Debug("checking database migration", "version", version)
		sqlBytes, err := migrationFiles.ReadFile("migrations/" + entry.Name())
		if err != nil {
			return err
		}
		sum := sha256.Sum256(sqlBytes)
		checksum := hex.EncodeToString(sum[:])
		tx, err := s.db.BeginTx(ctx, nil)
		if err != nil {
			return err
		}
		if _, err = tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtext($1))`, lockName); err != nil {
			_ = tx.Rollback()
			return err
		}
		var appliedChecksum string
		err = tx.QueryRowContext(ctx,
			`SELECT checksum FROM sharepatch_schema_migrations WHERE version = $1`, version,
		).Scan(&appliedChecksum)
		switch {
		case err == nil:
			if appliedChecksum != checksum {
				_ = tx.Rollback()
				return fmt.Errorf("sharepatch migration %s checksum changed", version)
			}
		case errors.Is(err, sql.ErrNoRows):
			if _, err = tx.ExecContext(ctx, string(sqlBytes)); err == nil {
				_, err = tx.ExecContext(ctx,
					`INSERT INTO sharepatch_schema_migrations(version, checksum) VALUES ($1, $2)`,
					version, checksum,
				)
			}
		default:
			_ = tx.Rollback()
			return err
		}
		if err != nil {
			_ = tx.Rollback()
			sharepatchLogger.Error("database migration failed", "version", version, "error", safeSharepatchError(err))
			return fmt.Errorf("apply sharepatch migration %s: %w", version, err)
		}
		if err := tx.Commit(); err != nil {
			sharepatchLogger.Error("database migration commit failed", "version", version, "error", safeSharepatchError(err))
			return err
		}
		sharepatchLogger.Info("database migration ready", "version", version)
	}
	sharepatchLogger.Debug("database migrations ready")
	return nil
}

type Cycle struct {
	ID        int64      `json:"id"`
	StartsAt  time.Time  `json:"starts_at"`
	EndsAt    *time.Time `json:"ends_at,omitempty"`
	AmountCNY string     `json:"amount_cny"`
	Status    string     `json:"status"`
}

type BillLine struct {
	UserID       int64  `json:"user_id"`
	Email        string `json:"email"`
	Status       string `json:"status,omitempty"`
	CreatedAt    string `json:"created_at,omitempty"`
	USDUsage     string `json:"usd_usage"`
	SharePercent string `json:"share_percent"`
	AmountCNY    string `json:"amount_cny"`
}

type CurrentPreview struct {
	Cycle    *Cycle     `json:"cycle,omitempty"`
	TotalUSD string     `json:"total_usd"`
	Lines    []BillLine `json:"lines"`
}

type PeriodLedger struct {
	Cycle Cycle      `json:"cycle"`
	Lines []BillLine `json:"lines"`
}

type Dashboard struct {
	Active   bool            `json:"active"`
	Timezone string          `json:"timezone"`
	Current  *CurrentPreview `json:"current,omitempty"`
	History  []PeriodLedger  `json:"history"`
}

type userBalance struct {
	ID        int64
	Email     string
	Status    string
	CreatedAt time.Time
	Start     string
	Current   string
}

type queryer interface {
	QueryRowContext(context.Context, string, ...any) *sql.Row
	QueryContext(context.Context, string, ...any) (*sql.Rows, error)
}

func (s *Store) state(ctx context.Context) (bool, int64, string, error) {
	var active bool
	var cycleID sql.NullInt64
	var timezone string
	err := s.db.QueryRowContext(ctx,
		`SELECT active, current_cycle_id, timezone FROM sharepatch_state WHERE id = $1`, stateRowID,
	).Scan(&active, &cycleID, &timezone)
	if err != nil {
		return false, 0, "", err
	}
	if cycleID.Valid {
		return active, cycleID.Int64, timezone, nil
	}
	return active, 0, timezone, nil
}

func (s *Store) cycle(ctx context.Context, q queryer, cycleID int64) (*Cycle, error) {
	var cycle Cycle
	var cents int64
	var end sql.NullTime
	err := q.QueryRowContext(ctx, `
		SELECT id, starts_at, ends_at, amount_cents, status
		FROM sharepatch_cycles WHERE id = $1
	`, cycleID).Scan(&cycle.ID, &cycle.StartsAt, &end, &cents, &cycle.Status)
	if err != nil {
		return nil, err
	}
	if end.Valid {
		cycle.EndsAt = &end.Time
	}
	cycle.AmountCNY = formatCNY(cents)
	return &cycle, nil
}

func (s *Store) loadUsers(ctx context.Context, q queryer, cycleID int64) ([]userBalance, error) {
	query := `
		SELECT u.id, u.email, u.status, u.created_at,
		       COALESCE(b.balance, 10000000.00000000)::text,
		       u.balance::text
		FROM users u
		LEFT JOIN sharepatch_boundaries b
		  ON b.cycle_id = $1 AND b.boundary = 'start' AND b.user_id = u.id
		WHERE u.deleted_at IS NULL
		ORDER BY u.id
	`
	rows, err := q.QueryContext(ctx, query, cycleID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var users []userBalance
	for rows.Next() {
		var u userBalance
		if err := rows.Scan(&u.ID, &u.Email, &u.Status, &u.CreatedAt, &u.Start, &u.Current); err != nil {
			return nil, err
		}
		users = append(users, u)
	}
	return users, rows.Err()
}

func usageUnits(user userBalance) (*big.Int, error) {
	start, err := decimalUnits(user.Start)
	if err != nil {
		return nil, err
	}
	current, err := decimalUnits(user.Current)
	if err != nil {
		return nil, err
	}
	usage := new(big.Int).Sub(start, current)
	if usage.Sign() < 0 {
		return nil, fmt.Errorf("user %d balance increased during an active cycle", user.ID)
	}
	return usage, nil
}

func (s *Store) currentPreview(ctx context.Context, q queryer, cycleID int64) (*CurrentPreview, error) {
	cycle, err := s.cycle(ctx, q, cycleID)
	if err != nil {
		return nil, err
	}
	users, err := s.loadUsers(ctx, q, cycleID)
	if err != nil {
		return nil, err
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
	cents, err := parseCNYCents(cycle.AmountCNY)
	if err != nil {
		return nil, err
	}
	allocations, total, err := allocateCents(inputs, cents)
	if err != nil && len(inputs) != 0 {
		return nil, err
	}
	allocationByID := make(map[int64]allocation, len(allocations))
	for _, row := range allocations {
		allocationByID[row.UserID] = row
	}
	preview := &CurrentPreview{Cycle: cycle, TotalUSD: unitsDecimal(total), Lines: make([]BillLine, 0, len(users))}
	for _, user := range users {
		row := allocationByID[user.ID]
		sharePercent := row.SharePercent
		if sharePercent == "" {
			sharePercent = "0.00000000"
		}
		preview.Lines = append(preview.Lines, BillLine{
			UserID:       user.ID,
			Email:        user.Email,
			Status:       user.Status,
			CreatedAt:    user.CreatedAt.UTC().Format(time.RFC3339Nano),
			USDUsage:     unitsDecimal(usageByID[user.ID]),
			SharePercent: sharePercent,
			AmountCNY:    formatCNY(row.Cents),
		})
	}
	return preview, nil
}

func (s *Store) Dashboard(ctx context.Context) (*Dashboard, error) {
	tx, err := s.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelRepeatableRead, ReadOnly: true})
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	active, cycleID, timezone, err := readState(ctx, tx)
	if err != nil {
		return nil, err
	}
	dashboard := &Dashboard{Active: active, Timezone: timezone, History: []PeriodLedger{}}
	if active && cycleID > 0 {
		dashboard.Current, err = s.currentPreview(ctx, tx, cycleID)
		if err != nil {
			return nil, err
		}
	}
	rows, err := tx.QueryContext(ctx, `
		SELECT c.id, c.starts_at, c.ends_at, c.amount_cents, c.status,
		       l.user_id, l.email_snapshot, l.usd_usage::text,
		       l.share_ratio::text, l.amount_cents
		FROM sharepatch_cycles c
		JOIN sharepatch_lines l ON l.cycle_id = c.id
		WHERE c.status = 'settled'
		ORDER BY c.id DESC, l.user_id
	`)
	if err != nil {
		return nil, err
	}
	periodIndex := make(map[int64]int)
	for rows.Next() {
		var cycle Cycle
		var end sql.NullTime
		var cycleCents int64
		var line BillLine
		var usage, ratio string
		var lineCents int64
		if err := rows.Scan(&cycle.ID, &cycle.StartsAt, &end, &cycleCents, &cycle.Status,
			&line.UserID, &line.Email, &usage, &ratio, &lineCents); err != nil {
			_ = rows.Close()
			return nil, err
		}
		if end.Valid {
			cycle.EndsAt = &end.Time
		}
		cycle.AmountCNY = formatCNY(cycleCents)
		line.USDUsage = usage
		ratioDecimal, err := decimal.NewFromString(ratio)
		if err != nil {
			_ = rows.Close()
			return nil, err
		}
		line.SharePercent = ratioDecimal.Mul(decimal.NewFromInt(100)).StringFixed(8)
		line.AmountCNY = formatCNY(lineCents)
		index, ok := periodIndex[cycle.ID]
		if !ok {
			index = len(dashboard.History)
			periodIndex[cycle.ID] = index
			dashboard.History = append(dashboard.History, PeriodLedger{Cycle: cycle, Lines: []BillLine{}})
		}
		dashboard.History[index].Lines = append(dashboard.History[index].Lines, line)
	}
	if err := rows.Err(); err != nil {
		_ = rows.Close()
		return nil, err
	}
	if err := rows.Close(); err != nil {
		return nil, err
	}
	return dashboard, tx.Commit()
}

func readState(ctx context.Context, q queryer) (bool, int64, string, error) {
	var active bool
	var cycleID sql.NullInt64
	var timezone string
	err := q.QueryRowContext(ctx,
		`SELECT active, current_cycle_id, timezone FROM sharepatch_state WHERE id = $1`, stateRowID,
	).Scan(&active, &cycleID, &timezone)
	if err != nil {
		return false, 0, "", err
	}
	if cycleID.Valid {
		return active, cycleID.Int64, timezone, nil
	}
	return active, 0, timezone, nil
}
