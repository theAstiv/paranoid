import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('./api.js', () => ({ getActiveRun: vi.fn() }))

import { getActiveRun } from './api.js'
import { watchActiveRun, activeRunMessage, WATCH_INTERVAL_MS } from './run_watch.js'

const RUN = { kind: 'run', started_at: '2026-11-19T10:00:00Z' }

function setVisibility(state) {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state })
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  setVisibility('visible')
  getActiveRun.mockResolvedValue({ active_run: null })
})

afterEach(() => {
  vi.useRealTimers()
  setVisibility('visible')
})

describe('watchActiveRun', () => {
  it('checks at once, then every interval, and reports a run', async () => {
    const onActive = vi.fn()
    const watch = watchActiveRun('m1', onActive)
    await vi.advanceTimersByTimeAsync(0)
    expect(getActiveRun).toHaveBeenCalledWith('m1')
    expect(onActive).not.toHaveBeenCalled()

    getActiveRun.mockResolvedValue({ active_run: RUN })
    await vi.advanceTimersByTimeAsync(WATCH_INTERVAL_MS)

    expect(getActiveRun).toHaveBeenCalledTimes(2)
    expect(onActive).toHaveBeenCalledWith(RUN)
    watch.stop()
  })

  it('skips the first check when immediate is false', async () => {
    const watch = watchActiveRun('m1', vi.fn(), { immediate: false })
    await vi.advanceTimersByTimeAsync(0)
    expect(getActiveRun).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(WATCH_INTERVAL_MS)
    expect(getActiveRun).toHaveBeenCalledTimes(1)
    watch.stop()
  })

  it('does not poll while the tab is hidden, and checks when it comes back', async () => {
    setVisibility('hidden')
    const watch = watchActiveRun('m1', vi.fn())
    await vi.advanceTimersByTimeAsync(WATCH_INTERVAL_MS * 3)
    expect(getActiveRun).not.toHaveBeenCalled()

    setVisibility('visible')
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(0)

    expect(getActiveRun).toHaveBeenCalledTimes(1)
    watch.stop()
  })

  it('does not check while skip() says a run is already followed', async () => {
    let following = true
    const onActive = vi.fn()
    const watch = watchActiveRun('m1', onActive, { skip: () => following })
    getActiveRun.mockResolvedValue({ active_run: RUN })
    await vi.advanceTimersByTimeAsync(WATCH_INTERVAL_MS * 2)
    expect(getActiveRun).not.toHaveBeenCalled()

    following = false
    await vi.advanceTimersByTimeAsync(WATCH_INTERVAL_MS)
    expect(onActive).toHaveBeenCalledTimes(1)
    watch.stop()
  })

  it('ignores a failed check and retries on the next tick', async () => {
    getActiveRun.mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ active_run: RUN })
    const onActive = vi.fn()
    const watch = watchActiveRun('m1', onActive)
    await vi.advanceTimersByTimeAsync(0)
    expect(onActive).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(WATCH_INTERVAL_MS)

    expect(onActive).toHaveBeenCalledWith(RUN)
    watch.stop()
  })

  it('stops checking after stop(), even for a check already in flight', async () => {
    let resolve
    getActiveRun.mockReturnValueOnce(new Promise(r => { resolve = r }))
    const onActive = vi.fn()
    const watch = watchActiveRun('m1', onActive)
    watch.stop()
    resolve({ active_run: RUN })
    await vi.advanceTimersByTimeAsync(WATCH_INTERVAL_MS * 2)

    expect(onActive).not.toHaveBeenCalled()
    expect(getActiveRun).toHaveBeenCalledTimes(1)
    document.dispatchEvent(new Event('visibilitychange'))
    expect(getActiveRun).toHaveBeenCalledTimes(1)
  })
})

describe('activeRunMessage', () => {
  it('names the kind of run', () => {
    expect(activeRunMessage('extract')).toMatch(/context extraction/)
    expect(activeRunMessage('run')).toMatch(/re-run/)
  })
})
