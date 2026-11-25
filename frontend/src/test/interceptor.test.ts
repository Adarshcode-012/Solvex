import { expect, it, vi } from 'vitest'

const handlers = vi.hoisted(() => ({ reject: undefined as undefined | ((error: unknown) => Promise<never>) }))
vi.mock('axios', () => ({ default: { create: vi.fn(() => ({
  interceptors: { request: { use: vi.fn() }, response: { use: (_ok: unknown, reject: typeof handlers.reject) => { handlers.reject = reject } } },
})) } }))
import '@/utils/api'

it('HTTP errors retain server message and request ID', async () => {
  await expect(handlers.reject!({ response: { status: 500, data: { detail: 'Server failed safely', request_id: 'request-123' } }, message: 'Axios generic' }))
    .rejects.toThrow('Server failed safely (Request ID: request-123)')
})

it('network failures retain the network message', async () => {
  await expect(handlers.reject!({ message: 'Connection refused' })).rejects.toThrow('network_error: Connection refused')
})
