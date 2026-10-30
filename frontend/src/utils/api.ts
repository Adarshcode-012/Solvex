import axios from 'axios'
import type {
  SolveResult, UsageStats, AiConfig,
  BrainStats, TemporalInsights, HealthStatus, Language,
} from '@/types'

// In development: Vite proxies /api → http://localhost:8000
// In production: set VITE_API_URL env var
const BASE_URL = import.meta.env.VITE_API_URL ?? '/api'

// Must match the backend's APP_SECRET_KEY. Only needed if the backend has
// one configured — set VITE_APP_API_KEY in the frontend's .env to match.
// (This is a shared-secret header, not a substitute for real per-user auth —
// fine for a solo-operator deployment; add proper auth if multiple people
// will use this instance.)
const API_KEY = import.meta.env.VITE_APP_API_KEY

const client = axios.create({
  baseURL: BASE_URL,
  timeout: 180_000, // 3 min — agent pipeline can take 90s+
  headers: API_KEY ? { 'X-API-Key': API_KEY } : {},
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
