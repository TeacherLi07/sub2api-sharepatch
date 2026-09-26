package sharepatch

import "sync/atomic"

var unifiedBillingRequired atomic.Bool

// EnableUnifiedBillingRequirement disables the upstream best-effort fallback
// once the sharepatch migration and database guards are installed.
func EnableUnifiedBillingRequirement() {
	unifiedBillingRequired.Store(true)
}

// UnifiedBillingRequired reports whether balance billing must go through the
// transaction that claims the upstream billing idempotency key.
func UnifiedBillingRequired() bool {
	return unifiedBillingRequired.Load()
}
