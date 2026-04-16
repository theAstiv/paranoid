import { describe, it, expect, beforeEach, vi } from 'vitest'
import { get } from 'svelte/store'
import {
  models,
  currentModel,
  threats,
  pipelineEvents,
  pipelineRunning,
  notification,
  pendingCount,
  lastEvent,
  notify,
} from './stores.js'

beforeEach(() => {
  models.set([])
  currentModel.set(null)
  threats.set([])
  pipelineEvents.set([])
  pipelineRunning.set(false)
  notification.set(null)
})

describe('models store', () => {
  it('starts empty', () => {
    expect(get(models)).toEqual([])
  })

  it('holds model objects', () => {
    models.set([{ id: 'abc', title: 'Test' }])
    expect(get(models)).toHaveLength(1)
    expect(get(models)[0].title).toBe('Test')
  })
})

describe('pendingCount derived store', () => {
  it('is 0 when threats list is empty', () => {
    threats.set([])
    expect(get(pendingCount)).toBe(0)
  })

  it('counts only pending threats', () => {
    threats.set([
      { id: '1', status: 'pending' },
      { id: '2', status: 'approved' },
      { id: '3', status: 'pending' },
      { id: '4', status: 'rejected' },
    ])
    expect(get(pendingCount)).toBe(2)
  })
})

describe('lastEvent derived store', () => {
  it('is null when no events', () => {
    pipelineEvents.set([])
    expect(get(lastEvent)).toBeNull()
  })

  it('returns the last event in the array', () => {
    const events = [{ type: 'start' }, { type: 'step' }, { type: 'done' }]
    pipelineEvents.set(events)
    expect(get(lastEvent)).toEqual({ type: 'done' })
  })
})

describe('notify', () => {
  it('sets notification with type and message', () => {
    notify('error', 'Something failed')
    expect(get(notification)).toEqual({ type: 'error', message: 'Something failed' })
  })

  it('auto-clears success notification after 4s', async () => {
    vi.useFakeTimers()
    notify('success', 'Saved!')
    expect(get(notification)).not.toBeNull()
    vi.advanceTimersByTime(4000)
    expect(get(notification)).toBeNull()
    vi.useRealTimers()
  })

  it('does not auto-clear error notification', async () => {
    vi.useFakeTimers()
    notify('error', 'Bad thing')
    vi.advanceTimersByTime(10000)
    expect(get(notification)).not.toBeNull()
    vi.useRealTimers()
  })
})
