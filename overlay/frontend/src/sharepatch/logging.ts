type LogLevel = 'debug' | 'info' | 'warn' | 'error' | 'silent'

const levels: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
  silent: 50,
}

function configuredLevel(): LogLevel {
  try {
    const value = window.localStorage.getItem('sharepatch.log_level')?.toLowerCase()
    if (value && value in levels) return value as LogLevel
  } catch {
    // Browser storage may be unavailable; keep the default info level.
  }
  return 'info'
}

function write(level: Exclude<LogLevel, 'silent'>, event: string, fields: Record<string, unknown> = {}) {
  if (levels[level] < levels[configuredLevel()]) return
  const method = level === 'debug' ? 'debug' : level
  console[method]('[sharepatch]', event, fields)
}

function errorFields(error: unknown): Record<string, unknown> {
  const fields: Record<string, unknown> = {
    error_type: error instanceof Error ? error.name : typeof error,
  }
  if (error && typeof error === 'object' && 'response' in error) {
    const response = error.response
    if (response && typeof response === 'object' && 'status' in response && typeof response.status === 'number') {
      fields.http_status = response.status
    }
  }
  return fields
}

export const sharepatchLog = {
  debug: (event: string, fields?: Record<string, unknown>) => write('debug', event, fields),
  info: (event: string, fields?: Record<string, unknown>) => write('info', event, fields),
  warn: (event: string, fields?: Record<string, unknown>) => write('warn', event, fields),
  error: (event: string, error?: unknown, fields: Record<string, unknown> = {}) => write('error', event, { ...fields, ...errorFields(error) }),
}
