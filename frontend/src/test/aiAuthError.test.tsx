import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { OutputPanel } from '@/components/OutputPanel'
import { useSolveStore } from '@/store/useSolveStore'
import { formatApiError, formatApiErrorForResponse } from '@/utils/api'

describe('AI provider authentication errors', () => {
  it('maps the safe backend error and shows it in OutputPanel', () => {
    const message = 'Gemini rejected the API key. Check the key for Gemini and restart the backend.'
    const displayValue = formatApiError({ code: 'ai_auth_failed', message })

    expect(displayValue).toBe(`ai_auth_failed: ${message}`)

    useSolveStore.getState().resetPipeline()
    useSolveStore.getState().setError(displayValue)
    render(<OutputPanel />)

    expect(screen.getByText('⚠️ AI provider key rejected')).toBeInTheDocument()
    expect(screen.getByText(message)).toBeInTheDocument()
  })

  it('maps provider timeouts and shows a useful message in OutputPanel', () => {
    const message = 'Gemini request timed out after 120 seconds. Check backend connectivity and try again.'
    const displayValue = formatApiError({ code: 'ai_provider_timeout', message })

    expect(displayValue).toBe('ai_provider_timeout: ' + message)

    useSolveStore.getState().resetPipeline()
    useSolveStore.getState().setError(displayValue)
    render(<OutputPanel />)

    expect(screen.getByText('⏱️ AI request timed out')).toBeInTheDocument()
    expect(screen.getByText(message)).toBeInTheDocument()
  })

  it('shows a useful timeout when a 504 response has no structured body', () => {
    const displayValue = formatApiErrorForResponse(undefined, 504)
    const message = 'The AI request timed out. Check backend and provider connectivity, then retry.'

    expect(displayValue).toBe('ai_provider_timeout: ' + message)

    useSolveStore.getState().resetPipeline()
    useSolveStore.getState().setError(displayValue)
    render(<OutputPanel />)

    expect(screen.getByText('⏱️ AI request timed out')).toBeInTheDocument()
    expect(screen.getByText(message)).toBeInTheDocument()
  })
})
