import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import Members from './Members.svelte'

vi.mock('../lib/api.js', () => ({
  listProjectMembers: vi.fn(),
  updateProjectMember: vi.fn(),
  removeProjectMember: vi.fn(),
  createProjectInvitation: vi.fn(),
  listProjectInvitations: vi.fn(),
  declineInvitation: vi.fn(),
}))

vi.mock('../lib/stores.js', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, notify: vi.fn() }
})

import {
  listProjectMembers, updateProjectMember, removeProjectMember,
  createProjectInvitation, listProjectInvitations, declineInvitation,
} from '../lib/api.js'
import { notify, currentProject, currentUser } from '../lib/stores.js'

const memberA = { user_id: 'u1', username: 'alice', display_name: 'Alice A', email: 'alice@x.com', role: 'editor' }
const memberOwner = { user_id: 'u2', username: 'bob', display_name: 'Bob B', email: 'bob@x.com', role: 'owner' }

beforeEach(() => {
  vi.clearAllMocks()
  currentProject.set(null)
  currentUser.set(null)
  listProjectMembers.mockResolvedValue([])
  listProjectInvitations.mockResolvedValue([])
})

describe('Members — no project / loading', () => {
  it('shows a message when no project is selected', () => {
    render(Members)
    expect(screen.getByText('No project selected.')).toBeInTheDocument()
  })

  it('loads members once a project is set', async () => {
    currentProject.set({ id: 'p1', name: 'Proj', member_role: 'viewer' })
    render(Members)
    await waitFor(() => expect(listProjectMembers).toHaveBeenCalledWith('p1'))
  })

  it('notifies on load failure', async () => {
    listProjectMembers.mockRejectedValue(new Error('db down'))
    currentProject.set({ id: 'p1', name: 'Proj', member_role: 'viewer' })
    render(Members)
    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('db down')))
  })
})

describe('Members — viewer (read-only)', () => {
  beforeEach(() => {
    currentProject.set({ id: 'p1', name: 'Proj', member_role: 'viewer' })
    currentUser.set({ id: 'me', is_admin: false })
    listProjectMembers.mockResolvedValue([memberA, memberOwner])
  })

  it('does not show the invite form', async () => {
    render(Members)
    await waitFor(() => expect(screen.getByText('Alice A')).toBeInTheDocument())
    expect(screen.queryByText('Invite member')).toBeNull()
  })

  it('does not fetch invitations for a non-manager', async () => {
    render(Members)
    await waitFor(() => expect(screen.getByText('Alice A')).toBeInTheDocument())
    expect(listProjectInvitations).not.toHaveBeenCalled()
  })

  it('shows roles as read-only chips, not selects', async () => {
    render(Members)
    await waitFor(() => expect(screen.getByText('Alice A')).toBeInTheDocument())
    expect(screen.getByText('editor')).toBeInTheDocument()
    expect(screen.getByText('owner')).toBeInTheDocument()
    expect(screen.queryByTitle('Remove member')).toBeNull()
  })
})

describe('Members — owner (management)', () => {
  beforeEach(() => {
    currentProject.set({ id: 'p1', name: 'Proj', member_role: 'owner' })
    currentUser.set({ id: 'owner-self', is_admin: false })
  })

  it('shows the invite form and sends an invitation', async () => {
    const created = { id: 'inv1', invited_email: 'new@x.com', role: 'viewer', status: 'pending', created_at: '2026-01-01T00:00:00.000Z' }
    createProjectInvitation.mockResolvedValue(created)
    render(Members)
    await waitFor(() => expect(screen.getByText('Invite member')).toBeInTheDocument())

    await fireEvent.input(screen.getByPlaceholderText('colleague@example.com'), { target: { value: 'new@x.com' } })
    await fireEvent.click(screen.getByText('Send invite'))

    await waitFor(() => expect(createProjectInvitation).toHaveBeenCalledWith('p1', { invited_email: 'new@x.com', role: 'viewer' }))
    await waitFor(() => expect(notify).toHaveBeenCalledWith('success', 'Invitation sent to new@x.com'))
    expect(screen.getByText('new@x.com')).toBeInTheDocument()
  })

  it('disables Send invite when the email is blank', async () => {
    render(Members)
    await waitFor(() => expect(screen.getByText('Send invite')).toBeInTheDocument())
    expect(screen.getByText('Send invite')).toBeDisabled()
  })

  it('notifies on invite failure', async () => {
    createProjectInvitation.mockRejectedValue(new Error('already invited'))
    render(Members)
    await waitFor(() => expect(screen.getByText('Invite member')).toBeInTheDocument())

    await fireEvent.input(screen.getByPlaceholderText('colleague@example.com'), { target: { value: 'dup@x.com' } })
    await fireEvent.click(screen.getByText('Send invite'))

    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('already invited')))
  })

  it('changes a non-owner member role via the select', async () => {
    listProjectMembers.mockResolvedValue([memberA])
    updateProjectMember.mockResolvedValue({ role: 'viewer' })
    render(Members)
    await waitFor(() => expect(screen.getByText('Alice A')).toBeInTheDocument())

    // getByDisplayValue on a <select> matches the selected option's visible
    // text ("Editor"), not its value attribute ("editor").
    const select = await waitFor(() => screen.getByDisplayValue('Editor'))
    await fireEvent.change(select, { target: { value: 'viewer' } })

    await waitFor(() => expect(updateProjectMember).toHaveBeenCalledWith('p1', 'u1', { role: 'viewer' }))
  })

  it('confirms before promoting a member to owner', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    listProjectMembers.mockResolvedValue([memberA])
    render(Members)
    await waitFor(() => expect(screen.getByText('Alice A')).toBeInTheDocument())

    const select = await waitFor(() => screen.getByDisplayValue('Editor'))
    await fireEvent.change(select, { target: { value: 'owner' } })

    expect(window.confirm).toHaveBeenCalled()
    expect(updateProjectMember).not.toHaveBeenCalled()
  })

  it('does not show a role select or remove button for the owner row', async () => {
    listProjectMembers.mockResolvedValue([memberOwner])
    render(Members)
    await waitFor(() => expect(screen.getByText('Bob B')).toBeInTheDocument())
    expect(screen.queryByDisplayValue('owner')).toBeNull()
    expect(screen.getByText('owner')).toBeInTheDocument()
  })

  it('removes a member after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    listProjectMembers.mockResolvedValue([memberA])
    removeProjectMember.mockResolvedValue(null)
    render(Members)
    await waitFor(() => expect(screen.getByText('Alice A')).toBeInTheDocument())

    await fireEvent.click(screen.getByTitle('Remove member'))

    await waitFor(() => expect(removeProjectMember).toHaveBeenCalledWith('p1', 'u1'))
    await waitFor(() => expect(notify).toHaveBeenCalledWith('success', 'Member removed.'))
    expect(screen.queryByText('Alice A')).toBeNull()
  })

  it('does not show a remove button for yourself', async () => {
    currentUser.set({ id: 'u1', is_admin: false })
    listProjectMembers.mockResolvedValue([memberA])
    render(Members)
    await waitFor(() => expect(screen.getByText(/Alice A/)).toBeInTheDocument())
    expect(screen.getByText('(you)')).toBeInTheDocument()
    expect(screen.queryByTitle('Remove member')).toBeNull()
  })

  it('lists pending invitations and revokes one', async () => {
    listProjectInvitations.mockResolvedValue([
      { id: 'inv1', invited_email: 'pending@x.com', role: 'viewer', status: 'pending', created_at: '2026-01-01T00:00:00.000Z' },
    ])
    declineInvitation.mockResolvedValue(null)
    render(Members)
    await waitFor(() => expect(screen.getByText('pending@x.com')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Revoke'))

    await waitFor(() => expect(declineInvitation).toHaveBeenCalledWith('inv1'))
    await waitFor(() => expect(notify).toHaveBeenCalledWith('success', 'Invitation revoked.'))
    expect(screen.queryByText('pending@x.com')).toBeNull()
  })

  it('filters out non-pending invitations', async () => {
    listProjectInvitations.mockResolvedValue([
      { id: 'inv1', invited_email: 'accepted@x.com', role: 'viewer', status: 'accepted', created_at: '2026-01-01T00:00:00.000Z' },
    ])
    render(Members)
    await waitFor(() => expect(screen.getByText('No pending invitations.')).toBeInTheDocument())
  })
})
