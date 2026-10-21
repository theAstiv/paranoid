import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { getModel, getConfig, login, subscribeToRun, followRun, getModelDiagram, downloadExport } from './api.js'
import { getStoredToken, setStoredToken } from './stores.js'

function jsonResponse(body, init = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
}

beforeEach(() => {
  localStorage.clear()
  window.location.hash = ''
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('request() — auth header', () => {
  it('does not attach Authorization header when no token stored', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: 'm1' }))
    vi.stubGlobal('fetch', fetchMock)

    await getModel('m1')

    const [, opts] = fetchMock.mock.calls[0]
    expect(opts.headers.Authorization).toBeUndefined()
  })

  it('attaches Authorization: Bearer header when a token is stored', async () => {
    setStoredToken('tok-abc')
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: 'm1' }))
    vi.stubGlobal('fetch', fetchMock)

    await getModel('m1')

    const [, opts] = fetchMock.mock.calls[0]
    expect(opts.headers.Authorization).toBe('Bearer tok-abc')
  })
})

describe('getModelDiagram()', () => {
  it('fetches a single diagram by id', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: 'd1', content: 'aGVsbG8=' }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await getModelDiagram('m1', 'd1')

    expect(result).toEqual({ id: 'd1', content: 'aGVsbG8=' })
    expect(fetchMock.mock.calls[0][0]).toContain('/models/m1/diagrams/d1')
  })
})

describe('request() — response handling', () => {
  it('returns parsed JSON on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ id: 'm1', title: 'Foo' })))
    const result = await getModel('m1')
    expect(result).toEqual({ id: 'm1', title: 'Foo' })
  })

  it('returns null on 204 No Content', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
    const result = await getModel('m1')
    expect(result).toBeNull()
  })

  it('throws an Error with the backend detail message on non-ok response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'Model not found' }), { status: 404 })
      )
    )
    await expect(getModel('missing')).rejects.toThrow('Model not found')
  })

  it('falls back to statusText when the error body is not JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('not json', { status: 500, statusText: 'Server Error' }))
    )
    await expect(getModel('m1')).rejects.toThrow('Server Error')
  })
})

describe('request() — 401 refresh-and-retry', () => {
  it('refreshes the token and retries once on a single 401', async () => {
    setStoredToken('expired-tok')
    const fetchMock = vi.fn()
      // 1. Initial request -> 401
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Unauthorized' }), { status: 401 }))
      // 2. Refresh call -> new token
      .mockResolvedValueOnce(jsonResponse({ access_token: 'new-tok' }))
      // 3. Retried request -> success
      .mockResolvedValueOnce(jsonResponse({ id: 'm1' }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await getModel('m1')

    expect(result).toEqual({ id: 'm1' })
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(fetchMock.mock.calls[1][0]).toContain('/auth/refresh')
    // Retried call carries the newly-refreshed token
    expect(fetchMock.mock.calls[2][1].headers.Authorization).toBe('Bearer new-tok')
    expect(getStoredToken()).toBe('new-tok')
  })

  it('clears auth and redirects to login when refresh itself fails', async () => {
    setStoredToken('expired-tok')
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Unauthorized' }), { status: 401 }))
      .mockResolvedValueOnce(new Response(null, { status: 401 })) // refresh fails
    vi.stubGlobal('fetch', fetchMock)

    await expect(getModel('m1')).rejects.toThrow('Session expired')
    expect(getStoredToken()).toBeNull()
    expect(window.location.hash).toBe('#/login')
  })

  it('clears auth and redirects to login when the retried request 401s again', async () => {
    setStoredToken('expired-tok')
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Unauthorized' }), { status: 401 }))
      .mockResolvedValueOnce(jsonResponse({ access_token: 'new-tok' }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Unauthorized' }), { status: 401 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(getModel('m1')).rejects.toThrow('Session expired')
    expect(getStoredToken()).toBeNull()
    expect(window.location.hash).toBe('#/login')
  })
})

describe('downloadExport() — BB-61', () => {
  function fileResponse(init = {}) {
    return new Response('{"ok":true}', {
      status: 200,
      headers: { 'Content-Disposition': 'attachment; filename="My Model.json"' },
      ...init,
    })
  }

  let created
  let clicked

  beforeEach(() => {
    created = []
    clicked = []
    URL.createObjectURL = vi.fn((blob) => { created.push(blob); return 'blob:test' })
    URL.revokeObjectURL = vi.fn()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () {
      clicked.push(this.download)
    })
  })

  it('sends the Bearer token and saves under the Content-Disposition filename', async () => {
    setStoredToken('tok-abc')
    const fetchMock = vi.fn().mockResolvedValue(fileResponse())
    vi.stubGlobal('fetch', fetchMock)

    await downloadExport('m1', 'json')

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/export/m1?format=json')
    expect(opts.headers.Authorization).toBe('Bearer tok-abc')
    expect(created).toHaveLength(1)
    // Not instanceof Blob: Response.blob() and jsdom's Blob can be different realms on CI.
    expect(await created[0].text()).toBe('{"ok":true}')
    expect(clicked).toEqual(['My Model.json'])
  })

  it('forwards status_filter and falls back to a default filename', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('# md', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await downloadExport('m1', 'markdown', 'approved')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/export/m1?format=markdown&status_filter=approved')
    expect(clicked).toEqual(['threat-model-m1.md'])
  })

  it('refreshes once on a 401 and retries with the new token', async () => {
    setStoredToken('expired-tok')
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Authentication required' }), { status: 401 }))
      .mockResolvedValueOnce(jsonResponse({ access_token: 'new-tok' }))
      .mockResolvedValueOnce(fileResponse())
    vi.stubGlobal('fetch', fetchMock)

    await downloadExport('m1', 'json')

    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(fetchMock.mock.calls[1][0]).toContain('/auth/refresh')
    expect(fetchMock.mock.calls[2][1].headers.Authorization).toBe('Bearer new-tok')
    expect(clicked).toEqual(['My Model.json'])
  })

  it('throws the server detail on a 404 and saves nothing', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Model not found' }), { status: 404 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(downloadExport('m1', 'pdf')).rejects.toThrow('Model not found')
    expect(created).toHaveLength(0)
    expect(clicked).toHaveLength(0)
  })
})

describe('login()', () => {
  it('stores the access token and sets currentUser on success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ access_token: 'fresh-tok', user: { id: 'u1', username: 'a' } }))
    )
    const { currentUser } = await import('./stores.js')
    const { get } = await import('svelte/store')

    await login({ username: 'a', password: 'pw' })

    expect(getStoredToken()).toBe('fresh-tok')
    expect(get(currentUser)).toEqual({ id: 'u1', username: 'a' })
  })

  it('rejects a wrong password with the server detail and no refresh (BB-112)', async () => {
    setStoredToken('old-tok')
    window.location.hash = '#/login'
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Invalid credentials' }), { status: 401 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(login({ username: 'a', password: 'wrong' })).rejects.toThrow('Invalid credentials')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/auth/login')
  })
})

describe('getConfig()', () => {
  it('issues a GET to /api/config', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ default_provider: 'anthropic' }))
    vi.stubGlobal('fetch', fetchMock)

    await getConfig()

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/config')
    expect(opts.method).toBe('GET')
  })
})

describe('subscribeToRun() — SSE parsing', () => {
  function sseStreamResponse(chunks) {
    const encoder = new TextEncoder()
    const stream = new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
        controller.close()
      },
    })
    return new Response(stream, { status: 200 })
  }

  it('parses SSE events and fires onEvent for each, onDone once on complete', async () => {
    const events = [
      `data: ${JSON.stringify({ step: 'summarize' })}\n\n`,
      `data: ${JSON.stringify({ step: 'complete' })}\n\n`,
    ]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseStreamResponse(events)))

    const onEvent = vi.fn()
    const onError = vi.fn()
    const onDone = vi.fn()

    subscribeToRun('m1', new FormData(), onEvent, onError, onDone)

    await vi.waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))
    expect(onEvent).toHaveBeenCalledTimes(2)
    expect(onEvent).toHaveBeenNthCalledWith(1, { step: 'summarize' })
    expect(onEvent).toHaveBeenNthCalledWith(2, { step: 'complete' })
    expect(onError).not.toHaveBeenCalled()
  })

  it('skips malformed SSE JSON without calling onEvent or throwing', async () => {
    const events = [
      `data: not-json\n\n`,
      `data: ${JSON.stringify({ step: 'complete' })}\n\n`,
    ]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseStreamResponse(events)))

    const onEvent = vi.fn()
    const onDone = vi.fn()

    subscribeToRun('m1', new FormData(), onEvent, vi.fn(), onDone)

    await vi.waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))
    expect(onEvent).toHaveBeenCalledTimes(1)
    expect(onEvent).toHaveBeenCalledWith({ step: 'complete' })
  })

  it('calls onError and onDone when the initial response is not ok', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'boom' }), { status: 500 }))
    )
    const onError = vi.fn()
    const onDone = vi.fn()

    subscribeToRun('m1', new FormData(), vi.fn(), onError, onDone)

    await vi.waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))
    expect(onError).toHaveBeenCalledTimes(1)
    expect(onError.mock.calls[0][0].message).toBe('boom')
    expect(onError.mock.calls[0][0].status).toBe(500)
  })

  // BB-71: Results tells "no run behind this model" (404) from a network failure.
  it('followRun() GETs the run events and reports a 404 by status', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'This model has no run in progress.' }), { status: 404 })
    )
    vi.stubGlobal('fetch', fetchMock)
    const onError = vi.fn()
    const onDone = vi.fn()

    followRun('m1', vi.fn(), onError, onDone)

    await vi.waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/models\/m1\/run\/events$/)
    expect(fetchMock.mock.calls[0][1].method).toBe('GET')
    expect(onError.mock.calls[0][0].status).toBe(404)
  })

  it('returns an abort function that aborts the underlying fetch', async () => {
    const fetchMock = vi.fn((url, opts) => {
      return new Promise((_, reject) => {
        const rejectAborted = () => {
          const err = new Error('aborted')
          err.name = 'AbortError'
          reject(err)
        }
        if (opts.signal.aborted) rejectAborted()
        else opts.signal.addEventListener('abort', rejectAborted)
      })
    })
    vi.stubGlobal('fetch', fetchMock)

    const onError = vi.fn()
    const onDone = vi.fn()
    const abort = subscribeToRun('m1', new FormData(), vi.fn(), onError, onDone)
    abort()

    await vi.waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))
    // AbortError is swallowed, not surfaced as onError
    expect(onError).not.toHaveBeenCalled()
  })
})
