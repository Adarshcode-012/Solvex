import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { OutputPanel } from '@/components/OutputPanel'
import { useSolveStore } from '@/store/useSolveStore'
import { makeResult } from './fixtures'

describe('OutputPanel status rendering', () => {
  beforeEach(() => {
    useSolveStore.getState().resetPipeline()
    useSolveStore.getState().setSolving(false)
  })

  it('renders a verified pass', () => {
    useSolveStore.getState().setResult(makeResult())
    render(<OutputPanel />)
    expect(screen.getByText('ALL TESTS PASSED')).toBeInTheDocument()
  })

  it('renders an unverified result', () => {
    useSolveStore.getState().setResult(makeResult({ status: 'unverified', verified: false }))
    render(<OutputPanel />)
    expect(screen.getAllByText('NOT VERIFIED').length).toBeGreaterThan(0)
    expect(screen.getByText(/Judge0 not available/)).toBeInTheDocument()
  })

  it('renders generated code for an unverified result', () => {
    useSolveStore.getState().setResult(makeResult({
      status: 'unverified',
      verified: false,
      final_solution: 'print(42)',
      timings: [{ role: 'analyzer', seconds: 1.25 }],
    }))
    render(<OutputPanel />)

    expect(screen.getAllByText('NOT VERIFIED').length).toBeGreaterThan(0)
    expect(document.querySelector('.cm-content')?.textContent).toContain('print(42)')
    expect(screen.getByText('analyzer: 1.25s')).toBeInTheDocument()
  })

  it('explains when no code was produced', () => {
    useSolveStore.getState().setResult(makeResult({
      status: 'unverified',
      verified: false,
      final_solution: '',
    }))
    render(<OutputPanel />)

    expect(screen.getByText('No code was produced.')).toBeInTheDocument()
  })

  it('renders a generic error state', () => {
    useSolveStore.getState().setError('Backend unavailable')
    render(<OutputPanel />)
    expect(screen.getByText('Backend unavailable')).toBeInTheDocument()
    expect(screen.getByText('FAILED')).toBeInTheDocument()
  })

  it('shows the Retry-After time in the rate-limit card', () => {
    useSolveStore.getState().setRateLimitInfo({
      ai: 'system', ai_label: 'SolveX', message: 'Daily cap reached', retryAfterSeconds: 75,
    })
    render(<OutputPanel />)
    expect(screen.getByText('Try again in 75 seconds.')).toBeInTheDocument()
  })
})
