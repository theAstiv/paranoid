import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import { get } from 'svelte/store'
import ProjectSettings from './ProjectSettings.svelte'

vi.mock('../lib/api.js', () => ({
  getProject: vi.fn(),
  updateProject: vi.fn(),
}))

vi.mock('../lib/stores.js', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, notify: vi.fn() }
})

import { getProject, updateProject } from '../lib/api.js'
import { notify, currentProject, currentUser } from '../lib/stores.js'

const projectDefaults = {
  default_provider: 'anthropic',
  default_model: 'claude-sonnet-4-20250514',
  default_iterations: 5,
  default_temperature: 0.3,
}

beforeEach(() => {
  vi.clearAllMocks()
  currentProject.set(null)
  currentUser.set(null)
  getProject.mockResolvedValue({ ...projectDefaults })
})

describe('ProjectSettings — gating', () => {
  it('shows a message when no project is selected', () => {
    render(ProjectSettings)
    expect(screen.getByText('No project selected.')).toBeInTheDocument()
  })

  it('loads project settings once a project is set', async () => {
    currentProject.set({ id: 'p1', name: 'Proj', member_role: 'owner' })
    render(ProjectSettings)
    await waitFor(() => expect(getProject).toHaveBeenCalledWith('p1'))
  })

  it('notifies on load failure', async () => {
    getProject.mockRejectedValue(new Error('boom'))
    currentProject.set({ id: 'p1', name: 'Proj', member_role: 'owner' })
    render(ProjectSettings)
    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('boom')))
  })

  it('shows an owner-only message for a non-owner, non-admin viewer', async () => {
    currentProject.set({ id: 'p1', name: 'Proj', member_role: 'viewer' })
    currentUser.set({ is_admin: false })
    render(ProjectSettings)
    await waitFor(() =>
      expect(screen.getByText('Only project owners can view or change project defaults.')).toBeInTheDocument()
    )
  })

  it('allows an instance admin to view settings even without an owner role', async () => {
    currentProject.set({ id: 'p1', name: 'Proj', member_role: 'viewer' })
    currentUser.set({ is_admin: true })
    render(ProjectSettings)
    await waitFor(() => expect(screen.getByText('Pipeline defaults')).toBeInTheDocument())
  })
})

describe('ProjectSettings — form', () => {
  beforeEach(() => {
    currentProject.set({ id: 'p1', name: 'Proj', member_role: 'owner' })
    currentUser.set({ is_admin: false })
  })

  it('populates the draft from the loaded project', async () => {
    render(ProjectSettings)
    await waitFor(() => expect(screen.getByDisplayValue('claude-sonnet-4-20250514')).toBeInTheDocument())
    expect(screen.getByDisplayValue('5')).toBeInTheDocument()
    expect(screen.getByDisplayValue('0.3')).toBeInTheDocument()
  })

  it('saves the draft, converting blanks to null and strings to numbers', async () => {
    const updated = { ...projectDefaults, default_iterations: 7 }
    updateProject.mockResolvedValue(updated)
    render(ProjectSettings)
    await waitFor(() => expect(screen.getByDisplayValue('5')).toBeInTheDocument())

    await fireEvent.input(screen.getByLabelText('Default iterations'), { target: { value: '7' } })
    await fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(updateProject).toHaveBeenCalledWith('p1', {
      default_provider: 'anthropic',
      default_model: 'claude-sonnet-4-20250514',
      default_iterations: 7,
      default_temperature: 0.3,
    }))
    await waitFor(() => expect(notify).toHaveBeenCalledWith('success', 'Project defaults saved.'))
    expect(get(currentProject)).toMatchObject(updated)
  })

  it('sends null for blank fields instead of empty strings', async () => {
    getProject.mockResolvedValue({ default_provider: '', default_model: '', default_iterations: '', default_temperature: '' })
    updateProject.mockResolvedValue({})
    render(ProjectSettings)
    await waitFor(() => expect(screen.getByText('Pipeline defaults')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(updateProject).toHaveBeenCalledWith('p1', {
      default_provider: null,
      default_model: null,
      default_iterations: null,
      default_temperature: null,
    }))
  })

  it('notifies on save failure', async () => {
    updateProject.mockRejectedValue(new Error('forbidden'))
    render(ProjectSettings)
    await waitFor(() => expect(screen.getByText('Pipeline defaults')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('forbidden')))
  })
})
