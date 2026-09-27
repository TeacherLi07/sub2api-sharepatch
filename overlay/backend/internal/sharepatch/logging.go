package sharepatch

import (
	"log/slog"
	"os"
	"regexp"
	"strings"
)

var sharepatchLogger = newSharepatchLogger()
var sharepatchEmailPattern = regexp.MustCompile(`(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b`)

func safeSharepatchError(err error) string {
	if err == nil {
		return ""
	}
	return sharepatchEmailPattern.ReplaceAllString(err.Error(), "[redacted-email]")
}

func newSharepatchLogger() *slog.Logger {
	var level slog.Level
	switch strings.ToLower(strings.TrimSpace(os.Getenv("SHAREPATCH_LOG_LEVEL"))) {
	case "", "info":
		level = slog.LevelInfo
	case "debug":
		level = slog.LevelDebug
	case "warn", "warning":
		level = slog.LevelWarn
	case "error":
		level = slog.LevelError
	default:
		level = slog.LevelInfo
		slog.Warn("invalid SHAREPATCH_LOG_LEVEL; using info", "value", os.Getenv("SHAREPATCH_LOG_LEVEL"))
	}
	return slog.New(slog.NewJSONHandler(os.Stderr, &slog.HandlerOptions{Level: level})).With("component", "sharepatch")
}
