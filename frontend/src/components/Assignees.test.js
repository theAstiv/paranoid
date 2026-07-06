import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import Assignees from './Assignees.svelte'

vi.mock('../lib/api.js', () => ({
  listAssignees: vi.fn(),
  addAssignee: vi.fn(),
  removeAssignee: vi.fn(),
  listProjectMembers: vi.fn(),
}))

vi.mock('../lib/stores.js', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, notify: vi.fn() }
})

import { listAssignees, addAssignee, removeAssignee, listProjectMembers } from '../lib/api.js'
import { currentUser, currentProject, notify } from '../lib/stores.js'

const member = { user_id: 'u1', username: 'alice', display_name: 'Alice A' }
const member2 = { user_id: 'u2', username: 'bob', display_name: 'Bob B' }

beforeEach(() => {
  vi.clearAllMocks()
  currentUser.set(null)
  currentProject.set(null)
  listAssignees.mockResolvedValue([])
  listProjectMembers.mockResolvedValue([])
})

describe('Assignees — read-only rendering', () => {
  it('renders an avatar with initials for each assignee', async () => {
    listAssignees.mockResolvedValue([{ user_id: 'u1', username: 'alice', display_name: 'Alice A' }])
    render(Assignees, { props: { modelId: 'm1', projectId: 'p1' } })
    await waitFor(() => expect(screen.getByText('AA')).toBeInTheDocument())
  })

  it('notifies on failure to load assignees', async () => {
    listAssignees.mockRejectedValue(new Error('boom'))
    render(Assignees, { props: { modelId: 'm1', projectId: 'p1' } })
    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('boom')))
  })

  it('hides the assign button when the user cannot assign', async () => {
    currentUser.set({ is_admin: false })
    currentProject.set({ id: 'p1', member_role: 'viewer' })
    render(Assignees, { props: { modelId: 'm1', projectId: 'p1' } })
    await waitFor(() => expect(listAssignees).toHaveBeenCalled())
    expect(screen.queryByTitle('Assign a user')).toBeNull()
  })

  it('shows the assign button for an instance admin regardless of project role', async () => {
    currentUser.set({ is_admin: true })
    currentProject.set({ id: 'p1', member_role: 'viewer' })
    render(Assignees, { props: { modelId: 'm1', projectId: 'p1' } })
    await waitFor(() => expect(listAssignees).toHaveBeenCalled())
    expect(screen.getByTitle('Assign a user')).toBeInTheDocument()
  })

  it('shows the assign button for an editor/owner in the same project', async () => {
    currentUser.set({ is_admin: false })
    currentProject.set({ id: 'p1', member_role: 'editor' })
    render(Assignees, { props: { modelId: 'm1', projectId: 'p1' } })
    await waitFor(() => expect(listAssignees).toHaveBeenCalled())
    expect(screen.getByTitle('Assign a user')).toBeInTheDocument()
  })
})

describe('Assignees — picker', () => {
  beforeEach(() => {
    currentUser.set({ is_admin: true })
    currentProject.set({ id: 'p1', member_role: 'owner' })
  })

  it('loads project members and lists candidates when opened', async () => {
    listProjectMembers.mockResolvedValue([member, member2])
    render(Assignees, { props: { modelId: 'm1', projectId: 'p1' } })
    await waitFor(() => expect(listAssignees).toHaveBeenCalled())

    await fireEvent.click(screen.getByTitle('Assign a user'))

    await waitFor(() => expect(listProjectMembers).toHaveBeenCalledWith('p1'))
    expect(screen.getByText('Alice A')).toBeInTheDocument()
    expect(screen.getByText('Bob B')).toBeInTheDocument()
  })

  it('excludes already-assigned members from the candidate list', async () => {
    listAssignees.mockResolvedValue([{ user_id: 'u1', username: 'alice', display_name: 'Alice A' }])
    listProjectMembers.mockResolvedValue([member, member2])
    render(Assignees, { props: { modelId: 'm1', projectId: 'p1' } })
    await waitFor(() => expect(listAssignees).toHaveBeenCalled())

    await fireEvent.click(screen.getByTitle('Assign a user'))
    await waitFor(() => expect(listProjectMembers).toHaveBeenCalled())

    expect(screen.queryByText('Alice A')).toBeNull()
    expect(screen.getByText('Bob B')).toBeInTheDocument()
  })

  it('shows an empty-state message when there are no unassigned members', async () => {
    listProjectMembers.mockResolvedValue([])
    render(Assignees, { props: { modelId: 'm1', projectId: 'p1' } })
    await waitFor(() => expect(listAssignees).toHaveBeenCalled())

    await fireEvent.click(screen.getByTitle('Assign a user'))
    await waitFor(() => expect(listProjectMembers).toHaveBeenCalled())

    expect(screen.getByText('No unassigned members.')).toBeInTheDocument()
  })

  it('assigns a candidate and closes the picker', async () => {
    listProjectMembers.mockResolvedValue([member])
    addAssignee.mockResolvedValue({ user_id: 'u1' })
    render(Assignees, { props: { modelId: 'm1', projectId: 'p1' } })
    await waitFor(() => expect(listAssignees).toHaveBeenCalled())

    await fireEvent.click(screen.getByTitle('Assign a user'))
    await waitFor(() => expect(listProjectMembers).toHaveBeenCalled())
    await fireEvent.click(screen.getByText('Alice A'))

    await waitFor(() => expect(addAssignee).toHaveBeenCalledWith('m1', { user_id: 'u1' }))
    // Picker closes after assignment
    expect(screen.queryByText('No unassigned members.')).toBeNull()
  })

  it('notifies on assign failure', async () => {
    listProjectMembers.mockResolvedValue([member])
    addAssignee.mockRejectedValue(new Error('no perms'))
    render(Assignees, { props: { modelId: 'm1', projectId: 'p1' } })
    await waitFor(() => expect(listAssignees).toHaveBeenCalled())

    await fireEvent.click(screen.getByTitle('Assign a user'))
    await waitFor(() => expect(listProjectMembers).toHaveBeenCalled())
    await fireEvent.click(screen.getByText('Alice A'))

    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('no perms')))
  })

  it('unassigns a user via the hover remove button', async () => {
    listAssignees.mockResolvedValue([{ user_id: 'u1', username: 'alice', display_name: 'Alice A' }])
    removeAssignee.mockResolvedValue(null)
    render(Assignees, { props: { modelId: 'm1', projectId: 'p1' } })
    await waitFor(() => expect(screen.getByTitle('Alice A')).toBeInTheDocument())

    await fireEvent.click(screen.getByTitle('Remove assignee'))

    await waitFor(() => expect(removeAssignee).toHaveBeenCalledWith('m1', 'u1'))
    await waitFor(() => expect(screen.queryByTitle('Alice A')).toBeNull())
  })

  it('notifies on unassign failure', async () => {
    listAssignees.mockResolvedValue([{ user_id: 'u1', username: 'alice', display_name: 'Alice A' }])
    removeAssignee.mockRejectedValue(new Error('nope'))
    render(Assignees, { props: { modelId: 'm1', projectId: 'p1' } })
    await waitFor(() => expect(screen.getByTitle('Alice A')).toBeInTheDocument())

    await fireEvent.click(screen.getByTitle('Remove assignee'))

    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('nope')))
  })
})
