package routes

import (
	"net/http"
	"testing"

	"github.com/Wei-Shaw/sub2api/internal/service"
	"github.com/stretchr/testify/require"
)

// Exercise the real OAuth transport and RegisterMCPRoutes private router. The
// outer /mcp URL is permitted; the dispatched billing operation must be denied
// before it reaches the handler (whose service is deliberately unconfigured).
func TestSharepatchMCPRejectsUnsupportedBillingOperations(t *testing.T) {
	f := newMCPOAuthHTTPFixture(t, service.RoleAdmin)
	_, tokens := f.authorize(t, service.MCPScopeAdmin, false)
	for _, test := range []struct {
		name string
		args map[string]any
	}{
		{"admin_update_user_balance", map[string]any{"id": 7, "idempotency_key": "balance-test", "body": map[string]any{"balance": 1, "operation": "add", "notes": "test"}}},
		{"admin_assign_subscription", map[string]any{"body": map[string]any{"user_id": 7, "group_id": 1, "validity_days": 30}}},
		{"admin_extend_subscription", map[string]any{"id": 1, "idempotency_key": "extend-test", "body": map[string]any{"days": 30}}},
		{"admin_revoke_subscription", map[string]any{"id": 1}},
	} {
		t.Run(test.name, func(t *testing.T) {
			response := f.rpc(t, tokens.AccessToken, "tools/call", map[string]any{"name": test.name, "arguments": test.args})
			require.Equal(t, http.StatusOK, response.status, string(response.body))
			result := decodeMCPRouteToolResult(t, response.body)
			require.True(t, result.Result.IsError)
			require.Equal(t, http.StatusForbidden, result.Result.Payload.HTTPStatus)
			require.Contains(t, string(result.Result.Payload.Result), "disabled in shared-billing mode")
		})
	}

	// Read-only key management remains available through the same protected router.
	response := f.rpc(t, tokens.AccessToken, "tools/call", map[string]any{"name": "user_get_api_key", "arguments": map[string]any{"id": 9}})
	require.Equal(t, http.StatusOK, response.status)
	result := decodeMCPRouteToolResult(t, response.body)
	require.False(t, result.Result.IsError)
	require.Equal(t, http.StatusOK, result.Result.Payload.HTTPStatus)
}
