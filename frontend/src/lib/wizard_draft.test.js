import { describe, it, expect, vi, afterEach } from 'vitest'
import { loadDraft, saveDraft, clearDraft, DRAFT_KEY } from './wizard_draft.js'

afterEach(() => {
  vi.restoreAllMocks()
  sessionStorage.clear()
})

describe('wizard_draft', () => {
  it('round-trips a draft through sessionStorage', () => {
    saveDraft({ title: 'Payments', step: 3 })
    expect(JSON.parse(sessionStorage.getItem(DRAFT_KEY))).toEqual({ title: 'Payments', step: 3 })
    expect(loadDraft()).toEqual({ title: 'Payments', step: 3 })
    clearDraft()
    expect(loadDraft()).toBeNull()
  })

  it('returns null for nothing stored, bad JSON or a non-object', () => {
    expect(loadDraft()).toBeNull()
    sessionStorage.setItem(DRAFT_KEY, '{oops')
    expect(loadDraft()).toBeNull()
    sessionStorage.setItem(DRAFT_KEY, '[1,2]')
    expect(loadDraft()).toBeNull()
    sessionStorage.setItem(DRAFT_KEY, '"text"')
    expect(loadDraft()).toBeNull()
  })

  it('never throws when storage is unavailable (private mode, blocked site data)', () => {
    const boom = () => { throw new DOMException('denied', 'SecurityError') }
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(boom)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(boom)
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(boom)

    expect(() => saveDraft({ title: 'x' })).not.toThrow()
    expect(loadDraft()).toBeNull()
    expect(() => clearDraft()).not.toThrow()
  })
})
