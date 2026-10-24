import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createChunkErrorHandler, RELOAD_WINDOW_MS } from './chunk_reload.js'

describe('createChunkErrorHandler (BB-57)', () => {
  let reload
  let clock

  beforeEach(() => {
    sessionStorage.clear()
    reload = vi.fn()
    clock = 1_000_000
  })

  const handler = () => createChunkErrorHandler({ storage: sessionStorage, reload, now: () => clock })

  it('reloads once on a missing chunk', () => {
    expect(handler()()).toBe(true)
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('does not reload again on a second error inside the window (the page after the reload)', () => {
    handler()()
    clock += 2_000
    // a fresh handler, as main.js creates one per page load
    expect(handler()()).toBe(false)
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('two events dispatched on the same page reload once', () => {
    const onError = handler()
    window.addEventListener('vite:preloadError', onError)
    window.dispatchEvent(new Event('vite:preloadError'))
    window.dispatchEvent(new Event('vite:preloadError'))
    window.removeEventListener('vite:preloadError', onError)
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('reloads again once the window has passed', () => {
    handler()()
    clock += RELOAD_WINDOW_MS + 1
    expect(handler()()).toBe(true)
    expect(reload).toHaveBeenCalledTimes(2)
  })

  it('never reloads when sessionStorage is unavailable (it could not be bounded)', () => {
    const broken = {
      getItem: () => { throw new Error('blocked') },
      setItem: () => { throw new Error('blocked') },
    }
    const onError = createChunkErrorHandler({ storage: broken, reload, now: () => clock })
    expect(onError()).toBe(false)
    expect(reload).not.toHaveBeenCalled()
  })
})
