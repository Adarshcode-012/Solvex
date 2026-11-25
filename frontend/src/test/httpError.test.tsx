import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { OutputPanel } from '@/components/OutputPanel'
import { useSolveStore } from '@/store/useSolveStore'

it('shows a server failure with its request ID without a startup hint', () => {
  useSolveStore.getState().resetPipeline()
  useSolveStore.getState().setError('Solve failed. (Request ID: test-request)')
  render(<OutputPanel />)
  expect(screen.getByText('Solve failed. (Request ID: test-request)')).toBeInTheDocument()
  expect(screen.queryByText(/Make sure the backend/)).not.toBeInTheDocument()
})

it('shows the startup hint for network failures', () => {
  useSolveStore.getState().resetPipeline()
  useSolveStore.getState().setError('network_error: Network Error')
  render(<OutputPanel />)
  expect(screen.getByText(/Make sure the backend/)).toBeInTheDocument()
})
