#!/usr/bin/env python3
"""Apply the optional Codex tutorial customization to one Sub2API checkout."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit(f"apply-codex-customizations: {message}")


def run(*args: str, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(args, cwd=cwd, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        fail(f"command failed ({' '.join(args)}): {exc.stderr.strip()}")
    return result.stdout.strip()


def patch_text(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        if new in text:
            return
        fail(f"{label}: anchor is missing in {path}")
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected one anchor in {path}, found {count}")
    path.write_text(text.replace(old, new, 1))


def patch_text_variants(
    path: Path,
    variants: list[tuple[str, str]],
    label: str,
    marker: str,
) -> None:
    text = path.read_text()
    matches = [(old, new) for old, new in variants if old in text]
    if not matches:
        if marker in text:
            return
        fail(f"{label}: anchor is missing in {path}")
    if len(matches) != 1:
        fail(f"{label}: expected one supported anchor in {path}, found {len(matches)}")
    old, new = matches[0]
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
        fail(f"customization source directory is missing: {source}")
    shutil.copytree(source, destination, dirs_exist_ok=True)


def apply_codex_customizations(upstream: Path) -> None:
    frontend = upstream / "frontend/src"
    copy_tree(ROOT / "customizations/codex/frontend/src/sub2apiCodex", frontend / "sub2apiCodex")

    ccswitch_import = frontend / "utils/ccswitchImport.ts"
    codex_model_import = "from '@/sub2apiCodex/codexWebsocketConfig'"
    if codex_model_import not in ccswitch_import.read_text():
        patch_text(
            ccswitch_import,
            "import type { GroupPlatform } from '@/types'\n",
            "import type { GroupPlatform } from '@/types'\n"
            "import { CODEX_WEBSOCKET_DEFAULT_MODEL } from '@/sub2apiCodex/codexWebsocketConfig'\n",
            "share the Codex template model default with CCS import",
        )
    patch_text(
        ccswitch_import,
        "export const OPENAI_CC_SWITCH_CODEX_MODEL = 'gpt-5.5'\n",
        "// The CCS Codex deeplink carries one model ID; keep it aligned with the tutorial.\n"
        "export const OPENAI_CC_SWITCH_CODEX_MODEL = CODEX_WEBSOCKET_DEFAULT_MODEL\n",
        "use the tutorial default model for CCS Codex imports",
    )
    remove_text(
        ccswitch_import,
        "    ['configFormat', 'json'],\n",
        "omit config format when the CCS link carries no config payload",
    )

    use_key_modal = frontend / "components/keys/UseKeyModal.vue"
    codex_config_import = "from '@/sub2apiCodex/codexWebsocketConfig'"
    if codex_config_import not in use_key_modal.read_text():
        patch_text(
            use_key_modal,
            "import type { GroupPlatform } from '@/types'\n",
            "import type { GroupPlatform } from '@/types'\n"
            "import { buildCodexWebsocketConfig, CODEX_WEBSOCKET_DEFAULT_MODEL } from '@/sub2apiCodex/codexWebsocketConfig'\n",
            "load the editable Codex WebSocket tutorial template",
        )
    patch_text(
        use_key_modal,
        "    case 'openai':\n      return 'codex'\n",
        "    case 'openai':\n      return 'codex-ws'\n",
        "default to the Codex WebSocket tutorial",
    )
    patch_text(
        use_key_modal,
        "      const tabs: TabConfig[] = [\n"
        "        { id: 'codex', label: t('keys.useKeyModal.cliTabs.codexCli'), icon: TerminalIcon },\n"
        "        { id: 'codex-ws', label: t('keys.useKeyModal.cliTabs.codexCliWs'), icon: TerminalIcon },\n"
        "      ]\n",
        "      const tabs: TabConfig[] = [\n"
        "        { id: 'codex-ws', label: t('keys.useKeyModal.cliTabs.codexCliWs'), icon: TerminalIcon },\n"
        "      ]\n",
        "show only the Codex WebSocket tutorial tab",
    )
    patch_text(
        use_key_modal,
        "      if (activeClientTab.value === 'codex-ws') {\n"
        "        return generateOpenAIWsFiles(apiBase, apiKey)\n"
        "      }\n"
        "      // Codex appends /responses directly and does not add /v1.\n"
        "      return generateOpenAIFiles(apiBase, apiKey)\n",
        "      // The OpenAI Codex tutorial exposes only the WebSocket configuration.\n"
        "      return generateOpenAIWsFiles(apiBase, apiKey)\n",
        "use WebSocket configuration for every OpenAI Codex tutorial path",
    )
    patch_regex(
        use_key_modal,
        r"(?ms)^function generateOpenAIFiles\(baseUrl: string, apiKey: string\): FileConfig\[\] \{.*?^\}\n\n",
        "// Codex customization: use the WebSocket-only tutorial configuration.\n\n",
        "remove the original non-WebSocket OpenAI Codex example",
        "Codex customization: use the WebSocket-only tutorial configuration.",
    )
    patch_text(
        use_key_modal,
        "  const model = selectCodexCatalogModel('gpt-5.5')\n"
        "  const reasoningEffortLine = codexReasoningEffortTomlLine(model)\n",
        "  const model = CODEX_WEBSOCKET_DEFAULT_MODEL\n",
        "read the default Codex model from the editable tutorial template",
    )
    patch_regex(
        use_key_modal,
        r"(?ms)^  // config.toml content with WebSocket v2\n  const configContent = `.*?^goals = true`\n",
        "  const configContent = buildCodexWebsocketConfig({\n"
        "    baseUrl,\n"
        "    model,\n"
        "    authConfig: generateCodexProviderAuthConfig(apiKey)\n"
        "  })\n",
        "use the repository-managed WebSocket configuration template",
        "const configContent = buildCodexWebsocketConfig({",
    )

    # Remove the local catalog UI and the client-side fetching/selection path.
    patch_regex(
        use_key_modal,
        r'(?ms)^        <section\n          v-if="showCodexModelCatalog".*?^        </section>\n\n',
        "        <!-- Codex discovers available models from the configured API endpoint. -->\n",
        "remove the local Codex model catalog panel",
        "Codex discovers available models from the configured API endpoint.",
    )
    patch_regex(
        use_key_modal,
        r"(?ms)^type CodexModelManifestState = .*?^// Reset tabs when platform changes\n",
        "// Codex discovers models directly from the configured API endpoint.\n\n"
        "// Reset tabs when platform changes\n",
        "remove Codex catalog state and path calculations",
        "Codex discovers models directly from the configured API endpoint.",
    )
    patch_text(
        use_key_modal,
        "watch(() => props.show, (show) => {\n"
        "  if (show) {\n"
        "    codexAuthMode.value = 'legacy'\n"
        "  } else {\n"
        "    resetCodexModelManifest()\n"
        "  }\n"
        "})\n",
        "watch(() => props.show, (show) => {\n"
        "  if (show) codexAuthMode.value = 'legacy'\n"
        "})\n",
        "simplify Codex auth mode reset watcher",
    )
    remove_text(
        use_key_modal,
        "watch(codexManifestContext, (context, previousContext) => {\n"
        "  if (context !== previousContext) {\n"
        "    resetCodexModelManifest()\n"
        "  }\n"
        "})\n\n",
        "remove catalog request context watcher",
    )
    patch_regex(
        use_key_modal,
        r"(?ms)^function resetCodexModelManifest\(\) \{.*?^\}\n\n(?=const escapeHtml)",
        "// Codex customization: API-key model discovery replaces downloaded catalogs.\n\n",
        "remove Codex catalog fetch, download, and model selection helpers",
        "Codex customization: API-key model discovery replaces downloaded catalogs.",
    )
    remove_text(use_key_modal, "import { saveAs } from 'file-saver'\n", "remove catalog file download dependency")
    remove_text(use_key_modal, "import { fetchCodexModelsManifest } from '@/api/codex'\n", "remove catalog fetch dependency")
    remove_text(
        use_key_modal,
        "import { buildCodexModelCatalogUrl, fetchCodexModelsManifest } from '@/api/codex'\n",
        "remove catalog URL and fetch dependencies",
    )
    remove_text(
        use_key_modal,
        "import {\n"
        "  findCodexCatalogModel,\n"
        "  formatCodexReasoningEffortTomlLine,\n"
        "  parseCodexCatalogModels,\n"
        "  selectCodexConfigReasoningEffort\n"
        "} from '@/utils/codexCatalogConfig'\n",
        "remove catalog parsing dependency",
    )

    patch_text(
        use_key_modal,
        "  const model = selectCodexCatalogModel('grok-4.5')\n",
        "  const model = 'grok-4.5'\n",
        "use the Grok Codex default without a local catalog",
    )
    patch_text_variants(
        use_key_modal,
        [
            (
                'model = "${model}"\nmodel_catalog_json = "${escapeTomlBasicString(codexModelCatalogPath.value)}"\n# Optional:\n',
                'model = "${model}"\n# Optional:\n',
            ),
            (
                'model = "${model}"\n${codexLocalCatalogToml.value}# Optional:\n',
                'model = "${model}"\n# Optional:\n',
            ),
        ],
        "remove local catalog from Grok Codex configuration",
        'model = "${model}"\n# Optional:',
    )
    patch_text(
        use_key_modal,
        "${codexModelCatalogMode.value === 'remote' ? `model_catalog_url = \"${escapeTomlBasicString(buildCodexModelCatalogUrl(baseUrl))}\"\\n` : ''}# Prefer env_key (variable NAME). Do not combine with experimental_bearer_token.\n",
        "# Codex discovers models directly from the configured API endpoint.\n"
        "# Prefer env_key (variable NAME). Do not combine with experimental_bearer_token.\n",
        "remove remote catalog URL from Grok Codex configuration",
    )
    patch_text(
        use_key_modal,
        "# Optional:\n# [features]\n# goals = true`",
        "[features]\napi_key_model_discovery = true\n# goals = true`",
        "enable endpoint model discovery in Grok Codex configuration",
    )
    patch_text(
        use_key_modal,
        "  const model = selectCodexCatalogModel(preferredModel)\n",
        "  const model = preferredModel\n",
        "use routed Codex defaults without a local catalog",
    )
    patch_text_variants(
        use_key_modal,
        [
            (
                'review_model = "${model}"\ndisable_response_storage = true\nmodel_catalog_json = "${escapeTomlBasicString(codexModelCatalogPath.value)}"\n',
                'review_model = "${model}"\ndisable_response_storage = true\n',
            ),
            (
                'review_model = "${model}"\ndisable_response_storage = true\n${codexLocalCatalogToml.value}\n[model_providers.sub2api]',
                'review_model = "${model}"\ndisable_response_storage = true\n\n[model_providers.sub2api]',
            ),
        ],
        "remove local catalog from routed Codex configuration",
        'disable_response_storage = true\n\n[model_providers.sub2api]',
    )
    patch_text(
        use_key_modal,
        "${codexModelCatalogMode.value === 'remote' ? `model_catalog_url = \"${escapeTomlBasicString(buildCodexModelCatalogUrl(baseUrl))}\"\\n` : ''}env_key = \"SUB2API_API_KEY\"\n",
        "# Codex discovers models directly from the configured API endpoint.\n"
        "env_key = \"SUB2API_API_KEY\"\n",
        "remove remote catalog URL from routed Codex configuration",
    )
    patch_text(
        use_key_modal,
        'supports_websockets = false`',
        'supports_websockets = false\n\n[features]\napi_key_model_discovery = true`',
        "enable endpoint model discovery in routed Codex configuration",
    )

    zh_dashboard = frontend / "i18n/locales/zh/dashboard.ts"
    en_dashboard = frontend / "i18n/locales/en/dashboard.ts"
    current_catalog_hints = [
        (
            zh_dashboard,
            "codexConfigTomlHint: '下载下方模型目录，将两个文件保存到 Codex 配置目录后重启 Codex。',",
            "codexConfigTomlHint: '将 config.toml 保存到 Codex 配置目录并重启；模型列表会从当前 API 端点获取。',",
            "remove routed Codex catalog setup instructions",
        ),
        (
            en_dashboard,
            "codexConfigTomlHint: 'Download the model catalog below, save both files under the Codex config directory, and restart Codex.',",
            "codexConfigTomlHint: 'Save config.toml under the Codex config directory and restart Codex. Available models are discovered from the API endpoint.',",
            "remove routed Codex catalog setup instructions",
        ),
        (
            zh_dashboard,
            "configTomlHint: '保存 config.toml 后重启 Codex，客户端会加载远程目录。使用本地文件模式时，还需下载目录并保存到配置中的路径。',",
            "configTomlHint: '将 config.toml 保存到 Codex 配置目录并重启；模型列表会从当前 API 端点获取。',",
            "remove routed Codex catalog setup instructions",
        ),
        (
            en_dashboard,
            "configTomlHint: 'Save config.toml and restart Codex to load the remote catalog. In local file mode, also download the catalog to the configured path.',",
            "configTomlHint: 'Save config.toml under the Codex config directory and restart Codex. Available models are discovered from the API endpoint.',",
            "remove routed Codex catalog setup instructions",
        ),
    ]
    for dashboard, old, new, label in current_catalog_hints:
        if old in dashboard.read_text():
            patch_all(dashboard, old, new, label)

    for dashboard, replacements in [
        (zh_dashboard, [
            (
                "codexNote: '启动 Codex 前先导出 SUB2API_API_KEY。下载的目录只包含模型元数据，不包含 API Key。'",
                "codexNote: '启动 Codex 前先导出 SUB2API_API_KEY；Codex 会从当前 API 端点发现可用模型。'",
                "remove routed Codex catalog note",
            ),
            (
                "codexDescription: '使用 API Key 和当前 Composite 分组的完整模型目录配置 Codex。',",
                "codexDescription: '使用 API Key 配置 Codex，并从当前 Composite 分组的 API 端点发现模型。',",
                "update Composite Codex description for endpoint discovery",
            ),
            (
                "codexNote: '启动 Codex 前先导出 SUB2API_API_KEY；分组会根据目录中选中的模型路由请求。'",
                "codexNote: '启动 Codex 前先导出 SUB2API_API_KEY；Codex 会从当前 API 端点发现可用模型。'",
                "remove Composite catalog note",
            ),
            (
                "description: '使用当前路由分组的完整模型目录配置 Codex。',",
                "description: '配置 Codex 从当前路由分组的 API 端点发现可用模型。',",
                "update routed Codex description for endpoint discovery",
            ),
            (
                "configTomlHint: '下载下方模型目录，将两个文件保存到 Codex 配置目录后重启 Codex。',",
                "configTomlHint: '将 config.toml 保存到 Codex 配置目录并重启；模型列表会从当前 API 端点获取。',",
                "remove routed Codex catalog setup instructions",
            ),
            (
                "note: '启动 Codex 前先导出 SUB2API_API_KEY。下载的目录只包含模型元数据，不包含 API Key。'",
                "note: '启动 Codex 前先导出 SUB2API_API_KEY；Codex 会从当前 API 端点发现可用模型。'",
                "remove routed Codex catalog note",
            ),
        ]),
        (en_dashboard, [
            (
                "codexNote: 'Export SUB2API_API_KEY before starting Codex. The downloaded catalog contains model metadata only, not your API key.',",
                "codexNote: 'Export SUB2API_API_KEY before starting Codex. Codex discovers available models from the configured API endpoint.',",
                "remove routed Codex catalog note",
            ),
            (
                "codexDescription: 'Configure Codex with API key authentication and the complete model catalog for this Composite group.',",
                "codexDescription: 'Configure Codex with API key authentication and discover models from this Composite group API endpoint.',",
                "update Composite Codex description for endpoint discovery",
            ),
            (
                "codexNote: 'Export SUB2API_API_KEY before starting Codex. Model requests are routed by the selected catalog slug.',",
                "codexNote: 'Export SUB2API_API_KEY before starting Codex. Codex discovers available models from the configured API endpoint.',",
                "remove Composite catalog note",
            ),
            (
                "description: 'Configure Codex with the complete model catalog for the current routed group.',",
                "description: 'Configure Codex to discover available models from the current routed API endpoint.',",
                "update routed Codex description for endpoint discovery",
            ),
            (
                "configTomlHint: 'Download the model catalog below, save both files under the Codex config directory, and restart Codex.',",
                "configTomlHint: 'Save config.toml under the Codex config directory and restart Codex. Available models are discovered from the API endpoint.',",
                "remove routed Codex catalog setup instructions",
            ),
            (
                "note: 'Export SUB2API_API_KEY before starting Codex. The downloaded catalog contains model metadata only, not your API key.',",
                "note: 'Export SUB2API_API_KEY before starting Codex. Codex discovers available models from the configured API endpoint.',",
                "remove routed Codex catalog note",
            ),
        ]),
    ]:
        for old, new, label in replacements:
            patch_all(dashboard, old, new, label)

    for dashboard, marker in [
        (zh_dashboard, "// Codex discovers models directly from the API endpoint."),
        (en_dashboard, "// Codex discovers models directly from the API endpoint."),
    ]:
        patch_regex(
            dashboard,
            r"(?ms)^      codexModelCatalog: \{\n.*?^      \},\n",
            f"      {marker}\n",
            "remove unused Codex model catalog translations",
            marker,
        )

    use_key_modal_tests = frontend / "components/keys/__tests__/UseKeyModal.spec.ts"
    patch_text(
        use_key_modal_tests,
        "  it('keeps legacy OpenAI Codex config as the default', () => {\n",
        "  it('keeps legacy OpenAI Codex WebSocket config as the default', () => {\n",
        "rename the OpenAI Codex default configuration expectation",
    )
    patch_text(
        use_key_modal_tests,
        "    expect(configToml).not.toContain('supports_websockets')\n"
        "    expect(configToml).not.toContain('responses_websockets_v2')\n",
        "    expect(configToml).toContain('supports_websockets = true')\n"
        "    expect(configToml).toContain('responses_websockets_v2 = true')\n",
        "expect WebSocket settings in the default OpenAI Codex configuration",
    )
    patch_text(
        use_key_modal_tests,
        "    expect(configToml).toContain('[features]\\ngoals = true')\n",
        "    expect(configToml).toContain('[features]\\napi_key_model_discovery = true\\nresponses_websockets_v2 = true\\ngoals = true')\n",
        "expect live API model discovery in OpenAI Codex config",
    )
    patch_all(
        use_key_modal_tests,
        "    expect(configToml).toContain('[features]\\nresponses_websockets_v2 = true\\ngoals = true')\n",
        "    expect(configToml).toContain('[features]\\napi_key_model_discovery = true\\nresponses_websockets_v2 = true\\ngoals = true')\n",
        "expect endpoint model discovery in the WebSocket Codex test",
    )
    patch_all(
        use_key_modal_tests,
        "expect(configToml).toContain('model = \"gpt-5.5\"')",
        "expect(configToml).toContain('model = \"gpt-6-luna\"')",
        "update OpenAI Codex model expectation",
    )
    patch_all(
        use_key_modal_tests,
        "expect(configToml).toContain('review_model = \"gpt-5.5\"')",
        "expect(configToml).toContain('review_model = \"gpt-6-luna\"')",
        "update OpenAI Codex review model expectation",
    )
    patch_all(
        use_key_modal_tests,
        "expect(configToml).not.toContain('model_context_window')",
        "expect(configToml).toContain('model_context_window = 1000000')",
        "expect the configured Codex context window",
    )
    patch_all(
        use_key_modal_tests,
        "expect(configToml).not.toContain('model_auto_compact_token_limit')",
        "expect(configToml).toContain('model_auto_compact_token_limit = 900000')",
        "expect the configured Codex compaction threshold",
    )
    openai_catalog_expectation = (
        "    expect(configToml).toContain('model_catalog_url = \"https://example.com/v1/models\"')\n"
        "    expect(configToml).not.toContain('model_catalog_json')\n"
    )
    if openai_catalog_expectation in use_key_modal_tests.read_text():
        patch_all(
            use_key_modal_tests,
            openai_catalog_expectation,
            "    expect(configToml).toContain('api_key_model_discovery = true')\n"
            "    expect(configToml).not.toContain('model_catalog_url')\n"
            "    expect(configToml).not.toContain('model_catalog_json')\n",
            "expect endpoint discovery instead of remote catalogs in OpenAI Codex configs",
        )
    patch_text(
        use_key_modal_tests,
        "import { afterEach, describe, expect, it, vi } from 'vitest'\n"
        "import { flushPromises, mount } from '@vue/test-utils'\n",
        "import { describe, expect, it, vi } from 'vitest'\n"
        "import { mount } from '@vue/test-utils'\n",
        "remove catalog-only test dependencies",
    )
    patch_text(
        use_key_modal_tests,
        "const { copyToClipboardMock, saveAsMock } = vi.hoisted(() => ({\n"
        "  copyToClipboardMock: vi.fn().mockResolvedValue(true),\n"
        "  saveAsMock: vi.fn()\n"
        "}))\n",
        "const { copyToClipboardMock } = vi.hoisted(() => ({\n"
        "  copyToClipboardMock: vi.fn().mockResolvedValue(true)\n"
        "}))\n",
        "remove catalog-only file saver mock",
    )
    remove_text(
        use_key_modal_tests,
        "vi.mock('file-saver', () => ({\n"
        "  saveAs: saveAsMock\n"
        "}))\n\n",
        "remove catalog-only file saver mock module",
    )
    remove_text(
        use_key_modal_tests,
        "function readBlobAsText(blob: Blob): Promise<string> {\n"
        "  return new Promise((resolve, reject) => {\n"
        "    const reader = new FileReader()\n"
        "    reader.addEventListener('load', () => resolve(String(reader.result || '')))\n"
        "    reader.addEventListener('error', () => reject(reader.error))\n"
        "    reader.readAsText(blob)\n"
        "  })\n"
        "}\n\n",
        "remove catalog-only blob reader helper",
    )
    remove_text(
        use_key_modal_tests,
        "  afterEach(() => {\n"
        "    vi.unstubAllGlobals()\n"
        "    saveAsMock.mockClear()\n"
        "  })\n\n",
        "remove catalog-only test cleanup",
    )
    patch_regex(
        use_key_modal_tests,
        r"(?ms)^  // Scenario: API Key users can .*?routed .*?catalog.*?(?=^  it\.each)",
        "  // Codex customization: models are discovered by the API endpoint instead of downloaded.\n\n",
        "remove downloaded catalog test",
        "Codex customization: models are discovered by the API endpoint instead of downloaded.",
    )
    patch_text(
        use_key_modal_tests,
        "    'offers Codex catalog configuration for the %s routed group',",
        "    'configures API model discovery for the %s routed group',",
        "rename routed Codex catalog test",
    )
    patch_all(
        use_key_modal_tests,
        "      expect(wrapper.find('[data-testid=\"codex-model-catalog\"]').exists()).toBe(true)\n",
        "      expect(wrapper.find('[data-testid=\"codex-model-catalog\"]').exists()).toBe(false)\n",
        "expect the catalog panel to be absent",
    )
    patch_text_variants(
        use_key_modal_tests,
        [
            (
                "\n      expect(config).toContain('model_catalog_json = \"~/.codex/codex-models.json\"')\n",
                "\n      expect(config).toContain('api_key_model_discovery = true')\n"
                "      expect(config).not.toContain('model_catalog_url')\n"
                "      expect(config).not.toContain('model_catalog_json')\n",
            ),
            (
                "\n      expect(config).toContain('model_catalog_url = \"https://example.com/v1/models\"')\n"
                "      expect(config).not.toContain('model_catalog_json')\n",
                "\n      expect(config).toContain('api_key_model_discovery = true')\n"
                "      expect(config).not.toContain('model_catalog_url')\n"
                "      expect(config).not.toContain('model_catalog_json')\n",
            ),
        ],
        "expect endpoint discovery instead of local catalog in routed Codex config",
        "\n      expect(config).toContain('api_key_model_discovery = true')\n"
        "      expect(config).not.toContain('model_catalog_url')\n"
        "      expect(config).not.toContain('model_catalog_json')",
    )
    patch_regex(
        use_key_modal_tests,
        r"(?ms)^  // Scenario: the platform-preferred model remains selected.*?(?=^\}\)\n)",
        "  // Codex customization: models resolve from the API endpoint.\n",
        "remove catalog-driven model selection tests",
        "Codex customization: models resolve from the API endpoint.",
    )

    ccswitch_tests = frontend / "utils/__tests__/ccswitchImport.spec.ts"
    ccswitch_test_model_import = "from '@/sub2apiCodex/codexWebsocketConfig'"
    if ccswitch_test_model_import not in ccswitch_tests.read_text():
        patch_text(
            ccswitch_tests,
            "import type { GroupPlatform } from '@/types'\n",
            "import type { GroupPlatform } from '@/types'\n"
            "import { CODEX_WEBSOCKET_DEFAULT_MODEL } from '@/sub2apiCodex/codexWebsocketConfig'\n",
            "test that CCS import tracks the Codex tutorial model",
        )
    patch_text(
        ccswitch_tests,
        "expect(OPENAI_CC_SWITCH_CODEX_MODEL).toBe('gpt-5.5')",
        "expect(OPENAI_CC_SWITCH_CODEX_MODEL).toBe(CODEX_WEBSOCKET_DEFAULT_MODEL)",
        "expect CCS import to use the shared Codex model default",
    )



def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--upstream-sha", required=True)
    args = parser.parse_args()
    upstream = args.upstream.resolve()
    actual_sha = run("git", "rev-parse", "HEAD", cwd=upstream)
    if actual_sha != args.upstream_sha:
        fail(f"checkout SHA is {actual_sha}; expected exactly {args.upstream_sha}")
    apply_codex_customizations(upstream)
    print(f"Codex tutorial customization applied to {actual_sha}")


if __name__ == "__main__":
    main()
