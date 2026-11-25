import { describe, expect, it } from 'vitest'
import { API_TIMEOUT_MS } from '@/utils/api'

describe('API client configuration', () => {
  it('allows slow solve requests up to ten minutes', () => {
    expect(API_TIMEOUT_MS).toBe(600_000)
  })
})
