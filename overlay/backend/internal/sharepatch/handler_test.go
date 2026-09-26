package sharepatch

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestGatewayPathDetectionCoversRootAliasesAndVersionedRoutes(t *testing.T) {
	for _, path := range []string{
		"/v1/messages",
		"/v1beta/models/gemini-2.5:generateContent",
		"/responses",
		"/chat/completions",
		"/backend-api/codex/responses",
		"/images/generations",
		"/videos/generations",
		"/realtime",
	} {
		if !isGatewayPath(path) {
			t.Errorf("isGatewayPath(%q) = false", path)
		}
	}
	for _, path := range []string{"/health", "/api/v1/sharepatch/dashboard", "/dashboard"} {
		if isGatewayPath(path) {
			t.Errorf("isGatewayPath(%q) = true", path)
		}
	}
}

func TestSimpleModeGateDoesNotAllowUnmeteredGatewayTraffic(t *testing.T) {
	gin.SetMode(gin.TestMode)
	handler := &Handler{standardBilling: false}
	handler.active.Store(true)
	called := false
	router := gin.New()
	router.Use(handler.Gate())
	router.POST("/v1/messages", func(c *gin.Context) {
		called = true
		c.Status(http.StatusOK)
	})
	response := httptest.NewRecorder()
	router.ServeHTTP(response, httptest.NewRequest(http.MethodPost, "/v1/messages", nil))
	if response.Code != http.StatusServiceUnavailable || called {
		t.Fatalf("simple mode gateway status=%d called=%t, want 503 and no handler call", response.Code, called)
	}
}

func TestBalanceAndUnsupportedFeatureRoutesAreBlocked(t *testing.T) {
	tests := []struct {
		path   string
		method string
	}{
		{"/api/v1/payment/orders", http.MethodPost},
		{"/api/v1/admin/payment/config", http.MethodPut},
		{"/api/v1/admin/users/12/balance", http.MethodPost},
		{"/api/v1/redeem", http.MethodPost},
		{"/api/v1/user/aff/transfer", http.MethodPost},
		{"/v1/images/batches", http.MethodPost},
		{"/v1/images/batches/abc/items", http.MethodGet},
	}
	for _, test := range tests {
		if !blockedSharepatchPath(test.path, test.method) {
			t.Errorf("blockedSharepatchPath(%q, %q) = false", test.path, test.method)
		}
	}
	if blockedSharepatchPath("/api/v1/sharepatch/dashboard", http.MethodGet) {
		t.Fatal("shared billing dashboard was blocked")
	}
}
