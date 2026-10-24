import { describe, it, expect } from 'vitest'
import { isKnownRoute, pageTitle, screenLabel } from './navigation.js'

const PATHS = ['/', '/settings', '/models/new', '/models/:id', '/models/:id/review', '/threats/:id/attack-tree', '*']

describe('pageTitle (BB-109)', () => {
  it.each([
    ['/', 'Threat Models · Paranoid'],
    ['/settings', 'Settings · Paranoid'],
    ['/models/new', 'New Model · Paranoid'],
    ['/models/abc', 'Results · Paranoid'],
    ['/models/abc/review', 'Review · Paranoid'],
    ['/models/abc/diff', 'Re-run Diff · Paranoid'],
    ['/threats/t1/attack-tree', 'Attack Tree · Paranoid'],
    ['/login', 'Sign in · Paranoid'],
  ])('%s -> %s', (location, title) => {
    expect(pageTitle(location)).toBe(title)
  })

  it('names the not-found page', () => {
    expect(pageTitle('/nope', false)).toBe('Page not found · Paranoid')
  })
})

describe('screenLabel (the breadcrumb, unchanged)', () => {
  it('keeps prefix matching and leaves model pages unnamed', () => {
    expect(screenLabel('/sources')).toBe('Code Sources')
    expect(screenLabel('/models/new')).toBe('New Model')
    expect(screenLabel('/models/abc')).toBe('')
  })
})

describe('isKnownRoute', () => {
  it('matches parameterised paths and ignores the catch-all', () => {
    expect(isKnownRoute('/models/abc/review', PATHS)).toBe(true)
    expect(isKnownRoute('/models/abc', PATHS)).toBe(true)
    expect(isKnownRoute('/models/abc/nope', PATHS)).toBe(false)
    expect(isKnownRoute('/no/such/page', PATHS)).toBe(false)
  })
})
