import { useCallback } from 'react'
import toast from 'react-hot-toast'
import { api } from '@/utils/api'
import { useSolveStore } from '@/store/useSolveStore'
import type { AgentRole, SolveResult } from '@/types'

const AGENT_ORDER: AgentRole[] = ['analyzer', 'strategist', 'coder', 'reviewer', 'judge']

interface RateLimitError {
  type: 'rate_limit'
  ai?: string
  ai_label?: string
  message?: string
  retryAfter?: string
}

function isRateLimitError(err: unknown): err is RateLimitError {
  return (
    typeof err === 'object' &&
    err !== null &&
    'type' in err &&
    (err as Record<string, unknown>).type === 'rate_limit'
  )
}

export function useSolve() {
  const store = useSolveStore()

  const applyPipelineEvents = useCallback(
    (result: SolveResult) => {
      const aiUsed = result.agents_ai_used ?? {}

      AGENT_ORDER.forEach((role) => {
        const ai = aiUsed[role]
        const passed = result.status === 'passed'
        const stepPassed = role === 'judge' ? passed : true
        store.setStepStatus(role, stepPassed ? 'done' : 'failed', ai)
      })

      if (result.status === 'max_retries') {
        store.setStepStatus('judge', 'failed')
      }
    },
    [store]
  )

  const applyLiveEvents = useCallback((events: Array<{ agent: AgentRole; status: string }>) => {
    events.forEach(({ agent, status }) => {
      if (status === 'started') store.setStepStatus(agent, 'active')
      else if (status === 'done' || status === 'unverified') store.setStepStatus(agent, 'done')
      else if (status === 'failed') store.setStepStatus(agent, 'failed')
    })
  }, [store])

  const solve = useCallback(async () => {
    const { problem, language, imageFile, aiMode, manualOverrides, solving } = store

    if (solving) return
    if (!problem.trim() && !imageFile) {
      toast.error('Enter a problem or upload a screenshot.')
      return
    }

    store.setSolving(true)
    store.resetPipeline()

    try {
      let result: SolveResult

      const overrides = aiMode === 'manual' && Object.keys(manualOverrides).length > 0
        ? manualOverrides
        : null

      if (imageFile) {
        store.setStepStatus('analyzer', 'active')
        result = await api.solveImage(imageFile, language, problem, overrides)
      } else {
        const { job_id: jobId, max_seconds: maxSeconds } = await api.startSolveJob(problem, language, overrides)
        const deadline = Date.now() + (maxSeconds ?? 900) * 1000
        while (true) {
          if (Date.now() >= deadline) throw new Error('Solving timed out. Please run it again.')
          await new Promise((resolve) => setTimeout(resolve, 350))
          const job = await api.getSolveJob(jobId)
          applyLiveEvents(job.events)
          if (job.status === 'complete' && job.result) {
            result = job.result
            break
          }
          if (job.status === 'failed') {
            if (job.error?.type === 'rate_limit') {
              throw {
                type: 'rate_limit',
                ai: job.error.ai,
                ai_label: job.error.ai_label,
                message: job.error.message,
                retryAfter: job.error.retry_after ? String(job.error.retry_after) : undefined,
              }
            }
            throw new Error((job.error?.message ?? 'Solve failed.') +
              (job.error?.request_id ? ` (Request ID: ${job.error.request_id})` : ''))
          }
        }
      }

      applyPipelineEvents(result)
      store.setResult(result)

      if (result.status === 'passed') {
        toast.success(`Solved in ${result.iterations_used} iteration${result.iterations_used !== 1 ? 's' : ''}!`)
      } else {
        toast('Best attempt shown — could not pass all tests.', { icon: '⚠️' })
      }

      api.getUsage().then(store.setUsage).catch(() => {})

    } catch (err: unknown) {
      if (isRateLimitError(err)) {
        const aiLabel = err.ai_label ?? 'SolveX'
        store.setRateLimitInfo({
          ai: err.ai ?? 'system',
          ai_label: aiLabel,
          message: err.message ?? 'Rate limit reached.',
          retryAfterSeconds: err.retryAfter ? Number(err.retryAfter) : undefined,
        })
        AGENT_ORDER.forEach((r) => store.setStepStatus(r, 'failed'))
        toast.error(`${aiLabel} rate limit hit. Switch AI or wait for reset.`)
      } else {
        const message = err instanceof Error ? err.message : 'Unexpected error'
        store.setError(message)
        AGENT_ORDER.forEach((r) => store.setStepStatus(r, 'failed'))
        toast.error(message)
      }
    } finally {
      store.setSolving(false)
    }
  }, [store, applyPipelineEvents, applyLiveEvents])

  return { solve }
}
