package routes

import (
	"github.com/Wei-Shaw/sub2api/internal/server/middleware"
	"github.com/Wei-Shaw/sub2api/internal/sharepatch"
	"github.com/gin-gonic/gin"
)

func RegisterSharepatchRoutes(
	v1 *gin.RouterGroup,
	h *sharepatch.Handler,
	jwtAuth middleware.JWTAuthMiddleware,
	adminAuth middleware.AdminAuthMiddleware,
	auditLog middleware.AuditLogMiddleware,
) {
	users := v1.Group("/sharepatch")
	users.Use(gin.HandlerFunc(jwtAuth))
	users.GET("/dashboard", h.Dashboard)

	admin := v1.Group("/admin/sharepatch")
	admin.Use(gin.HandlerFunc(adminAuth), gin.HandlerFunc(auditLog))
	admin.GET("/status", h.AdminStatus)
	admin.POST("/activation-preview", h.ActivationPreview)
	admin.POST("/activate", h.Activate)
	admin.PUT("/current-amount", h.SetCurrentAmount)
	admin.POST("/settlements", h.Settle)
}
