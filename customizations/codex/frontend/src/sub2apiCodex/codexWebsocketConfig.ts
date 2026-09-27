export const CODEX_WEBSOCKET_DEFAULT_MODEL = 'gpt-6-luna'

export interface CodexWebsocketConfigValues {
  baseUrl: string
  model: string
  authConfig: string
}

function escapeTomlBasicString(value: string): string {
  return value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
}

export function buildCodexWebsocketConfig(values: CodexWebsocketConfigValues): string {
  const model = escapeTomlBasicString(values.model)
  const baseUrl = escapeTomlBasicString(values.baseUrl)

  return `model_provider = "OpenAI"
model = "${model}"
review_model = "${model}"
model_context_window = 1000000
model_auto_compact_token_limit = 900000

[model_providers.OpenAI]
name = "OpenAI"
base_url = "${baseUrl}"
wire_api = "responses"
supports_websockets = true
${values.authConfig}

[features]
api_key_model_discovery = true
responses_websockets_v2 = true
goals = true`
}
