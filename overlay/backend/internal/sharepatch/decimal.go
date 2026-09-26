package sharepatch

import (
	"fmt"
	"math/big"
	"sort"

	"github.com/shopspring/decimal"
)

const meterStart = "10000000.00000000"

type allocationInput struct {
	UserID int64
	Units  *big.Int // USD rounded to 8 places, in 1e-8 USD units
}

type allocation struct {
	UserID       int64
	Units        *big.Int
	Cents        int64
	SharePercent string
}

func decimalUnits(raw string) (*big.Int, error) {
	d, err := decimal.NewFromString(raw)
	if err != nil {
		return nil, fmt.Errorf("invalid decimal %q: %w", raw, err)
	}
	scaled := d.Shift(8)
	if !scaled.Equal(scaled.Truncate(0)) {
		return nil, fmt.Errorf("decimal %q has more than eight fractional places", raw)
	}
	return scaled.BigInt(), nil
}

func unitsDecimal(units *big.Int) string {
	return decimal.NewFromBigInt(units, -8).StringFixed(8)
}

func parseCNYCents(raw string) (int64, error) {
	d, err := decimal.NewFromString(raw)
	if err != nil || d.IsNegative() {
		return 0, fmt.Errorf("CNY total must be a nonnegative decimal amount")
	}
	scaled := d.Shift(2)
	if !scaled.Equal(scaled.Truncate(0)) || !scaled.BigInt().IsInt64() {
		return 0, fmt.Errorf("CNY total must have at most two decimal places and fit in a signed 64-bit integer")
	}
	return scaled.BigInt().Int64(), nil
}

func formatCNY(cents int64) string {
	negative := cents < 0
	if negative {
		cents = -cents
	}
	s := fmt.Sprintf("%d.%02d", cents/100, cents%100)
	if negative {
		return "-" + s
	}
	return s
}

func allocateCents(inputs []allocationInput, totalCents int64) ([]allocation, *big.Int, error) {
	if totalCents < 0 {
		return nil, nil, fmt.Errorf("total cents must be nonnegative")
	}
	ordered := append([]allocationInput(nil), inputs...)
	sort.Slice(ordered, func(i, j int) bool { return ordered[i].UserID < ordered[j].UserID })
	if len(ordered) == 0 {
		return nil, new(big.Int), fmt.Errorf("cannot allocate a bill without participants")
	}
	totalUnits := new(big.Int)
	for _, row := range ordered {
		if row.Units == nil || row.Units.Sign() < 0 {
			return nil, nil, fmt.Errorf("user %d has invalid negative or missing usage", row.UserID)
		}
		totalUnits.Add(totalUnits, row.Units)
	}

	result := make([]allocation, len(ordered))
	remainders := make([]*big.Int, len(ordered))
	if totalUnits.Sign() == 0 {
		share := totalCents / int64(len(ordered))
		remainder := totalCents % int64(len(ordered))
		for i, row := range ordered {
			result[i] = allocation{UserID: row.UserID, Units: new(big.Int).Set(row.Units), Cents: share, SharePercent: "0.00000000"}
			if int64(i) < remainder {
				result[i].Cents++
			}
		}
		return result, totalUnits, nil
	}

	denom := new(big.Int).Set(totalUnits)
	centsBig := big.NewInt(totalCents)
	for i, row := range ordered {
		numerator := new(big.Int).Mul(new(big.Int).Set(row.Units), centsBig)
		q, rem := new(big.Int), new(big.Int)
		q.QuoRem(numerator, denom, rem)
		if !q.IsInt64() {
			return nil, nil, fmt.Errorf("allocated cents overflow for user %d", row.UserID)
		}
		result[i] = allocation{UserID: row.UserID, Units: new(big.Int).Set(row.Units), Cents: q.Int64()}
		remainders[i] = rem
	}
	left := totalCents
	for _, row := range result {
		left -= row.Cents
	}
	indices := make([]int, len(result))
	for i := range indices {
		indices[i] = i
	}
	sort.Slice(indices, func(i, j int) bool {
		cmp := remainders[indices[i]].Cmp(remainders[indices[j]])
		if cmp == 0 {
			return result[indices[i]].UserID < result[indices[j]].UserID
		}
		return cmp > 0
	})
	for i := int64(0); i < left; i++ {
		result[indices[i%int64(len(indices))]].Cents++
	}

	denomDecimal := decimal.NewFromBigInt(totalUnits, 0)
	for i := range result {
		percent := decimal.NewFromBigInt(result[i].Units, 0).
			DivRound(denomDecimal, 20).Mul(decimal.NewFromInt(100))
		result[i].SharePercent = percent.StringFixed(8)
	}
	return result, totalUnits, nil
}
