import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import AdminUsers from './AdminUsers.svelte'

vi.mock('svelte-spa-router', () => ({
  push: vi.fn(),
}))

vi.mock('../lib/api.js', () => ({
  listAllUsers: vi.fn(),
  register: vi.fn(),
}))

vi.mock('../lib/stores.js', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, notify: vi.fn() }
})

import { push } from 'svelte-spa-router'
import { listAllUsers, register } from '../lib/api.js'
import { notify, currentUser, authLoading } from '../lib/stores.js'

const userA = {
  id: 'u1', username: 'alice', display_name: 'Alice A', email: 'alice@x.com',
  is_admin: false, is_active: true, last_login_at: null, created_at: '2026-01-01T00:00:00.000Z',
}

beforeEach(() => {
  vi.clearAllMocks()
  currentUser.set(null)
  authLoading.set(true)
  listAllUsers.mockResolvedValue([])
})

describe('AdminUsers — create user', () => {
  it('creates a user through register without signing in as them', async () => {
    currentUser.set({ id: 'admin', is_admin: true })
    authLoading.set(false)
    register.mockResolvedValue({ ...userA, id: 'u9', username: 'bob' })
    render(AdminUsers)
    await waitFor(() => expect(screen.getByText('Create user')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Create user'))
    await fireEvent.input(screen.getByLabelText('Username'), { target: { value: 'bob' } })
    await fireEvent.input(screen.getByLabelText('Email'), { target: { value: 'bob@x.com' } })
    await fireEvent.input(screen.getByLabelText(/^Initial password/), { target: { value: 'password123' } })
    await fireEvent.click(screen.getByText('Create'))

    await waitFor(() => expect(register).toHaveBeenCalledWith({
      username: 'bob', email: 'bob@x.com', password: 'password123', display_name: undefined,
    }))
    await waitFor(() => expect(notify).toHaveBeenCalledWith('success', 'Created user @bob'))
    expect(screen.getByText('@bob')).toBeInTheDocument()
  })
})

describe('AdminUsers — auth gating', () => {
  it('does not redirect or fetch while auth is still loading', () => {
    render(AdminUsers)
    expect(push).not.toHaveBeenCalled()
    expect(listAllUsers).not.toHaveBeenCalled()
  })

  it('redirects non-admins to the home page once auth resolves', async () => {
    currentUser.set({ id: 'u1', is_admin: false })
    authLoading.set(false)
    render(AdminUsers)
    await waitFor(() => expect(push).toHaveBeenCalledWith('/'))
    expect(listAllUsers).not.toHaveBeenCalled()
  })

  it('fetches users for an admin once auth resolves', async () => {
    currentUser.set({ id: 'admin-1', is_admin: true })
    authLoading.set(false)
    render(AdminUsers)
    await waitFor(() => expect(listAllUsers).toHaveBeenCalled())
    expect(push).not.toHaveBeenCalled()
  })

  it('notifies on load failure', async () => {
    currentUser.set({ id: 'admin-1', is_admin: true })
    authLoading.set(false)
    listAllUsers.mockRejectedValue(new Error('forbidden'))
    render(AdminUsers)
    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('forbidden')))
  })
})

describe('AdminUsers — rendering', () => {
  beforeEach(() => {
    currentUser.set({ id: 'admin-1', is_admin: true })
    authLoading.set(false)
  })

  it('shows an empty state when there are no users', async () => {
    render(AdminUsers)
    await waitFor(() => expect(screen.getByText('No users registered.')).toBeInTheDocument())
  })

  it('renders a row per user with username and email', async () => {
    listAllUsers.mockResolvedValue([userA])
    render(AdminUsers)
    await waitFor(() => expect(screen.getByText('Alice A')).toBeInTheDocument())
    expect(screen.getByText('@alice')).toBeInTheDocument()
    expect(screen.getByText('alice@x.com')).toBeInTheDocument()
  })

  it('shows the user count', async () => {
    listAllUsers.mockResolvedValue([userA])
    render(AdminUsers)
    await waitFor(() => expect(screen.getByText('1 user')).toBeInTheDocument())
  })

  it('marks the current user with "(you)"', async () => {
    currentUser.set({ id: 'u1', is_admin: true })
    listAllUsers.mockResolvedValue([userA])
    render(AdminUsers)
    await waitFor(() => expect(screen.getByText('(you)')).toBeInTheDocument())
  })

  it('shows an admin chip for admin users and a member chip otherwise', async () => {
    listAllUsers.mockResolvedValue([userA, { ...userA, id: 'u2', username: 'admin2', is_admin: true }])
    render(AdminUsers)
    await waitFor(() => expect(screen.getByText('member')).toBeInTheDocument())
    expect(screen.getByText('admin')).toBeInTheDocument()
  })

  it('shows an inactive chip for deactivated users', async () => {
    listAllUsers.mockResolvedValue([{ ...userA, is_active: false }])
    render(AdminUsers)
    await waitFor(() => expect(screen.getByText('inactive')).toBeInTheDocument())
  })

  it('shows "never" for a user with no last_login_at', async () => {
    listAllUsers.mockResolvedValue([userA])
    render(AdminUsers)
    await waitFor(() => expect(screen.getByText('never')).toBeInTheDocument())
  })
})
