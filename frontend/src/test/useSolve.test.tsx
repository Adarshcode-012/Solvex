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
    vi.mocked(api.solveText).mockResolvedValue(makeResult())
    const { result } = renderHook(() => useSolve())

    await act(async () => {
      await result.current.solve()
    })

    expect(useSolveStore.getState().result?.status).toBe('passed')
    expect(useSolveStore.getState().solving).toBe(false)
  })

  it('maps a structured rate-limit error', async () => {
    vi.mocked(api.solveText).mockRejectedValue({
      type: 'rate_limit', ai: 'claude', ai_label: 'Claude', message: 'Limit reached',
    })
    const { result } = renderHook(() => useSolve())

    await act(async () => {
      await result.current.solve()
    })

    await waitFor(() => expect(useSolveStore.getState().rateLimitInfo).toMatchObject({ ai: 'claude' }))
    expect(useSolveStore.getState().error).toBeNull()
  })

  it('stores a generic error', async () => {
    vi.mocked(api.solveText).mockRejectedValue(new Error('network failure'))
    const { result } = renderHook(() => useSolve())

    await act(async () => {
      await result.current.solve()
    })

    expect(useSolveStore.getState().error).toBe('network failure')
  })
})