import axios from 'axios'
import type {
  SolveResult, UsageStats, AiConfig, ExplanationResponse,
  BrainStats, TemporalInsights, HealthStatus, Language, SolveJobSnapshot,
} from '@/types'

const BASE_URL = import.meta.env.VITE_API_URL ?? '/api'
export const API_TIMEOUT_MS = 600_000

const client = axios.create({
  baseURL: BASE_URL,
  timeout: API_TIMEOUT_MS,
  withCredentials: true,
})

export function formatApiError(detail: unknown): string | null {
  if (typeof detail === 'string') return detail
  if (typeof detail !== 'object' || detail === null) return null

  const value = detail as Record<string, unknown>
  if (
    (
      value.code === 'ai_auth_failed' ||
      value.code === 'ai_key_missing' ||
      value.code === 'ai_provider_timeout'
    ) &&
    typeof value.message === 'string'
  ) {
    return `${value.code}: ${value.message}`
  }
  if (typeof value.message === 'string') return value.message
  return null
}

export function formatApiErrorForResponse(detail: unknown, status?: number): string | null {
  return formatApiError(detail) ??
    (status === 504
      ? 'ai_provider_timeout: The AI request timed out. Check backend and provider connectivity, then retry.'
      : null)
}

client.interceptors.request.use((config) => {
  const csrf = document.cookie
    .split('; ')
    .find((cookie) => cookie.startsWith('solvex_csrf='))
    ?.split('=')[1]
  if (csrf) config.headers['X-CSRF-Token'] = decodeURIComponent(csrf)
  return config
})

client.interceptors.response.use(
  (res) => res,
  (err) => {
    const detail = err.response?.data?.detail
    if (detail && typeof detail === 'object' && detail.error === 'rate_limit') {
      return Promise.reject({
        type: 'rate_limit',
        ...detail,
        retryAfter: err.response?.headers?.['retry-after'],
      })
    }
    const message =
      formatApiErrorForResponse(detail, err.response?.status) ??
      err.message ??
      'Unknown error'
    const requestId = err.response?.data?.request_id ?? err.response?.headers?.['x-request-id']
    return Promise.reject(new Error(
      err.response
        ? message + (requestId ? ` (Request ID: ${requestId})` : '')
        : `network_error: ${message}`
    ))
  }
)


export const api = {
  health(): Promise<HealthStatus> {
    return client.get('/health').then((r) => r.data)
  },

  solveText(
    problem: string,
    language: Language,
    manualOverrides?: Record<string, string> | null
  ): Promise<SolveResult> {
    return client
      .post('/solve', {
        problem,
        language,
        manual_ai_overrides: manualOverrides ?? null,
      })
      .then((r) => r.data)
  },

  startSolveJob(
    problem: string,
    language: Language,
    manualOverrides?: Record<string, string> | null,
  ): Promise<{ job_id: string; max_seconds?: number }> {
    return client.post('/solve/jobs', {
      problem,
      language,
      manual_ai_overrides: manualOverrides ?? null,
    }).then((r) => r.data)
  },

  getSolveJob(jobId: string): Promise<SolveJobSnapshot> {
    return client.get(`/solve/jobs/${encodeURIComponent(jobId)}`).then((r) => r.data)
  },

  solveImage(
    imageFile: File,
    language: Language,
    extraText = '',
    manualOverrides?: Record<string, string> | null
  ): Promise<SolveResult> {
    const fd = new FormData()
    fd.append('image', imageFile)
    fd.append('language', language)
    fd.append('extra_text', extraText)
    fd.append('manual_ai_overrides', JSON.stringify(manualOverrides ?? {}))
    return client.post('/solve-image', fd).then((r) => r.data)
  },

  explain(
    problem: string,
    finalCode: string,
    language: Language,
    chosenApproach: string,
    reasoningChain: string,
  ): Promise<ExplanationResponse> {
    return client.post('/explain', {
      problem,
      final_code: finalCode,
      language,
      chosen_approach: chosenApproach,
      reasoning_chain: reasoningChain,
    }).then((r) => r.data)
  },

  getUsage(): Promise<UsageStats> {
    return client.get('/usage').then((r) => r.data)
  },

  resetUsage(): Promise<{ message: string }> {
    return client.post('/usage/reset').then((r) => r.data)
  },

  getAiConfig(): Promise<AiConfig> {
    return client.get('/ai-config').then((r) => r.data)
  },

  getBrainStats(): Promise<BrainStats> {
    return client.get('/brain/stats').then((r) => r.data)
  },

  getTemporalInsights(): Promise<TemporalInsights> {
    return client.get('/brain/temporal').then((r) => r.data)
  },

  resetBrain(): Promise<{ message: string }> {
    return client.post('/brain/reset').then((r) => r.data)
  },
}
