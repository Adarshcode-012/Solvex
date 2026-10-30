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

  it('renders a generic error state', () => {
    useSolveStore.getState().setError('Backend unavailable')
    render(<OutputPanel />)
    expect(screen.getByText('Backend unavailable')).toBeInTheDocument()
    expect(screen.getByText('FAILED')).toBeInTheDocument()
  })
})