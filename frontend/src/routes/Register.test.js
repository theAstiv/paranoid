import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import Register from './Register.svelte'

vi.mock('svelte-spa-router', () => ({
  push: vi.fn(),
}))

vi.mock('../lib/api.js', () => ({
  register: vi.fn(),
  login: vi.fn(),
}))

import { push } from 'svelte-spa-router'
import { register, login } from '../lib/api.js'

beforeEach(() => {
  vi.clearAllMocks()
})

async function fillForm({ username = 'alice', email = 'alice@x.com', password = 'password123', display = '' } = {}) {
  await fireEvent.input(screen.getByLabelText(/^Username/), { target: { value: username } })
  await fireEvent.input(screen.getByLabelText('Email'), { target: { value: email } })
  await fireEvent.input(screen.getByLabelText(/^Password/), { target: { value: password } })
  if (display) await fireEvent.input(screen.getByLabelText(/^Display name/), { target: { value: display } })
}

describe('Register', () => {
  it('registers, logs in, and navigates home on success', async () => {
    register.mockResolvedValue({ id: 'u1' })
    login.mockResolvedValue({ access_token: 'tok', user: { id: 'u1' } })
    render(Register)

    await fillForm()
    await fireEvent.click(screen.getByText('Create account →'))

    await waitFor(() => expect(register).toHaveBeenCalledWith({
      username: 'alice', email: 'alice@x.com', password: 'password123', display_name: undefined,
    }))
    await waitFor(() => expect(login).toHaveBeenCalledWith({ username: 'alice', password: 'password123' }))
    await waitFor(() => expect(push).toHaveBeenCalledWith('/'))
  })

  it('passes a display name through when provided', async () => {
    register.mockResolvedValue({ id: 'u1' })
    login.mockResolvedValue({ access_token: 'tok', user: {} })
    render(Register)

    await fillForm({ display: 'Alice A' })
    await fireEvent.click(screen.getByText('Create account →'))

    await waitFor(() => expect(register).toHaveBeenCalledWith(expect.objectContaining({ display_name: 'Alice A' })))
  })

  it('shows an error and does not call login when registration fails', async () => {
    register.mockRejectedValue(new Error('username taken'))
    render(Register)

    await fillForm()
    await fireEvent.click(screen.getByText('Create account →'))

    await waitFor(() => expect(screen.getByText('username taken')).toBeInTheDocument())
    expect(login).not.toHaveBeenCalled()
    expect(push).not.toHaveBeenCalled()
  })

  it('shows an error when the post-register login fails', async () => {
    register.mockResolvedValue({ id: 'u1' })
    login.mockRejectedValue(new Error('login failed after register'))
    render(Register)

    await fillForm()
    await fireEvent.click(screen.getByText('Create account →'))

    await waitFor(() => expect(screen.getByText('login failed after register')).toBeInTheDocument())
    expect(push).not.toHaveBeenCalled()
  })

  it('shows a loading state while submitting', async () => {
    let resolveRegister
    register.mockReturnValue(new Promise(r => { resolveRegister = r }))
    render(Register)

    await fillForm()
    await fireEvent.click(screen.getByText('Create account →'))

    expect(screen.getByText('Creating account…')).toBeInTheDocument()
    resolveRegister({ id: 'u1' })
    login.mockResolvedValue({ access_token: 'tok', user: {} })
    await waitFor(() => expect(push).toHaveBeenCalled())
  })

  it('links to the login page', () => {
    const { container } = render(Register)
    expect(container.querySelector('a[href="#/login"]')).not.toBeNull()
  })
})
