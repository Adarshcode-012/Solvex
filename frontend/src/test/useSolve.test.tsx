import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useSolve } from '@/hooks/useSolve'
import { useSolveStore } from '@/store/useSolveStore'
import { makeResult } from './fixtures'
import { api } from '@/utils/api'

vi.mock('@/utils/api', () => ({
  api: {
    solveText: vi.fn(),
    solveImage: vi.fn(),
    startSolveJob: vi.fn(),
    getSolveJob: vi.fn(),
    getUsage: vi.fn().mockResolvedValue(null),
  },
}))

describe('useSolve', () => {
  beforeEach(() => {
    useSolveStore.getState().resetPipeline()
    useSolveStore.getState().setProblem('Print one')
    useSolveStore.getState().setError(null)
    useSolveStore.getState().setRateLimitInfo(null)
    vi.clearAllMocks()
  })

  it('handles a successful solve', async () => {
    vi.mocked(api.startSolveJob).mockResolvedValue({ job_id: 'job-1' })
    vi.mocked(api.getSolveJob)
      .mockResolvedValueOnce({ status: 'running', events: [{ agent: 'analyzer', status: 'started' }], result: null, error: null })
      .mockResolvedValueOnce({ status: 'complete', events: [{ agent: 'analyzer', status: 'done' }], result: makeResult(), error: null })
    const { result } = renderHook(() => useSolve())

    await act(async () => {
      await result.current.solve()
    })

    expect(useSolveStore.getState().result?.status).toBe('passed')
    expect(useSolveStore.getState().solving).toBe(false)
  })

  it('maps a structured rate-limit error', async () => {
    vi.mocked(api.startSolveJob).mockResolvedValue({ job_id: 'job-2' })
    vi.mocked(api.getSolveJob).mockResolvedValue({
      status: 'failed', events: [], result: null,
      error: { type: 'rate_limit', ai: 'claude', ai_label: 'Claude', message: 'Limit reached' },
    })
    const { result } = renderHook(() => useSolve())

    await act(async () => {
      await result.current.solve()
    })

    await waitFor(() => expect(useSolveStore.getState().rateLimitInfo).toMatchObject({ ai: 'claude' }))
    expect(useSolveStore.getState().error).toBeNull()
  })

  it('stores a generic error', async () => {
    vi.mocked(api.startSolveJob).mockResolvedValue({ job_id: 'job-3' })
    vi.mocked(api.getSolveJob).mockResolvedValue({
      status: 'failed', events: [], result: null,
      error: { code: 'solve_failed', message: 'network failure' },
    })
    const { result } = renderHook(() => useSolve())

    await act(async () => {
      await result.current.solve()
    })

    expect(useSolveStore.getState().error).toBe('network failure')
  })
})
