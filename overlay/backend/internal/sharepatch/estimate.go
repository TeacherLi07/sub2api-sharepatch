package sharepatch

import (
	"math/big"
	"time"
)

// expectedMonthEnd preserves the wall-clock time in the billing timezone and
// clamps dates such as January 31 to the last day of the following month.
func expectedMonthEnd(start time.Time, location *time.Location) time.Time {
	local := start.In(location)
	first := time.Date(local.Year(), local.Month()+1, 1, 0, 0, 0, 0, location)
	lastDay := first.AddDate(0, 1, -1).Day()
	day := local.Day()
	if day > lastDay {
		day = lastDay
	}
	return time.Date(first.Year(), first.Month(), day, local.Hour(), local.Minute(), local.Second(), local.Nanosecond(), location).UTC()
}

func elapsedInMonth(start, end, asOf time.Time) time.Duration {
	if !asOf.After(start) {
		return 0
	}
	if !asOf.Before(end) {
		return end.Sub(start)
	}
	return asOf.Sub(start)
}

// proratedCNY applies both ratios before rounding once to the nearest cent.
// This informational estimate never changes allocations or settled bill lines.
func proratedCNY(units, totalUnits *big.Int, cents int64, elapsed, duration time.Duration) *string {
	if totalUnits.Sign() == 0 || duration <= 0 {
		return nil
	}
	numerator := new(big.Int).Mul(units, big.NewInt(cents))
	numerator.Mul(numerator, big.NewInt(int64(elapsed)))
	denominator := new(big.Int).Mul(totalUnits, big.NewInt(int64(duration)))
	quotient, remainder := new(big.Int), new(big.Int)
	quotient.QuoRem(numerator, denominator, remainder)
	if remainder.Lsh(remainder, 1).Cmp(denominator) >= 0 {
		quotient.Add(quotient, big.NewInt(1))
	}
	amount := formatCNY(quotient.Int64())
	return &amount
}

func currentCNYEstimates(row allocation, totalUnits *big.Int, cents int64, elapsed, duration time.Duration) (*string, *string) {
	if totalUnits.Sign() == 0 {
		return nil, nil
	}
	amount := formatCNY(row.Cents)
	if elapsed == duration {
		// Include deterministic cent remainders in both columns at 100%.
		return &amount, &amount
	}
	return &amount, proratedCNY(row.Units, totalUnits, cents, elapsed, duration)
}
