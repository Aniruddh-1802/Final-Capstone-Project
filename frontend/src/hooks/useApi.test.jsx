import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', async (importOriginal) => ({ ...(await importOriginal()), api: { get: vi.fn() } }))
import { api } from '../api/client'
import { useApi } from './useApi'

// A promise we resolve by hand, so the test controls which response arrives last.
function deferred() {
  let resolve
  const promise = new Promise((r) => { resolve = r })
  return { promise, resolve }
}

describe('useApi', () => {
  beforeEach(() => vi.clearAllMocks())

  it('returns data and sends only non-empty params', async () => {
    api.get.mockResolvedValue({ data: { ok: 1 } })
    const { result } = renderHook(() => useApi('/x', { a: 1, b: '' }))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.data).toEqual({ ok: 1 })
    expect(api.get.mock.calls[0][1].params).toEqual({ a: 1 })
  })

  it('ignores a slow response for an OLD filter that arrives after the newest one', async () => {
    const slow = deferred()
    const fast = deferred()
    api.get.mockReturnValueOnce(slow.promise).mockReturnValueOnce(fast.promise)
    const { result, rerender } = renderHook(({ age }) => useApi('/analytics/summary', { age_group: age }), { initialProps: { age: 'old' } })
    rerender({ age: 'new' })                              // the user changed the filter; the first request is now stale
    await act(async () => { fast.resolve({ data: { which: 'new' } }) })
    await waitFor(() => expect(result.current.data).toEqual({ which: 'new' }))
    await act(async () => { slow.resolve({ data: { which: 'old' } }) })  // the stale response arrives last
    expect(result.current.data).toEqual({ which: 'new' })                // ...and must not overwrite the newest data
    expect(api.get.mock.calls[0][1].signal.aborted).toBe(true)           // the old request was also aborted
  })

  it('reports an error and supports retry via reload', async () => {
    api.get.mockRejectedValueOnce({ response: { status: 500, data: { error: { message: 'x' } } } }).mockResolvedValueOnce({ data: [1] })
    const { result } = renderHook(() => useApi('/x'))
    await waitFor(() => expect(result.current.error).toBeTruthy())
    act(() => result.current.reload())
    await waitFor(() => expect(result.current.data).toEqual([1]))
    expect(result.current.error).toBeNull()
  })

  it('does not call the API when disabled', () => {
    renderHook(() => useApi('/x', {}, { enabled: false }))
    expect(api.get).not.toHaveBeenCalled()
  })
})
