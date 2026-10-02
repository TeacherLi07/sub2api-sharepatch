package sharepatch

import (
	"encoding/json"
	"math"
	"math/big"
	"testing"
	"time"
)

func TestCurrentCNYEstimatesPreserveRemaindersAtAndAfterMonthEnd(t *testing.T) {
	rows, total, err := allocateCents([]allocationInput{
		{UserID: 1, Units: big.NewInt(1)}, {UserID: 2, Units: big.NewInt(1)}, {UserID: 3, Units: big.NewInt(1)},
	}, 2)
	if err != nil {
		t.Fatal(err)
	}
	start := time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC)
	end := expectedMonthEnd(start, time.UTC)
	for _, asOf := range []time.Time{end, end.Add(48 * time.Hour)} {
		for i, row := range rows {
			whole, prorated := currentCNYEstimates(row, total, 2, elapsedInMonth(start, end, asOf), end.Sub(start))
			want := []string{"0.01", "0.01", "0.00"}[i]
			if whole == nil || prorated == nil || *whole != want || *prorated != want {
				t.Fatalf("user %d estimates = %v, %v; want both %s", row.UserID, whole, prorated, want)
			}
		}
	}
}

func TestZeroUsagePreviewAmountsAreNullButSettlementStillAllocates(t *testing.T) {
	rows, total, err := allocateCents([]allocationInput{{UserID: 1, Units: new(big.Int)}}, 100)
	if err != nil || rows[0].Cents != 100 {
		t.Fatalf("zero usage settlement allocation = %v, %v", rows, err)
	}
	whole, prorated := currentCNYEstimates(rows[0], total, 100, time.Hour, 30*24*time.Hour)
	data, err := json.Marshal(CurrentBillLine{BillLine: BillLine{AmountCNY: "1.00"}, AmountCNY: whole, ProratedAmountCNY: prorated})
	if err != nil {
		t.Fatal(err)
	}
	var payload map[string]any
	if err := json.Unmarshal(data, &payload); err != nil {
		t.Fatal(err)
	}
	for _, field := range []string{"amount_cny", "prorated_amount_cny"} {
		if value, ok := payload[field]; !ok || value != nil {
			t.Fatalf("%s = %v, present = %t; want explicit null", field, value, ok)
		}
	}
}

func TestExpectedMonthEnd(t *testing.T) {
	for _, tc := range []struct {
		name, zone, start, end string
	}{
		{"same day and time", "Asia/Shanghai", "2026-10-02T14:15:16.123456789+08:00", "2026-11-02T14:15:16.123456789+08:00"},
		{"short February", "Asia/Shanghai", "2026-01-31T14:15:16+08:00", "2026-02-28T14:15:16+08:00"},
		{"leap February", "Asia/Shanghai", "2028-01-30T14:15:16+08:00", "2028-02-29T14:15:16+08:00"},
		{"30 day month", "Asia/Shanghai", "2026-03-31T14:15:16+08:00", "2026-04-30T14:15:16+08:00"},
		{"year rollover", "Asia/Shanghai", "2026-12-31T14:15:16+08:00", "2027-01-31T14:15:16+08:00"},
		{"billing day differs from UTC", "Asia/Shanghai", "2026-01-30T18:15:16Z", "2026-02-28T02:15:16+08:00"},
		{"daylight saving elapsed hours", "America/New_York", "2026-03-01T14:15:16-05:00", "2026-04-01T14:15:16-04:00"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			location, err := time.LoadLocation(tc.zone)
			if err != nil {
				t.Fatal(err)
			}
			start, err := time.Parse(time.RFC3339Nano, tc.start)
			if err != nil {
				t.Fatal(err)
			}
			want, err := time.Parse(time.RFC3339Nano, tc.end)
			if err != nil {
				t.Fatal(err)
			}
			if got := expectedMonthEnd(start, location); !got.Equal(want) {
				t.Fatalf("end = %s, want %s", got, want)
			}
		})
	}
}

func TestElapsedInMonthClampsToCycle(t *testing.T) {
	start := time.Date(2026, 10, 2, 3, 4, 5, 0, time.UTC)
	end := expectedMonthEnd(start, time.UTC)
	duration := end.Sub(start)
	for _, tc := range []struct {
		asOf time.Time
		want time.Duration
	}{
		{start.Add(-time.Hour), 0}, {start, 0},
		{start.Add(duration / 2), duration / 2},
		{end, duration}, {end.Add(100 * 24 * time.Hour), duration},
	} {
		if got := elapsedInMonth(start, end, tc.asOf); got != tc.want {
			t.Fatalf("elapsed at %s = %s, want %s", tc.asOf, got, tc.want)
		}
	}
}

func TestProratedCNYUsesExactUsageAndTimeBeforeRounding(t *testing.T) {
	for _, tc := range []struct {
		name, units, total       string
		cents, elapsed, duration int64
		want                     string
	}{
		{"ten percent usage at half month", "1", "10", 100000, 15, 30, "50.00"},
		{"only user at first day", "1", "1", 30000, 1, 30, "10.00"},
		{"not rounded whole-month amount", "1", "3", 2, 2, 3, "0.00"},
		{"half cent rounds up", "1", "2", 2, 1, 2, "0.01"},
		{"zero user usage", "0", "10", 100000, 15, 30, "0.00"},
		{"zero elapsed", "1", "10", 100000, 0, 30, "0.00"},
		{"zero total", "0", "0", 100000, 15, 30, ""},
		{"zero amount", "1", "10", 0, 15, 30, "0.00"},
		{"large exact multiplication", "100000000000000000000", "100000000000000000000", math.MaxInt64, 2678400000000000, 2678400000000000, "92233720368547758.07"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			units, _ := new(big.Int).SetString(tc.units, 10)
			total, _ := new(big.Int).SetString(tc.total, 10)
			got := proratedCNY(units, total, tc.cents, time.Duration(tc.elapsed), time.Duration(tc.duration))
			if tc.want == "" {
				if got != nil {
					t.Fatalf("zero usage estimate = %s, want nil", *got)
				}
			} else if got == nil || *got != tc.want {
				t.Fatalf("estimate = %v, want %s", got, tc.want)
			}
			if units.String() != tc.units || total.String() != tc.total {
				t.Fatal("estimate mutated usage inputs")
			}
		})
	}
}
