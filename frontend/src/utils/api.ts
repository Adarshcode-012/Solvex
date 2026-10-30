import axios from 'axios'
import type {
  SolveResult, UsageStats, AiConfig,
  BrainStats, TemporalInsights, HealthStatus, Language,
} from '@/types'

// In development: Vite proxies /api → http://localhost:8000
// In production: set VITE_API_URL env var
const BASE_URL = import.meta.env.VITE_API_URL ?? '/api'

const client = axios.create({
  baseURL: BASE_URL,
  timeout: 180_000, // 3 min — agent pipeline can take 90s+
  withCredentials: true,
})

client.interceptors.request.use((config) => {
  const csrf = document.cookie
    .split('; ')
    .find((cookie) => cookie.startsWith('solvex_csrf='))
    ?.split('=')[1]
  if (csrf) config.headers['X-CSRF-Token'] = decodeURIComponent(csrf)
  return config
})

// ── Response interceptor: unwrap Axios errors into plain messages ──────────────
client.interceptors.response.use(
  (res) => res,
  (err) => {
    const detail = err.response?.data?.detail
    if (detail && typeof detail === 'object' && detail.error === 'rate_limit') {
      return Promise.reject({ type: 'rate_limit', ...detail })
    }
    const message =
      (typeof detail === 'string' ? detail : null) ??
      err.message ??
      'Unknown error'
    return Promise.reject(new Error(message))
  }
)

// ── API functions ─────────────────────────────────────────────────────────────

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
