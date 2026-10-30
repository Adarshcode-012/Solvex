import { describe, expect, it } from 'vitest'
import { useSolveStore } from '@/store/useSolveStore'

describe('useSolveStore', () => {
  it('updates a pipeline step and resets pipeline state', () => {
    const store = useSolveStore.getState()
    store.resetPipeline()
    store.setStepStatus('judge', 'failed', 'judge0')

    expect(useSolveStore.getState().pipelineSteps.find((step) => step.role === 'judge')).toMatchObject({
      status: 'failed',
      ai: 'judge0',
    })

    store.setError('failure')
    store.resetPipeline()
    expect(useSolveStore.getState().pipelineSteps.every((step) => step.status === 'idle')).toBe(true)
    expect(useSolveStore.getState().result).toBeNull()
    expect(useSolveStore.getState().error).toBeNull()
  })
})