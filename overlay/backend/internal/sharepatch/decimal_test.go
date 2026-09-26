package sharepatch

import (
	"math/big"
	"testing"
)

func TestAllocateCentsUsesExactMaximumRemainders(t *testing.T) {
	rows, total, err := allocateCents([]allocationInput{
		{UserID: 8, Units: big.NewInt(1)},
		{UserID: 3, Units: big.NewInt(1)},
		{UserID: 5, Units: big.NewInt(1)},
	}, 2)
	if err != nil {
		t.Fatal(err)
	}
	if total.Cmp(big.NewInt(3)) != 0 {
		t.Fatalf("total units = %s, want 3", total)
	}
	if rows[0].UserID != 3 || rows[0].Cents != 1 || rows[1].UserID != 5 || rows[1].Cents != 1 || rows[2].UserID != 8 || rows[2].Cents != 0 {
		t.Fatalf("tie remainder was not assigned by user ID: %#v", rows)
	}
	if rows[0].Cents+rows[1].Cents+rows[2].Cents != 2 {
		t.Fatal("allocated cents do not sum to the configured total")
	}
}

func TestAllocateCentsSplitsZeroUsageAndOddRemainderByUserID(t *testing.T) {
	rows, _, err := allocateCents([]allocationInput{
		{UserID: 12, Units: new(big.Int)},
		{UserID: 2, Units: new(big.Int)},
		{UserID: 7, Units: new(big.Int)},
	}, 5)
	if err != nil {
		t.Fatal(err)
	}
	want := []struct {
		id    int64
		cents int64
	}{{2, 2}, {7, 2}, {12, 1}}
	for i := range want {
		if rows[i].UserID != want[i].id || rows[i].Cents != want[i].cents {
			t.Fatalf("row %d = user %d cents %d, want user %d cents %d", i, rows[i].UserID, rows[i].Cents, want[i].id, want[i].cents)
		}
	}
}

func TestDecimalUnitsAndCNYCentsNeverUseBinaryFloat(t *testing.T) {
	units, err := decimalUnits("0.30000001")
	if err != nil || units.String() != "30000001" {
		t.Fatalf("decimalUnits = %v, %v; want 30000001", units, err)
	}
	if _, err := decimalUnits("0.000000001"); err == nil {
		t.Fatal("decimalUnits accepted more than eight fractional places")
	}
	cents, err := parseCNYCents("12.30")
	if err != nil || cents != 1230 {
		t.Fatalf("parseCNYCents = %d, %v; want 1230", cents, err)
	}
	if _, err := parseCNYCents("12.301"); err == nil {
		t.Fatal("parseCNYCents accepted a fractional fen")
	}
}
