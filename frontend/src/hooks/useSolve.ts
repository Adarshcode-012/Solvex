import { useCallback } from 'react'
import toast from 'react-hot-toast'
import { api } from '@/utils/api'
import { useSolveStore } from '@/store/useSolveStore'
import type { AgentRole, SolveResult } from '@/types'

const AGENT_ORDER: AgentRole[] = ['analyzer', 'strategist', 'coder', 'reviewer', 'judge']

interface RateLimitError {
  type: 'rate_limit'
  ai: string
  ai_label: string
  message: string
}

function isRateLimitError(err: unknown): err is RateLimitError {
  return (
    typeof err === 'object' &&
    err !== null &&
    'type' in err &&
    (err as Record<string, unknown>).type === 'rate_limit' &&
    'ai' in err &&
    'ai_label' in err &&
    'message' in err
  )
}

export function useSolve() {
  const store = useSolveStore()

  /**
   * Animates the pipeline steps based on pipeline_events from the result.
   * Since the API is synchronous (not streaming), we animate after we get
   * the result using the pipeline_events array returned from the backend.
   */
  const applyPipelineEvents = useCallback(
    (result: SolveResult) => {
      const events = result.pipeline_events ?? []
      const aiUsed = result.agents_ai_used ?? {}

      // Mark all steps that appear in events as done/failed
      AGENT_ORDER.forEach((role) => {
        const ai = aiUsed[role]
        const passed = result.status === 'passed'
        // Final status for each step
        const stepPassed = role === 'judge' ? passed : true
        store.setStepStatus(role, stepPassed ? 'done' : 'failed', ai)
      })

      // Handle judge failure
      if (result.status === 'max_retries') {
        store.setStepStatus('judge', 'failed')
      }
    },
    [store]
  )

  /**
   * Simulates step-by-step animation while the pipeline is running.
   * Since the backend is synchronous, we show estimated timing.
   */
  const startProgressAnimation = useCallback(() => {
    const delays = [0, 8000, 18000, 28000, 38000]
    const timers: ReturnType<typeof setTimeout>[] = []

    AGENT_ORDER.forEach((role, i) => {
      const t = setTimeout(() => {
        if (useSolveStore.getState().solving) {
          // Mark previous steps done
          AGENT_ORDER.slice(0, i).forEach((r) => {
            if (useSolveStore.getState().pipelineSteps.find((s) => s.role === r)?.status === 'active') {
              useSolveStore.getState().setStepStatus(r, 'done')
            }
          })
          useSolveStore.getState().setStepStatus(role, 'active')
        }
      }, delays[i])
      timers.push(t)
    })

    return () => timers.forEach(clearTimeout)
  }, [])

  const solve = useCallback(async () => {
    const { problem, language, imageFile, aiMode, manualOverrides, solving } = store

    if (solving) return
    if (!problem.trim() && !imageFile) {
      toast.error('Enter a problem or upload a screenshot.')
      return
    }

    store.setSolving(true)
    store.resetPipeline()

    const cancelAnimation = startProgressAnimation()

    try {
      let result: SolveResult

      const overrides = aiMode === 'manual' && Object.keys(manualOverrides).length > 0
        ? manualOverrides
        : null

      if (imageFile) {
        result = await api.solveImage(imageFile, language, problem, overrides)
      } else {
        result = await api.solveText(problem, language, overrides)
      }

      cancelAnimation()
      applyPipelineEvents(result)
      store.setResult(result)

      if (result.status === 'passed') {
        toast.success(`Solved in ${result.iterations_used} iteration${result.iterations_used !== 1 ? 's' : ''}!`)
      } else {
        toast('Best attempt shown — could not pass all tests.', { icon: '⚠️' })
      }

      // Refresh usage stats
      api.getUsage().then(store.setUsage).catch(() => {})

    } catch (err: unknown) {
      cancelAnimation()

      // Rate limit error (structured object from interceptor)
      if (isRateLimitError(err)) {
        store.setRateLimitInfo({ ai: err.ai, ai_label: err.ai_label, message: err.message })
        AGENT_ORDER.forEach((r) => store.setStepStatus(r, 'failed'))
        toast.error(`${err.ai_label} rate limit hit. Switch AI or wait for reset.`)
      } else {
        const message = err instanceof Error ? err.message : 'Unexpected error'
        store.setError(message)
        AGENT_ORDER.forEach((r) => store.setStepStatus(r, 'failed'))
        toast.error(message)
      }
    } finally {
      store.setSolving(false)
    }
  }, [store, startProgressAnimation, applyPipelineEvents])

  return { solve }
}
