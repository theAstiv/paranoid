import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/svelte'
import { tick } from 'svelte'
import { get } from 'svelte/store'

// Every API call resolves to an empty list; the shell only needs to boot.
vi.mock('./lib/api.js', async (importOriginal) => {
  const actual = await importOriginal()
  return Object.fromEntries(
    Object.keys(actual).map(name => [name, vi.fn().mockResolvedValue([])]),
  )
})

import App from './App.svelte'
import { getConfig, fetchMe } from './lib/api.js'
import { menuOpen, notification, notify, currentUser, config } from './lib/stores.js'

beforeEach(() => {
  vi.clearAllMocks()
  window.location.hash = '#/'
  menuOpen.set(null)
  notification.set(null)
  currentUser.set(null)
  config.set(null)
  getConfig.mockResolvedValue({ first_run: false })
  fetchMe.mockResolvedValue(null)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('App — toasts are announced (BB-102)', () => {
  it('keeps a polite live region in the page before any toast', async () => {
    render(App)
    const region = await screen.findByTestId('toast-region')
    expect(region.getAttribute('role')).toBe('status')
    expect(region.getAttribute('aria-live')).toBe('polite')
    expect(region.textContent.trim()).toBe('')
  })

  it('puts a new toast inside the region; an error one is also an alert', async () => {
    render(App)
    const region = await screen.findByTestId('toast-region')

    notify('error', 'Export failed: boom')
    await tick()

    expect(within(region).getByText('Export failed: boom')).toBeInTheDocument()
    expect(within(region).getByRole('alert')).toBeInTheDocument()

    notify('success', 'Settings saved')
    await tick()
    expect(within(region).getByText('Settings saved')).toBeInTheDocument()
    expect(within(region).queryByRole('alert')).toBeNull()
  })
})

describe('App — menus (BB-100)', () => {
  it.each([
    ['Switch project', 'project'],
    ['User menu', 'user'],
    ['Notifications', 'notif'],
  ])('%s: aria-expanded follows the menu and Escape closes it and refocuses the trigger', async (label, name) => {
    render(App)
    const trigger = await screen.findByRole('button', { name: label })
    expect(trigger.getAttribute('aria-haspopup')).toBe('menu')
    expect(trigger.getAttribute('aria-expanded')).toBe('false')

    await fireEvent.click(trigger)
    expect(get(menuOpen)).toBe(name)
    expect(trigger.getAttribute('aria-expanded')).toBe('true')

    await fireEvent.keyDown(window, { key: 'Escape' })

    expect(get(menuOpen)).toBeNull()
    expect(trigger.getAttribute('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(trigger)
  })

  it('ignores Escape when no menu is open', async () => {
    render(App)
    await screen.findByRole('button', { name: 'User menu' })
    await fireEvent.keyDown(window, { key: 'Escape' })
    expect(get(menuOpen)).toBeNull()
  })
})

describe('App — config needs a session (review S2)', () => {
  it('does not fetch config while nobody is signed in', async () => {
    window.location.hash = '#/register'
    render(App)
    await waitFor(() => expect(fetchMe).toHaveBeenCalled())
    await tick()
    expect(getConfig).not.toHaveBeenCalled()
    expect(window.location.hash).toBe('#/register')
  })

  it('fetches config once a user is current, and follows first_run to Settings', async () => {
    getConfig.mockResolvedValue({ first_run: true })
    fetchMe.mockImplementation(async () => {
      const user = { id: 'u-1', username: 'alice' }
      currentUser.set(user)
      return user
    })
    render(App)
    await waitFor(() => expect(getConfig).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(window.location.hash).toBe('#/settings'))
  })
})

describe('App — sidebar version (review F1)', () => {
  it('shows the server version from config, not a hard-coded one', async () => {
    getConfig.mockResolvedValue({ first_run: false, version: '1.6.0' })
    fetchMe.mockImplementation(async () => {
      const user = { id: 'u-1', username: 'alice' }
      currentUser.set(user)
      return user
    })
    render(App)
    expect(await screen.findByText('v1.6.0')).toBeInTheDocument()
    expect(screen.queryByText('v1.5')).toBeNull()
  })

  it('shows no version before config has loaded', async () => {
    render(App)
    await screen.findByRole('button', { name: 'User menu' })
    expect(screen.queryByText(/^v\d/)).toBeNull()
  })
})

describe('App — unknown routes and titles (BB-113, BB-109)', () => {
  it('shows a not-found page with a link home for an unknown hash', async () => {
    window.location.hash = '#/no/such/page'
    render(App)
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Go to Threat Models' })).toBeInTheDocument()
    await waitFor(() => expect(document.title).toBe('Page not found · Paranoid'))
  })

  it('titles the tab after the screen', async () => {
    window.location.hash = '#/settings'
    render(App)
    await waitFor(() => expect(document.title).toBe('Settings · Paranoid'))
  })
})
