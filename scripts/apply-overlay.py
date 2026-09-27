#!/usr/bin/env python3
"""Apply the sharepatch overlay to one exact Sub2API release checkout."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PINNED_BASELINE = "fd80b08c90b55edcad5b00171b53f08721d30da1"


def fail(message: str) -> None:
    raise SystemExit(f"apply-overlay: {message}")


def run(*args: str, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(args, cwd=cwd, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        fail(f"command failed ({' '.join(args)}): {exc.stderr.strip()}")
    return result.stdout.strip()


def patch_text(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected one anchor in {path}, found {count}")
    path.write_text(text.replace(old, new, 1))


def patch_all(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        if new in text:
            return
        fail(f"{label}: anchor is missing in {path}")
    path.write_text(text.replace(old, new))


def remove_text(path: Path, old: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        return
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected one anchor in {path}, found {count}")
    path.write_text(text.replace(old, "", 1))


def patch_regex(path: Path, pattern: str, replacement: str, label: str, marker: str) -> None:
    text = path.read_text()
    if marker in text:
        return
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        fail(f"{label}: expected one regex anchor in {path}, found {count}")
    path.write_text(updated)


def copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        fail(f"overlay source directory is missing: {source}")
    shutil.copytree(source, destination, dirs_exist_ok=True)


def infer_github_repo() -> str:
    remote = run("git", "remote", "get-url", "origin", cwd=ROOT)
    match = re.search(r"github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?$", remote, re.IGNORECASE)
    if not match:
        fail(f"origin must be a GitHub owner/repository URL, got {remote!r}")
    return match.group(1)


def apply_backend(upstream: Path, patch_repo: str) -> None:
    backend = upstream / "backend"
    copy_tree(ROOT / "overlay/backend/internal/sharepatch", backend / "internal/sharepatch")
    routes_source = ROOT / "overlay/backend/internal/server/routes/sharepatch.go"
    if not routes_source.is_file():
        fail(f"overlay route file is missing: {routes_source}")
    shutil.copy2(routes_source, backend / "internal/server/routes/sharepatch.go")
    update_test = ROOT / "overlay/backend/internal/service/update_service_sharepatch_test.go"
    shutil.copy2(update_test, backend / "internal/service/update_service_sharepatch_test.go")

    handler_file = backend / "internal/handler/handler.go"
    patch_text(
        handler_file,
        '\t"github.com/Wei-Shaw/sub2api/internal/securityaudit"\n',
        '\t"github.com/Wei-Shaw/sub2api/internal/securityaudit"\n'
        '\t"github.com/Wei-Shaw/sub2api/internal/sharepatch"\n',
        "handler package import",
    )
    patch_regex(
        handler_file,
        r"(?m)^(\s*BatchImage\s+\*BatchImageHandler\s*)$",
        r"\1\n\tSharepatch *sharepatch.Handler",
        "sharepatch handler field",
        "Sharepatch *sharepatch.Handler",
    )

    handler_wire = backend / "internal/handler/wire.go"
    patch_text(
        handler_wire,
        "import (\n",
        'import (\n\t"database/sql"\n',
        "handler wire standard imports",
    )
    patch_text(
        handler_wire,
        '\t"github.com/Wei-Shaw/sub2api/internal/service"\n',
        '\t"github.com/Wei-Shaw/sub2api/internal/service"\n'
        '\t"github.com/Wei-Shaw/sub2api/internal/sharepatch"\n',
        "handler wire sharepatch import",
    )
    insert = (
        "func ProvideSharepatchHandler(db *sql.DB, cfg *config.Config) (*sharepatch.Handler, error) {\n"
        "\treturn sharepatch.NewHandler(db, cfg.RunMode)\n"
        "}\n\n"
    )
    wire_text = handler_wire.read_text()
    if "func ProvideSharepatchHandler(" not in wire_text:
        marker = "// ProviderSet is the Wire provider set for all handlers\n"
        at = wire_text.find(marker)
        if at < 0:
            fail("handler wire provider-set anchor is missing")
        wire_text = wire_text[:at] + insert + wire_text[at:]
        handler_wire.write_text(wire_text)

    patch_regex(
        handler_wire,
        r"(?m)^(\s*_\s+\*service\.OpenAIQuotaAutoResetService,)\n(\) \*Handlers \{)$",
        r"\tsharepatchHandler *sharepatch.Handler,\n\1\n\2",
        "ProvideHandlers dependency",
        "sharepatchHandler *sharepatch.Handler",
    )
    patch_regex(
        handler_wire,
        r"(?m)^(\s*BatchImage:\s+batchImageHandler,)\s*$",
        r"\1\n\t\tSharepatch: sharepatchHandler,",
        "ProvideHandlers sharepatch field",
        "Sharepatch: sharepatchHandler,",
    )
    patch_text(
        handler_wire,
        "\tProvideBatchImageHandler,\n",
        "\tProvideBatchImageHandler,\n\tProvideSharepatchHandler,\n",
        "sharepatch Wire provider registration",
    )

    router_file = backend / "internal/server/router.go"
    patch_text(
        router_file,
        "\troutes.RegisterPaymentRoutes(v1, h.Payment, h.PaymentWebhook, h.Admin.Payment, jwtAuth, adminAuth, auditLog, settingService, panelRateLimiter)\n",
        "\troutes.RegisterPaymentRoutes(v1, h.Payment, h.PaymentWebhook, h.Admin.Payment, jwtAuth, adminAuth, auditLog, settingService, panelRateLimiter)\n"
        "\troutes.RegisterSharepatchRoutes(v1, h.Sharepatch, jwtAuth, adminAuth, auditLog)\n",
        "shared billing API route registration",
    )
    admin_user_handler = backend / "internal/handler/admin/user_handler.go"
    patch_text(
        admin_user_handler,
        '\t"log/slog"\n',
        '\t"log/slog"\n\t"net/http"\n',
        "admin user delete status code import",
    )
    patch_text(
        admin_user_handler,
        "\terr = h.adminService.DeleteUser(c.Request.Context(), userID)\n\tif err != nil {\n\t\tresponse.ErrorFrom(c, err)\n\t\treturn\n\t}\n",
        "\terr = h.adminService.DeleteUser(c.Request.Context(), userID)\n\tif err != nil {\n"
        "\t\tif strings.Contains(err.Error(), \"user has current-cycle usage\") {\n"
        "\t\t\tresponse.Error(c, http.StatusConflict, \"This user has current-cycle usage; disable the account instead of deleting it.\")\n"
        "\t\t\treturn\n"
        "\t\t}\n\t\tresponse.ErrorFrom(c, err)\n\t\treturn\n\t}\n",
        "surface the consumed-user deletion guard",
    )
    http_file = backend / "internal/server/http.go"
    patch_text(
        http_file,
        "\tr.Use(middleware2.Recovery())\n",
        "\tr.Use(middleware2.Recovery())\n\tr.Use(handlers.Sharepatch.Gate())\n",
        "shared billing request gate",
    )

    billing_file = backend / "internal/repository/usage_billing_repo.go"
    patch_text(
        billing_file,
        "\tif !applied {\n\t\treturn &service.UsageBillingApplyResult{Applied: false}, nil\n\t}\n\n\tresult := &service.UsageBillingApplyResult{Applied: true}\n",
        "\tif !applied {\n\t\treturn &service.UsageBillingApplyResult{Applied: false}, nil\n\t}\n"
        "\tif cmd.BalanceCost > 0 {\n"
        "\t\tif _, err := tx.ExecContext(ctx, `SELECT set_config('sharepatch.billing', 'on', TRUE)`); err != nil {\n"
        "\t\t\treturn nil, err\n"
        "\t\t}\n"
        "\t}\n\n\tresult := &service.UsageBillingApplyResult{Applied: true}\n",
        "billing transaction marker",
    )

    legacy_file = backend / "internal/service/gateway_usage_billing.go"
    patch_text(
        legacy_file,
        '\t"github.com/Wei-Shaw/sub2api/internal/pkg/timezone"\n',
        '\t"github.com/Wei-Shaw/sub2api/internal/pkg/timezone"\n'
        '\t"github.com/Wei-Shaw/sub2api/internal/sharepatch"\n',
        "legacy billing patch mode import",
    )
    patch_text(
        legacy_file,
        "\t\t// The legacy path is only a fallback for standard billing. Simple mode\n"
        "\t\t// must retain request-id deduplication and never bill other balances.\n"
        "\t\tpostUsageBilling(ctx, p, deps)\n"
        "\t\treturn true, nil\n",
        "\t\t// Sharepatch activates fail-closed billing here; upstream unit/degraded tests retain the fallback.\n"
        "\t\tif sharepatch.UnifiedBillingRequired() {\n"
        "\t\t\treturn false, errors.New(\"unified usage billing repository unavailable; refusing legacy balance deduction\")\n"
        "\t\t}\n"
        "\t\tpostUsageBilling(ctx, p, deps)\n"
        "\t\treturn true, nil\n",
        "disable legacy billing fallback only in sharepatch mode",
    )

    auth_service = backend / "internal/service/auth_service.go"
    patch_text(
        auth_service,
        "func (s *AuthService) resolveSignupGrantPlan(ctx context.Context, signupSource string) signupGrantPlan {\n\tplan := signupGrantPlan{}\n",
        "func (s *AuthService) resolveSignupGrantPlan(ctx context.Context, signupSource string) (plan signupGrantPlan) {\n"
        "\tsharedBilling := s.sharedBillingActive(ctx)\n"
        "\tdefer func() {\n"
        "\t\tif sharedBilling {\n"
        "\t\t\tplan.Balance = 10000000\n"
        "\t\t\tplan.Subscriptions = nil\n"
        "\t\t}\n"
        "\t}()\n"
        "\tplan = signupGrantPlan{}\n",
        "shared billing signup grants",
    )
    if "func (s *AuthService) sharedBillingActive(ctx context.Context) bool" not in auth_service.read_text():
        helper = (
            "func (s *AuthService) sharedBillingActive(ctx context.Context) bool {\n"
            "\tif s == nil || s.entClient == nil {\n\t\treturn false\n\t}\n"
            "\trows, err := s.entClient.QueryContext(ctx, `SELECT active FROM sharepatch_state WHERE id = 1`)\n"
            "\tif err != nil {\n\t\treturn false\n\t}\n"
            "\tdefer rows.Close()\n"
            "\tif !rows.Next() {\n\t\treturn false\n\t}\n"
            "\tvar active bool\n"
            "\treturn rows.Scan(&active) == nil && active\n"
            "}\n\n"
        )
        marker = "func (s *AuthService) resolveSignupGrantPlan(ctx context.Context, signupSource string) (plan signupGrantPlan) {\n"
        patch_text(auth_service, marker, helper + marker, "shared billing state helper")
    patch_text(
        auth_service,
        "if promoCode != \"\" && s.promoService != nil && s.settingService != nil && s.settingService.IsPromoCodeEnabled(ctx) {",
        "if promoCode != \"\" && !s.sharedBillingActive(ctx) && s.promoService != nil && s.settingService != nil && s.settingService.IsPromoCodeEnabled(ctx) {",
        "disable signup promo credits",
    )
    patch_text(
        auth_service,
        "if user == nil || user.ID <= 0 || promoCode == \"\" || s.promoService == nil || s.settingService == nil || !s.settingService.IsPromoCodeEnabled(ctx) {",
        "if user == nil || user.ID <= 0 || promoCode == \"\" || s.sharedBillingActive(ctx) || s.promoService == nil || s.settingService == nil || !s.settingService.IsPromoCodeEnabled(ctx) {",
        "disable OAuth signup promo credits",
    )
    first_bind = backend / "internal/service/auth_oauth_first_bind.go"
    patch_text(
        first_bind,
        "\tif !enabled {\n\t\treturn nil\n\t}\n\n\tclient := s.entClient\n",
        "\tif !enabled {\n\t\treturn nil\n\t}\n"
        "\tif s.sharedBillingActive(ctx) {\n"
        "\t\tproviderDefaults.Balance = 0\n"
        "\t\tproviderDefaults.Subscriptions = nil\n"
        "\t}\n\n\tclient := s.entClient\n",
        "disable first-bind credits and subscriptions",
    )

    update_service = backend / "internal/service/update_service.go"
    patch_text(
        update_service,
        'githubRepo     = "Wei-Shaw/sub2api"',
        f'githubRepo     = "{patch_repo}"',
        "bind updater to patch repository",
    )
    old_compare = (
        "func compareVersions(current, latest string) int {\n"
        "\tcurrentParts := parseVersion(current)\n"
        "\tlatestParts := parseVersion(latest)\n\n"
        "\tfor i := 0; i < 3; i++ {\n"
        "\t\tif currentParts[i] < latestParts[i] {\n"
        "\t\t\treturn -1\n"
        "\t\t}\n"
        "\t\tif currentParts[i] > latestParts[i] {\n"
        "\t\t\treturn 1\n"
        "\t\t}\n"
        "\t}\n"
        "\treturn 0\n"
        "}\n"
    )
    new_compare = (
        "func compareVersions(current, latest string) int {\n"
        "\tcurrentParts := parseVersion(current)\n"
        "\tlatestParts := parseVersion(latest)\n"
        "\tfor i := 0; i < 3; i++ {\n"
        "\t\tif currentParts[i] < latestParts[i] { return -1 }\n"
        "\t\tif currentParts[i] > latestParts[i] { return 1 }\n"
        "\t}\n"
        "\tcurrentRevision, currentIsShare := parseSharepatchRevision(current)\n"
        "\tlatestRevision, latestIsShare := parseSharepatchRevision(latest)\n"
        "\tif currentIsShare != latestIsShare {\n"
        "\t\tif currentIsShare { return 1 }; return -1\n"
        "\t}\n"
        "\tif currentRevision < latestRevision { return -1 }\n"
        "\tif currentRevision > latestRevision { return 1 }\n"
        "\treturn 0\n"
        "}\n\n"
        "func parseSharepatchRevision(version string) (int, bool) {\n"
        "\tversion = strings.TrimPrefix(version, \"v\")\n"
        "\tmarker := \"-share.\"\n"
        "\tindex := strings.LastIndex(version, marker)\n"
        "\tif index < 0 { return 0, false }\n"
        "\trevision, err := strconv.Atoi(version[index+len(marker):])\n"
        "\tif err != nil || revision < 0 { return 0, false }\n"
        "\treturn revision, true\n"
        "}\n"
    )
    patch_text(update_service, old_compare, new_compare, "sharepatch-aware version comparison")

    dockerfile = upstream / "Dockerfile"
    patch_text(
        dockerfile,
        'LABEL org.opencontainers.image.source="https://github.com/Wei-Shaw/sub2api"',
        f'LABEL org.opencontainers.image.source="https://github.com/{patch_repo}"',
        "container source label",
    )
    patch_text(
        dockerfile,
        "ARG GOLANG_IMAGE=golang:1.27.0-alpine",
        "ARG GOLANG_IMAGE=golang:1.27.1-alpine",
        "use the verified Go patch release in Docker builds",
    )
    patch_text(
        dockerfile,
        "CGO_ENABLED=0 GOOS=${TARGETOS:-linux} GOARCH=${TARGETARCH} go build \\\n",
        "CGO_ENABLED=0 GOOS=${TARGETOS:-linux} GOARCH=${TARGETARCH} go build -p=2 \\\n",
        "bound Docker Go build parallelism",
    )
    image = f"ghcr.io/{patch_repo.lower()}:latest"
    for compose_name in ("docker-compose.yml", "docker-compose.local.yml", "docker-compose.standalone.yml"):
        compose = upstream / "deploy" / compose_name
        patch_text(
            compose,
            "    image: weishaw/sub2api:latest",
            f"    image: {image}",
            f"point {compose_name} at the sharepatch image",
        )
    docker_doc = upstream / "deploy/DOCKER.md"
    patch_all(
        docker_doc,
        "weishaw/sub2api:latest",
        image,
        "Docker documentation image reference",
    )

    gofmt_files = [
        handler_file,
        handler_wire,
        router_file,
        http_file,
        admin_user_handler,
        billing_file,
        legacy_file,
        auth_service,
        first_bind,
        update_service,
        backend / "internal/server/routes/sharepatch.go",
        backend / "internal/sharepatch/activation.go",
        backend / "internal/sharepatch/decimal.go",
        backend / "internal/sharepatch/handler.go",
        backend / "internal/sharepatch/handler_test.go",
        backend / "internal/sharepatch/logging.go",
        backend / "internal/sharepatch/mode.go",
        backend / "internal/sharepatch/postgres_integration_test.go",
        backend / "internal/sharepatch/settlement.go",
        backend / "internal/sharepatch/store.go",
        backend / "internal/sharepatch/decimal_test.go",
        backend / "internal/service/update_service_sharepatch_test.go",
    ]
    run("gofmt", "-w", *[str(path) for path in gofmt_files], cwd=upstream)


def apply_frontend(upstream: Path) -> None:
    frontend = upstream / "frontend/src"
    copy_tree(ROOT / "overlay/frontend/src/sharepatch", frontend / "sharepatch")

    app_header = frontend / "components/layout/AppHeader.vue"
    header_summary = (
        "        <div\n"
        "          v-if=\"user && !authStore.isSimpleMode\"\n"
        "          class=\"group relative hidden items-center gap-2 rounded-xl bg-primary-50 px-3 py-1.5 dark:bg-primary-900/20 sm:flex\"\n"
        "        >\n"
        "          <span class=\"text-xs text-primary-700 dark:text-primary-300\">当期消费</span>\n"
        "          <span class=\"text-sm font-semibold text-primary-700 dark:text-primary-300\">{{ formatHeaderMoney(currentPeriodSpend) }}</span>\n"
        "          <div class=\"pointer-events-none absolute right-0 top-full mt-2 hidden w-60 rounded-lg border border-gray-200 bg-white p-3 text-xs shadow-lg group-hover:block dark:border-dark-700 dark:bg-dark-800\">\n"
        "            <div class=\"flex items-center justify-between\">\n"
        "              <span class=\"text-gray-500 dark:text-dark-400\">当期消费</span>\n"
        "              <span class=\"font-medium text-gray-900 dark:text-white\">{{ formatHeaderMoney(currentPeriodSpend) }}</span>\n"
        "            </div>\n"
        "            <div class=\"mt-2 flex items-center justify-between\">\n"
        "              <span class=\"text-gray-500 dark:text-dark-400\">当期预计分摊</span>\n"
        "              <span class=\"font-semibold text-gray-900 dark:text-white\">{{ formatHeaderCNY(expectedPeriodShare) }}</span>\n"
        "            </div>\n"
        "            <p v-if=\"!sharedBillingActive\" class=\"mt-2 border-t border-gray-100 pt-2 text-gray-500 dark:border-dark-700 dark:text-dark-400\">共享计费尚未激活</p>\n"
        "          </div>\n"
        "        </div>\n"
    )
    patch_text(
        app_header,
        "        <!-- Balance Display -->\n",
        "        <!-- Current period consumption -->\n" + header_summary + "        <!-- Balance Display -->\n",
        "add current consumption to desktop header",
    )
    patch_text(
        app_header,
        "        <!-- Balance Display -->\n        <div\n          v-if=\"user\"\n",
        "        <!-- Balance Display -->\n        <div\n          v-if=\"user && authStore.isSimpleMode\"\n",
        "keep simple-mode balance display",
    )
    mobile_header_summary = (
        "              <!-- Current consumption (mobile) -->\n"
        "              <div v-if=\"!authStore.isSimpleMode\" class=\"border-b border-gray-100 px-4 py-2 dark:border-dark-700 sm:hidden\">\n"
        "                <div class=\"flex items-center justify-between text-xs text-gray-500 dark:text-dark-400\">\n"
        "                  <span>当期消费</span><span class=\"font-semibold text-primary-600 dark:text-primary-400\">{{ formatHeaderMoney(currentPeriodSpend) }}</span>\n"
        "                </div>\n"
        "                <div class=\"mt-1 flex items-center justify-between text-xs text-gray-500 dark:text-dark-400\">\n"
        "                  <span>当期预计分摊</span><span class=\"font-semibold text-gray-800 dark:text-gray-100\">{{ formatHeaderCNY(expectedPeriodShare) }}</span>\n"
        "                </div>\n"
        "              </div>\n"
        "              <!-- Balance (simple mode only) -->\n"
        "              <div v-if=\"authStore.isSimpleMode\" class=\"border-b border-gray-100 px-4 py-2 dark:border-dark-700 sm:hidden\">\n"
    )
    patch_text(
        app_header,
        "              <!-- Balance (mobile only) -->\n              <div class=\"border-b border-gray-100 px-4 py-2 dark:border-dark-700 sm:hidden\">\n",
        mobile_header_summary,
        "add current consumption to mobile user menu",
    )
    patch_text(
        app_header,
        "import { resolveSiteBillingMode } from '@/utils/siteBillingMode'\n",
        "import { resolveSiteBillingMode } from '@/utils/siteBillingMode'\n"
        "import { sharepatchAPI, type SharepatchLine } from '@/sharepatch/api'\n"
        "import { sharepatchLog } from '@/sharepatch/logging'\n",
        "load shared billing summary in header",
    )
    patch_text(
        app_header,
        "const totalBalance = computed(() => availableBalance.value + frozenBalance.value)\n",
        "const totalBalance = computed(() => availableBalance.value + frozenBalance.value)\n"
        "const sharepatchLine = ref<SharepatchLine | null>(null)\n"
        "const sharedBillingActive = ref(false)\n"
        "const sharedBillingSummaryLoaded = ref(false)\n"
        "const currentPeriodSpend = computed(() => Number(sharepatchLine.value?.usd_usage || 0))\n"
        "const expectedPeriodShare = computed(() => Number(sharepatchLine.value?.amount_cny || 0))\n",
        "header shared billing summary state",
    )
    patch_all(
        app_header,
        "{{ formatHeaderMoney(currentPeriodSpend) }}",
        "{{ currentPeriodSpendDisplay }}",
        "format current header consumption",
    )
    patch_all(
        app_header,
        "{{ formatHeaderCNY(expectedPeriodShare) }}",
        "{{ expectedPeriodShareDisplay }}",
        "format current header estimate",
    )
    patch_text(
        app_header,
        "const expectedPeriodShare = computed(() => Number(sharepatchLine.value?.amount_cny || 0))\n",
        "const expectedPeriodShare = computed(() => Number(sharepatchLine.value?.amount_cny || 0))\n"
        "const currentPeriodSpendDisplay = computed(() => sharedBillingSummaryLoaded.value ? formatHeaderMoney(currentPeriodSpend.value) : '—')\n"
        "const expectedPeriodShareDisplay = computed(() => sharedBillingSummaryLoaded.value ? formatHeaderCNY(expectedPeriodShare.value) : '—')\n",
        "format loaded header totals",
    )
    patch_text(
        app_header,
        "function toggleMobileSidebar() {\n",
        "let sharedBillingRefreshTimer: number | undefined\n\n"
        "async function loadSharedBillingSummary() {\n"
        "  if (!user.value || authStore.isSimpleMode) {\n"
        "    sharepatchLine.value = null\n"
        "    sharedBillingSummaryLoaded.value = false\n"
        "    return\n"
        "  }\n"
        "  try {\n"
        "    const dashboard = await sharepatchAPI.getDashboard()\n"
        "    sharedBillingActive.value = dashboard.active\n"
        "    const userID = Number(user.value.id)\n"
        "    sharepatchLine.value = dashboard.current?.lines?.find((line) => line.user_id === userID) ?? null\n"
        "    sharedBillingSummaryLoaded.value = true\n"
        "  } catch (error) {\n"
        "    sharepatchLog.debug('header shared billing summary unavailable', { error_type: error instanceof Error ? error.name : typeof error })\n"
        "  }\n"
        "}\n\n"
        "function formatHeaderCNY(value: number) {\n"
        "  if (!Number.isFinite(value)) return '¥0.00'\n"
        "  return `¥${value.toFixed(2)}`\n"
        "}\n\n"
        "function toggleMobileSidebar() {\n",
        "header shared billing summary polling",
    )
    patch_text(
        app_header,
        "onMounted(() => {\n  document.addEventListener('click', handleClickOutside)\n})\n",
        "onMounted(() => {\n"
        "  document.addEventListener('click', handleClickOutside)\n"
        "  void loadSharedBillingSummary()\n"
        "  sharedBillingRefreshTimer = window.setInterval(() => void loadSharedBillingSummary(), 60_000)\n"
        "})\n\n"
        "watch([() => user.value?.id, () => authStore.isSimpleMode], () => {\n"
        "  void loadSharedBillingSummary()\n"
        "})\n",
        "refresh header shared billing summary",
    )
    patch_text(
        app_header,
        "onBeforeUnmount(() => {\n  document.removeEventListener('click', handleClickOutside)\n})\n",
        "onBeforeUnmount(() => {\n"
        "  document.removeEventListener('click', handleClickOutside)\n"
        "  if (sharedBillingRefreshTimer !== undefined) window.clearInterval(sharedBillingRefreshTimer)\n"
        "})\n",
        "clean up header summary refresh timer",
    )
    patch_text(
        app_header,
        "import { ref, computed, onMounted, onBeforeUnmount } from 'vue'\n",
        "import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'\n",
        "watch current header user",
    )

    router = frontend / "router/index.ts"
    shared_billing_route = (
        "  {\n    path: '/shared-billing',\n"
        "    name: 'SharedBilling',\n"
        "    component: () => import('@/sharepatch/SharepatchView.vue'),\n"
        "    meta: { requiresAuth: true, requiresAdmin: false, title: 'Shared Billing' }\n"
        "  },\n"
        "  {\n    path: '/keys',\n"
    )
    patch_text(
        router,
        "  {\n    path: '/keys',\n",
        shared_billing_route,
        "shared billing route",
    )
    patch_text(
        router,
        "  // Check admin requirement\n",
        "  const sharepatchDisabledPaths = [\n"
        "    '/purchase', '/orders', '/subscriptions', '/redeem', '/batch-image', '/docs/batch-image', '/payment/qrcode',\n"
        "    '/admin/orders', '/admin/subscriptions', '/admin/redeem', '/admin/promo-codes'\n"
        "  ]\n"
        "  if (sharepatchDisabledPaths.some((path) => to.path === path || to.path.startsWith(`${path}/`))) {\n"
        "    next('/shared-billing')\n"
        "    return\n"
        "  }\n\n"
        "  // Check admin requirement\n",
        "redirect legacy billing routes to shared billing",
    )
    feature_guard_test = frontend / "router/__tests__/feature-access.spec.ts"
    for old, new, label in [
        ("runGuard({ requiresPayment: true }, '/purchase')", "runGuard({ requiresPayment: true }, '/feature')", "preserve payment flag guard test"),
        ("['payment', { requiresPayment: true }, '/purchase']", "['payment', { requiresPayment: true }, '/feature']", "preserve payment flag failure test"),
        ("['subscription', { requiresSubscription: true }, '/subscriptions']", "['subscription', { requiresSubscription: true }, '/feature']", "preserve subscription flag failure test"),
    ]:
        patch_text(feature_guard_test, old, new, label)
    patch_all(
        feature_guard_test,
        "runGuard({ requiresSubscription: true }, '/subscriptions')",
        "runGuard({ requiresSubscription: true }, '/feature')",
        "test subscription guard independently of hidden route",
    )
    patch_text(
        feature_guard_test,
        "describe('feature route guard', () => {\n",
        "describe('shared billing legacy routes', () => {\n"
        "  beforeAll(async () => {\n"
        "    await import('@/router')\n"
        "  })\n"
        "  it.each(['/purchase', '/orders', '/subscriptions', '/redeem', '/batch-image', '/docs/batch-image', '/payment/qrcode', '/admin/orders', '/admin/subscriptions', '/admin/redeem', '/admin/promo-codes'])('redirects %s to the shared billing page', async (path) => {\n"
        "    authStore.isAuthenticated = true\n"
        "    const { navigation, next } = runGuard({}, path)\n"
        "    await navigation\n"
        "    expect(next).toHaveBeenCalledWith('/shared-billing')\n"
        "  })\n"
        "})\n\n"
        "describe('feature route guard', () => {\n",
        "sharepatch route guard regression tests",
    )
    user_dashboard = frontend / "views/user/DashboardView.vue"
    patch_text(
        user_dashboard,
        "    <div class=\"space-y-6\">\n",
        "    <div class=\"space-y-6\">\n      <SharepatchPanel />\n",
        "shared billing dashboard panel",
    )
    patch_text(
        user_dashboard,
        "import AppLayout from '@/components/layout/AppLayout.vue'; import LoadingSpinner",
        "import AppLayout from '@/components/layout/AppLayout.vue'; import SharepatchPanel from '@/sharepatch/SharepatchPanel.vue'; import LoadingSpinner",
        "shared billing dashboard import",
    )
    patch_text(
        user_dashboard,
        '<UserDashboardStats :stats="stats" :balance="user?.balance || 0" :is-simple="authStore.isSimpleMode" :platform-quotas="platformQuotas" />',
        '<UserDashboardStats :stats="stats" :balance="user?.balance || 0" :is-simple="authStore.isSimpleMode" :hide-balance="true" :platform-quotas="platformQuotas" />',
        "hide internal meter balance from dashboard",
    )

    dashboard_stats = frontend / "components/user/dashboard/UserDashboardStats.vue"
    patch_text(
        dashboard_stats,
        "    <div v-if=\"!isSimple\" class=\"card p-4\">",
        "    <div v-if=\"!isSimple && !hideBalance\" class=\"card p-4\">",
        "hide meter balance card",
    )
    patch_text(
        dashboard_stats,
        "  isSimple: boolean\n  platformQuotas?: PlatformQuotaItem[] | null\n",
        "  isSimple: boolean\n  hideBalance?: boolean\n  platformQuotas?: PlatformQuotaItem[] | null\n",
        "dashboard hide balance prop",
    )
    profile_info = frontend / "components/user/profile/ProfileInfoCard.vue"
    patch_text(
        profile_info,
        '              <div\n                data-testid="profile-overview-metric-balance"',
        '              <div\n                v-if="!hideBalance"\n                data-testid="profile-overview-metric-balance"',
        "hide the internal meter on user profile",
    )
    patch_text(
        profile_info,
        "  user: User | null\n",
        "  user: User | null\n  hideBalance?: boolean\n",
        "profile hide balance prop",
    )
    profile_view = frontend / "views/user/ProfileView.vue"
    patch_text(
        profile_view,
        "        :user=\"user\"\n",
        "        :user=\"user\"\n        :hide-balance=\"true\"\n",
        "hide internal meter on profile page",
    )

    user_create = frontend / "components/admin/user/UserCreateModal.vue"
    remove_text(
        user_create,
        "        <div>\n          <label class=\"input-label\">{{ t('admin.users.columns.balance') }}</label>\n          <input v-model=\"form.balance\" type=\"number\" step=\"any\" class=\"input\" />\n        </div>\n",
        "remove initial balance adjustment from admin user creation",
    )
    patch_text(
        user_create,
        'class="grid grid-cols-1 sm:grid-cols-2 gap-4"',
        'class="grid grid-cols-1 gap-4"',
        "expand the remaining admin concurrency field",
    )
    patch_text(
        user_create,
        "const form = reactive({ email: '', password: '', username: '', notes: '', role: 'user' as 'user' | 'admin', balance: '', concurrency: 1, rpm_limit: 0 })",
        "const form = reactive({ email: '', password: '', username: '', notes: '', role: 'user' as 'user' | 'admin', concurrency: 1, rpm_limit: 0 })",
        "remove initial balance form state",
    )
    patch_text(
        user_create,
        "    const { balance: rawBalance, ...rest } = { ...form }\n"
        "    const balance = String(rawBalance).trim()\n"
        "    const payload: typeof rest & { balance?: number } = { ...rest }\n"
        "    if (balance !== '') {\n"
        "      payload.balance = Number(balance)\n"
        "    }\n",
        "    const payload = { ...form }\n",
        "remove initial balance payload from admin user creation",
    )
    patch_text(
        user_create,
        "{ email: '', password: '', username: '', notes: '', role: 'user', balance: '', concurrency: 1, rpm_limit: 0 }",
        "{ email: '', password: '', username: '', notes: '', role: 'user', concurrency: 1, rpm_limit: 0 }",
        "remove initial balance reset state",
    )

    users_view = frontend / "views/admin/UsersView.vue"
    patch_text(
        users_view,
        "              <button\n                @click.stop=\"handleDeposit(row)\"",
        "              <button\n                v-if=\"false\"\n                @click.stop=\"handleDeposit(row)\"",
        "hide admin balance top-up entry",
    )
    for anchor, label in [
        ("              <!-- Deposit -->\n", "hide row balance adjustment menu"),
        ("              <!-- Withdraw -->\n", "hide row balance withdrawal menu"),
        ("              <!-- Balance History -->\n", "hide row balance history menu"),
    ]:
        start = users_view.read_text().find(anchor)
        if start >= 0:
            end = users_view.read_text().find("\n\n", start)
            if end < 0:
                fail(f"{label}: end anchor missing in {users_view}")
            block = users_view.read_text()[start:end + 2]
            users_view.write_text(users_view.read_text().replace(block, "", 1))
    remove_text(
        users_view,
        "  { key: 'balance', label: t('admin.users.columns.balance'), sortable: true },\n",
        "hide internal meter column from admin user table",
    )
    patch_text(
        users_view,
        "<UserBalanceModal :show=\"showBalanceModal\"",
        "<UserBalanceModal v-if=\"false\" :show=\"showBalanceModal\"",
        "hide admin balance adjustment modal",
    )
    patch_text(
        users_view,
        "<UserBalanceHistoryModal :show=\"showBalanceHistoryModal\"",
        "<UserBalanceHistoryModal v-if=\"false\" :show=\"showBalanceHistoryModal\"",
        "hide admin balance history modal",
    )

    sidebar = frontend / "components/layout/AppSidebar.vue"
    for old, new, label in [
        ("const flagPayment = makeSidebarFlag(FeatureFlags.payment)", "const flagPayment = () => false", "hide payment navigation"),
        ("const flagSubscription = makeSidebarFlag(FeatureFlags.subscription)", "const flagSubscription = () => false", "hide subscription navigation"),
        ("const flagBatchImageAccess = () => canUseBatchImage.value", "const flagBatchImageAccess = () => false", "hide batch image navigation"),
        ("const flagAffiliate = makeSidebarFlag(FeatureFlags.affiliate)", "const flagAffiliate = () => false", "hide affiliate transfer navigation"),
        ("const flagAdminPayment = () => adminSettingsStore.paymentEnabled", "const flagAdminPayment = () => false", "hide admin payment navigation"),
    ]:
        patch_text(sidebar, old, new, label)
    patch_text(
        sidebar,
        "const { canUseBatchImage, refreshBatchImageAccess } = useBatchImageAccess()",
        "const { refreshBatchImageAccess } = useBatchImageAccess()",
        "remove unused batch-image navigation state",
    )
    patch_text(
        sidebar,
        "  if (withDashboard) {\n    items.push({ path: '/dashboard', label: t('nav.dashboard'), icon: DashboardIcon })\n  }\n  items.push(\n",
        "  if (withDashboard) {\n    items.push({ path: '/dashboard', label: t('nav.dashboard'), icon: DashboardIcon })\n  }\n"
        "  items.push({ path: '/shared-billing', label: '共同账单', icon: CreditCardIcon })\n"
        "  items.push(\n",
        "shared billing navigation",
    )
    patch_text(
        sidebar,
        "{ path: '/redeem', label: t('nav.redeem'), icon: GiftIcon, hideInSimpleMode: true },",
        "{ path: '/redeem', label: t('nav.redeem'), icon: GiftIcon, hideInSimpleMode: true, featureFlag: () => false },",
        "hide balance redemption navigation",
    )
    patch_text(
        sidebar,
        "    { path: '/admin/redeem', label: t('nav.redeemCodes'), icon: TicketIcon, hideInSimpleMode: true },",
        "    { path: '/admin/redeem', label: t('nav.redeemCodes'), icon: TicketIcon, hideInSimpleMode: true, featureFlag: () => false },",
        "hide admin redemption navigation",
    )
    patch_text(
        sidebar,
        "    { path: '/admin/promo-codes', label: t('nav.promoCodes'), icon: GiftIcon, hideInSimpleMode: true },",
        "    { path: '/admin/promo-codes', label: t('nav.promoCodes'), icon: GiftIcon, hideInSimpleMode: true, featureFlag: () => false },",
        "hide promo navigation",
    )
    patch_text(
        sidebar,
        "    { path: '/admin/dashboard', label: t('nav.dashboard'), icon: DashboardIcon },\n",
        "    { path: '/admin/dashboard', label: t('nav.dashboard'), icon: DashboardIcon },\n"
        "    { path: '/shared-billing', label: '共同账单', icon: CreditCardIcon },\n",
        "admin shared billing navigation",
    )

    quick_actions = frontend / "components/user/dashboard/UserDashboardQuickActions.vue"
    patch_text(
        quick_actions,
        '<button v-if="canUseBatchImage" @click="router.push(\'/batch-image\')"',
        '<button v-if="false && canUseBatchImage" @click="router.push(\'/batch-image\')"',
        "hide batch image dashboard action",
    )
    patch_text(
        quick_actions,
        '<button @click="router.push(\'/redeem\')"',
        '<button v-if="false" @click="router.push(\'/redeem\')"',
        "hide balance redemption dashboard action",
    )
    sidebar_test = frontend / "components/layout/__tests__/AppSidebar.spec.ts"
    patch_text(
        sidebar_test,
        "expect(componentSource).toContain('const flagSubscription = makeSidebarFlag(FeatureFlags.subscription)')",
        "expect(componentSource).toContain('const flagSubscription = () => false')",
        "update subscription navigation regression expectation",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--upstream-sha", default=PINNED_BASELINE)
    parser.add_argument("--patch-repo", default=None)
    args = parser.parse_args()
    upstream = args.upstream.resolve()
    actual_sha = run("git", "rev-parse", "HEAD", cwd=upstream)
    if actual_sha != args.upstream_sha:
        fail(f"checkout SHA is {actual_sha}; expected exactly {args.upstream_sha}")
    patch_repo = args.patch_repo or infer_github_repo()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", patch_repo):
        fail(f"invalid GitHub owner/repository: {patch_repo!r}")
    apply_backend(upstream, patch_repo)
    apply_frontend(upstream)
    print(f"overlay applied to {actual_sha} for {patch_repo}")


if __name__ == "__main__":
    main()
