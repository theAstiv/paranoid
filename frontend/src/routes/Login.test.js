import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import Login from './Login.svelte'

vi.mock('svelte-spa-router', () => ({
  push: vi.fn(),
}))

vi.mock('../lib/api.js', () => ({
  login: vi.fn(),
}))

import { push } from 'svelte-spa-router'
import { login } from '../lib/api.js'

beforeEach(() => {
  vi.clearAllMocks()
})

describe('Login', () => {
  it('logs in and navigates home on success', async () => {
    login.mockResolvedValue({ access_token: 'tok', user: { id: 'u1' } })
    render(Login)

    await fireEvent.input(screen.getByLabelText('Username'), { target: { value: 'admin' } })
    await fireEvent.input(screen.getByLabelText('Password'), { target: { value: 'secret123' } })
    await fireEvent.click(screen.getByText('Sign in →'))

    await waitFor(() => expect(login).toHaveBeenCalledWith({ username: 'admin', password: 'secret123' }))
    await waitFor(() => expect(push).toHaveBeenCalledWith('/'))
  })

  it('shows an error message on failed login and does not navigate', async () => {
    login.mockRejectedValue(new Error('Invalid credentials'))
    render(Login)

    await fireEvent.input(screen.getByLabelText('Username'), { target: { value: 'admin' } })
    await fireEvent.input(screen.getByLabelText('Password'), { target: { value: 'wrong' } })
    await fireEvent.click(screen.getByText('Sign in →'))

    await waitFor(() => expect(screen.getByText('Invalid credentials')).toBeInTheDocument())
    expect(push).not.toHaveBeenCalled()
  })

  it('shows a generic error when the thrown error has no message', async () => {
    login.mockRejectedValue({})
    render(Login)

    await fireEvent.input(screen.getByLabelText('Username'), { target: { value: 'admin' } })
    await fireEvent.input(screen.getByLabelText('Password'), { target: { value: 'wrong' } })
    await fireEvent.click(screen.getByText('Sign in →'))

    await waitFor(() => expect(screen.getByText('Login failed')).toBeInTheDocument())
  })

  it('shows a loading state while the request is in flight', async () => {
    let resolveLogin
    login.mockReturnValue(new Promise(r => { resolveLogin = r }))
    render(Login)

    await fireEvent.input(screen.getByLabelText('Username'), { target: { value: 'admin' } })
    await fireEvent.input(screen.getByLabelText('Password'), { target: { value: 'secret123' } })
    await fireEvent.click(screen.getByText('Sign in →'))

    expect(screen.getByText('Signing in…')).toBeInTheDocument()
    resolveLogin({ access_token: 'tok', user: {} })
    await waitFor(() => expect(push).toHaveBeenCalled())
  })

  it('links to the register page', () => {
    const { container } = render(Login)
    expect(container.querySelector('a[href="#/register"]')).not.toBeNull()
  })
})
