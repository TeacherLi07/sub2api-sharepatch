package sharepatch

import (
	"context"
	"database/sql"
	"errors"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/Wei-Shaw/sub2api/internal/pkg/response"
	"github.com/gin-gonic/gin"
)

type Handler struct {
	store           *Store
	standardBilling bool
	active          atomic.Bool
	refreshed       atomic.Int64
	refreshMu       sync.Mutex
}

func NewHandler(db *sql.DB, runMode string) (*Handler, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	store, err := NewStore(ctx, db)
	if err != nil {
		return nil, err
	}
	h := &Handler{store: store, standardBilling: runMode == "standard"}
	active, _, err := store.Status(ctx)
	if err != nil {
		return nil, err
	}
	h.active.Store(active)
	h.refreshed.Store(time.Now().UnixNano())
	EnableUnifiedBillingRequirement()
	sharepatchLogger.Info("handler ready", "active", active, "standard_billing", h.standardBilling)
	return h, nil
}

func (h *Handler) Dashboard(c *gin.Context) {
	dashboard, err := h.store.Dashboard(c.Request.Context())
	if err != nil {
		sharepatchLogger.Error("dashboard request failed", "error", safeSharepatchError(err))
		response.Error(c, http.StatusInternalServerError, "failed to load shared billing dashboard")
		return
	}
	sharepatchLogger.Debug("dashboard loaded", "active", dashboard.Active, "history_count", len(dashboard.History))
	response.Success(c, dashboard)
}

func (h *Handler) AdminStatus(c *gin.Context) {
	dashboard, err := h.store.Dashboard(c.Request.Context())
	if err != nil {
		sharepatchLogger.Error("admin dashboard request failed", "error", safeSharepatchError(err))
		response.Error(c, http.StatusInternalServerError, "failed to load shared billing status")
		return
	}
	sharepatchLogger.Debug("admin dashboard loaded", "active", dashboard.Active, "history_count", len(dashboard.History))
	response.Success(c, dashboard)
}

type activationRequest struct {
	StartsAt         string `json:"starts_at" binding:"required"`
	TotalCNY         string `json:"total_cny" binding:"required"`
	ConfirmIntegrity bool   `json:"confirm_usage_log_integrity"`
}

func (h *Handler) ActivationPreview(c *gin.Context) {
	var req activationRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "starts_at and total_cny are required")
		return
	}
	startsAt, amountCents, err := parseActivationRequest(req)
	if err != nil {
		response.BadRequest(c, err.Error())
		return
	}
	preview, err := h.store.PreviewActivation(c.Request.Context(), startsAt, amountCents)
	if err != nil {
		sharepatchLogger.Warn("activation preview failed", "error", safeSharepatchError(err))
		response.BadRequest(c, err.Error())
		return
	}
	codes := make([]string, 0, len(preview.Blockers))
	for _, blocker := range preview.Blockers {
		codes = append(codes, blocker.Code)
	}
	sharepatchLogger.Info("activation preview completed", "active", preview.Active, "user_count", len(preview.Users), "blocker_count", len(codes), "blocker_codes", codes)
	response.Success(c, preview)
}

func (h *Handler) Activate(c *gin.Context) {
	if !h.standardBilling {
		sharepatchLogger.Warn("activation rejected outside standard billing mode")
		response.Error(c, http.StatusConflict, "shared billing can only be activated in standard mode")
		return
	}
	var req activationRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "starts_at and total_cny are required")
		return
	}
	startsAt, amountCents, err := parseActivationRequest(req)
	if err != nil {
		response.BadRequest(c, err.Error())
		return
	}
	cycle, err := h.store.Activate(c.Request.Context(), startsAt, amountCents, req.ConfirmIntegrity)
	if err != nil {
		sharepatchLogger.Error("activation failed", "error", safeSharepatchError(err))
		response.Error(c, http.StatusConflict, err.Error())
		return
	}
	h.active.Store(true)
	h.refreshed.Store(time.Now().UnixNano())
	sharepatchLogger.Info("activation completed", "cycle_id", cycle.ID, "starts_at", cycle.StartsAt)
	response.Success(c, cycle)
}

type amountRequest struct {
	TotalCNY string `json:"total_cny" binding:"required"`
}

func (h *Handler) SetCurrentAmount(c *gin.Context) {
	if !h.standardBilling {
		sharepatchLogger.Warn("cycle amount update rejected outside standard billing mode")
		response.Error(c, http.StatusConflict, "shared billing requires standard mode")
		return
	}
	var req amountRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "total_cny is required")
		return
	}
	cents, err := checkAmountString(req.TotalCNY)
	if err != nil {
		response.BadRequest(c, err.Error())
		return
	}
	cycle, err := h.store.SetCurrentAmount(c.Request.Context(), cents)
	if err != nil {
		sharepatchLogger.Error("cycle amount update failed", "error", safeSharepatchError(err))
		response.Error(c, http.StatusConflict, err.Error())
		return
	}
	sharepatchLogger.Info("cycle amount updated", "cycle_id", cycle.ID)
	response.Success(c, cycle)
}

func (h *Handler) Settle(c *gin.Context) {
	if !h.standardBilling {
		sharepatchLogger.Warn("settlement rejected outside standard billing mode")
		response.Error(c, http.StatusConflict, "shared billing requires standard mode")
		return
	}
	ledger, err := h.store.Settle(c.Request.Context(), c.GetHeader("Idempotency-Key"))
	if err != nil {
		sharepatchLogger.Error("settlement failed", "error", safeSharepatchError(err))
		response.Error(c, http.StatusConflict, err.Error())
		return
	}
	sharepatchLogger.Info("settlement completed", "cycle_id", ledger.Cycle.ID, "line_count", len(ledger.Lines))
	response.Success(c, ledger)
}

func parseActivationRequest(req activationRequest) (time.Time, int64, error) {
	startsAt, err := time.Parse(time.RFC3339Nano, strings.TrimSpace(req.StartsAt))
	if err != nil {
		return time.Time{}, 0, errors.New("starts_at must be an RFC3339 timestamp with a timezone offset")
	}
	cents, err := checkAmountString(req.TotalCNY)
	if err != nil {
		return time.Time{}, 0, err
	}
	return startsAt.UTC(), cents, nil
}

func (h *Handler) Gate() gin.HandlerFunc {
	return func(c *gin.Context) {
		path := c.Request.URL.Path
		if blockedSharepatchPath(path, c.Request.Method) {
			response.Error(c, http.StatusForbidden, "this operation is disabled in shared-billing mode")
			c.Abort()
			return
		}
		if !isGatewayPath(path) {
			c.Next()
			return
		}
		if !h.standardBilling {
			sharepatchLogger.Warn("gateway request rejected outside standard billing mode", "path", c.Request.URL.Path)
			response.Error(c, http.StatusServiceUnavailable, "gateway billing is paused because shared billing requires standard mode")
			c.Abort()
			return
		}
		active, err := h.isActive(c.Request.Context())
		if err != nil {
			response.Error(c, http.StatusServiceUnavailable, "shared-billing status is unavailable")
			c.Abort()
			return
		}
		if !active {
			sharepatchLogger.Info("gateway request rejected while activation is pending", "path", c.Request.URL.Path)
			response.Error(c, http.StatusServiceUnavailable, "gateway billing is paused until an administrator activates shared billing")
			c.Abort()
			return
		}
		sharepatchLogger.Debug("gateway request allowed", "path", c.Request.URL.Path)
		c.Next()
	}
}

func (h *Handler) isActive(ctx context.Context) (bool, error) {
	now := time.Now().UnixNano()
	if now-h.refreshed.Load() < int64(time.Second) {
		return h.active.Load(), nil
	}
	h.refreshMu.Lock()
	defer h.refreshMu.Unlock()
	now = time.Now().UnixNano()
	if now-h.refreshed.Load() < int64(time.Second) {
		return h.active.Load(), nil
	}
	active, _, err := h.store.Status(ctx)
	if err != nil {
		return false, err
	}
	h.active.Store(active)
	h.refreshed.Store(now)
	return active, nil
}

func isGatewayPath(path string) bool {
	for _, prefix := range []string{
		"/v1", "/v1beta", "/v3", "/api/v3", "/backend-api", "/antigravity", "/gemini",
		"/messages", "/responses", "/chat/completions", "/embeddings", "/images", "/models",
		"/alpha/search", "/contents", "/videos", "/tts", "/stt", "/custom-voices",
		"/realtime", "/web_search", "/x_search",
	} {
		if path == prefix || strings.HasPrefix(path, prefix+"/") {
			return true
		}
	}
	return false
}

func blockedSharepatchPath(path, method string) bool {
	for _, prefix := range []string{"/v1/images/batches", "/v3/images/batches", "/api/v3/images/batches", "/images/batches"} {
		if path == prefix || strings.HasPrefix(path, prefix+"/") {
			return true
		}
	}
	if strings.HasPrefix(path, "/api/v1/payment") || strings.HasPrefix(path, "/api/v1/admin/payment") ||
		strings.HasPrefix(path, "/api/v1/batch-image") || strings.HasPrefix(path, "/api/v1/batch-images") {
		return true
	}
	if path == "/api/v1/redeem" && method == http.MethodPost {
		return true
	}
	if path == "/api/v1/user/aff/transfer" && method == http.MethodPost {
		return true
	}
	if strings.HasPrefix(path, "/api/v1/admin/redeem-codes") || strings.HasPrefix(path, "/api/v1/admin/promo-codes") ||
		strings.HasPrefix(path, "/api/v1/admin/subscriptions") {
		return true
	}
	if strings.HasPrefix(path, "/api/v1/admin/users/") && strings.HasSuffix(path, "/balance") {
		return true
	}
	return false
}
