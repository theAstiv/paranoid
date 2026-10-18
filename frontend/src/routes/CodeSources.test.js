import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import { tick } from 'svelte'
import CodeSources from './CodeSources.svelte'

vi.mock('../lib/api.js', () => ({
  listCodeSources: vi.fn(),
  createCodeSource: vi.fn(),
  deleteCodeSource: vi.fn(),
  reindexSource: vi.fn(),
  subscribeToSourceEvents: vi.fn(() => vi.fn()),
}))

vi.mock('../lib/stores.js', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, notify: vi.fn() }
})

import {
  listCodeSources, createCodeSource, deleteCodeSource, reindexSource, subscribeToSourceEvents,
} from '../lib/api.js'
import { notify, currentProject, currentUser } from '../lib/stores.js'

const readySource = {
  id: 's1', name: 'backend', git_url: 'https://github.com/x/y.git', ref: null,
  last_index_status: 'ready', has_pat: false,
}

beforeEach(() => {
  vi.clearAllMocks()
  currentProject.set(null)
  currentUser.set({ id: 'u1' })
  subscribeToSourceEvents.mockReturnValue(vi.fn())
  listCodeSources.mockResolvedValue([])
})

describe('CodeSources — project scoping', () => {
  it('lists the current project’s sources', async () => {
    currentProject.set({ id: 'p1', name: 'Alpha' })
    render(CodeSources)
    await waitFor(() => expect(listCodeSources).toHaveBeenCalledWith({ project_id: 'p1' }))
  })

  it('reloads and stops the old progress streams when the project changes', async () => {
    const stop = vi.fn()
    subscribeToSourceEvents.mockReturnValue(stop)
    currentProject.set({ id: 'p1', name: 'Alpha' })
    listCodeSources.mockResolvedValueOnce([{ ...readySource, last_index_status: 'cloning' }])
    render(CodeSources)
    await waitFor(() => expect(subscribeToSourceEvents).toHaveBeenCalled())

    listCodeSources.mockResolvedValueOnce([{ ...readySource, id: 's9', name: 'other-repo' }])
    currentProject.set({ id: 'p2', name: 'Beta' })

    await waitFor(() => expect(listCodeSources).toHaveBeenLastCalledWith({ project_id: 'p2' }))
    await waitFor(() => expect(screen.getByText('other-repo')).toBeInTheDocument())
    expect(screen.queryByText('backend')).toBeNull()
    expect(stop).toHaveBeenCalled()
  })

  it('creates the source in the current project', async () => {
    currentProject.set({ id: 'p1', name: 'Alpha' })
    createCodeSource.mockResolvedValue({ ...readySource, id: 's-new' })
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('Add source')).toBeInTheDocument())
    await fireEvent.click(screen.getByText('Add source'))
    await fireEvent.input(screen.getByLabelText(/Git URL/), { target: { value: 'https://github.com/x/y.git' } })
    await fireEvent.input(screen.getByLabelText(/^Name/), { target: { value: 'backend' } })
    await fireEvent.click(screen.getByText('Add & clone'))

    await waitFor(() => expect(createCodeSource).toHaveBeenCalledWith({
      name: 'backend', git_url: 'https://github.com/x/y.git', ref: null, pat: null, project_id: 'p1',
    }))
  })

  it('blocks adding a source while a signed-in user has no project', async () => {
    currentUser.set({ id: 'u1', username: 'ann' })
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('Add source')).toBeInTheDocument())
    await fireEvent.click(screen.getByText('Add source'))
    await fireEvent.input(screen.getByLabelText(/Git URL/), { target: { value: 'https://github.com/x/y.git' } })
    await fireEvent.input(screen.getByLabelText(/^Name/), { target: { value: 'backend' } })
    expect(screen.getByText('Add & clone')).toBeDisabled()
  })
})

// BB-24: the server needs editor to add/re-index and owner to delete; the buttons
// follow it. A role that is not known yet keeps them (the server still enforces).
describe('CodeSources — role gating', () => {
  const ADD = 'Add source'
  const REINDEX = 'Re-clone and re-index'
  const DELETE = 'Delete source'

  async function renderAs(role, user = { id: 'u1', username: 'ann' }) {
    currentUser.set(user)
    currentProject.set({ id: 'p1', name: 'Alpha', member_role: role })
    listCodeSources.mockResolvedValue([readySource])
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('backend')).toBeInTheDocument())
  }

  it('shows a viewer the list but no Add, re-index or delete', async () => {
    await renderAs('viewer')
    expect(screen.queryByText(ADD)).toBeNull()
    expect(screen.queryByTitle(REINDEX)).toBeNull()
    expect(screen.queryByTitle(DELETE)).toBeNull()
  })

  it('tells a viewer to ask an editor when the project has no sources', async () => {
    currentUser.set({ id: 'u1', username: 'ann' })
    currentProject.set({ id: 'p1', name: 'Alpha', member_role: 'viewer' })
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('No code sources yet.')).toBeInTheDocument())
    expect(screen.getByText(/ask a project editor/i)).toBeInTheDocument()
    expect(screen.queryByText(/Add a Git repository/)).toBeNull()
  })

  it('lets an editor add and re-index but not delete', async () => {
    await renderAs('editor')
    expect(screen.getByText(ADD)).toBeInTheDocument()
    expect(screen.getByTitle(REINDEX)).toBeInTheDocument()
    expect(screen.queryByTitle(DELETE)).toBeNull()
  })

  it('lets an owner do everything', async () => {
    await renderAs('owner')
    expect(screen.getByText(ADD)).toBeInTheDocument()
    expect(screen.getByTitle(REINDEX)).toBeInTheDocument()
    expect(screen.getByTitle(DELETE)).toBeInTheDocument()
  })

  it('lets an instance admin do everything whatever their project role', async () => {
    await renderAs('viewer', { id: 'u2', username: 'root', is_admin: true })
    expect(screen.getByText(ADD)).toBeInTheDocument()
    expect(screen.getByTitle(REINDEX)).toBeInTheDocument()
    expect(screen.getByTitle(DELETE)).toBeInTheDocument()
  })

  it('keeps the buttons while the role is not known', async () => {
    currentProject.set({ id: 'p1', name: 'Alpha' })
    listCodeSources.mockResolvedValue([readySource])
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('backend')).toBeInTheDocument())
    expect(screen.getByText(ADD)).toBeInTheDocument()
    expect(screen.getByTitle(REINDEX)).toBeInTheDocument()
    expect(screen.getByTitle(DELETE)).toBeInTheDocument()
  })
})

describe('CodeSources — loading', () => {
  it('loads sources on mount', async () => {
    render(CodeSources)
    await waitFor(() => expect(listCodeSources).toHaveBeenCalled())
  })

  it('notifies on load failure', async () => {
    listCodeSources.mockRejectedValue(new Error('boom'))
    render(CodeSources)
    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('boom')))
  })

  it('shows an empty state when there are no sources', async () => {
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('No code sources yet.')).toBeInTheDocument())
  })

  it('attaches SSE for any source not in a terminal state', async () => {
    listCodeSources.mockResolvedValue([{ ...readySource, id: 's2', last_index_status: 'cloning' }])
    render(CodeSources)
    await waitFor(() => expect(subscribeToSourceEvents).toHaveBeenCalledWith(
      's2', expect.any(Function), expect.any(Function), expect.any(Function),
    ))
  })

  it('does not attach SSE for a terminal (ready) source', async () => {
    listCodeSources.mockResolvedValue([readySource])
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('backend')).toBeInTheDocument())
    expect(subscribeToSourceEvents).not.toHaveBeenCalled()
  })
})

// BB-41: signing out nulls the user and project; the page's reload used to call the API
// without a token and toast "Session expired", which the next login still showed.
describe('CodeSources — signed out', () => {
  it('does not load sources, or toast, while nobody is signed in', async () => {
    currentUser.set(null)
    listCodeSources.mockRejectedValue(new Error('Session expired'))
    render(CodeSources)
    await tick()
    expect(listCodeSources).not.toHaveBeenCalled()
    expect(notify).not.toHaveBeenCalled()
  })

  it('loads once a user signs in', async () => {
    currentUser.set(null)
    render(CodeSources)
    await tick()
    currentUser.set({ id: 'u1' })
    await waitFor(() => expect(listCodeSources).toHaveBeenCalledTimes(1))
  })
})

describe('CodeSources — rendering', () => {
  it('renders the source name, status chip, and git URL', async () => {
    listCodeSources.mockResolvedValue([readySource])
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('backend')).toBeInTheDocument())
    expect(screen.getByText('ready')).toBeInTheDocument()
    expect(screen.getByText('https://github.com/x/y.git')).toBeInTheDocument()
  })

  it('shows a PAT badge when has_pat is true', async () => {
    listCodeSources.mockResolvedValue([{ ...readySource, has_pat: true }])
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('PAT')).toBeInTheDocument())
  })

  it('shows the last_index_error for a failed source', async () => {
    listCodeSources.mockResolvedValue([{ ...readySource, last_index_status: 'failed', last_index_error: 'clone timed out' }])
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('clone timed out')).toBeInTheDocument())
  })

  it('shows a re-index button only for terminal-state sources', async () => {
    listCodeSources.mockResolvedValue([readySource])
    render(CodeSources)
    await waitFor(() => expect(screen.getByTitle('Re-clone and re-index')).toBeInTheDocument())
  })

  it('hides the re-index button for an active (non-terminal) source', async () => {
    listCodeSources.mockResolvedValue([{ ...readySource, last_index_status: 'cloning' }])
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('backend')).toBeInTheDocument())
    expect(screen.queryByTitle('Re-clone and re-index')).toBeNull()
  })

  it('updates status live via SSE events', async () => {
    let onEvent
    subscribeToSourceEvents.mockImplementation((id, cb) => { onEvent = cb; return vi.fn() })
    listCodeSources.mockResolvedValue([{ ...readySource, last_index_status: 'cloning' }])
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('cloning')).toBeInTheDocument())

    onEvent({ status: 'indexing', message: 'Parsing files…' })
    await waitFor(() => expect(screen.getByText('indexing')).toBeInTheDocument())
    expect(screen.getByText('Parsing files…')).toBeInTheDocument()
  })
})

describe('CodeSources — add form', () => {
  it('toggles the add form', async () => {
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('Add source')).toBeInTheDocument())
    await fireEvent.click(screen.getByText('Add source'))
    expect(screen.getByText('Add repository')).toBeInTheDocument()

    // Both the header toggle and the form's own Cancel button read "Cancel"
    // while the form is open — target the form's ghost-styled one specifically.
    const formCancel = screen.getAllByText('Cancel').find(el => el.className.includes('btn-ghost'))
    await fireEvent.click(formCancel)
    expect(screen.queryByText('Add repository')).toBeNull()
  })

  it('disables Add & clone until name and URL are filled', async () => {
    currentProject.set({ id: 'p1', name: 'Alpha' })
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('Add source')).toBeInTheDocument())
    await fireEvent.click(screen.getByText('Add source'))

    expect(screen.getByText('Add & clone')).toBeDisabled()
    await fireEvent.input(screen.getByLabelText(/Git URL/), { target: { value: 'https://github.com/x/y.git' } })
    expect(screen.getByText('Add & clone')).toBeDisabled()
    await fireEvent.input(screen.getByLabelText(/^Name/), { target: { value: 'backend' } })
    expect(screen.getByText('Add & clone')).not.toBeDisabled()
  })

  it('adds a source and closes the form', async () => {
    const created = { ...readySource, id: 's-new', name: 'backend' }
    createCodeSource.mockResolvedValue(created)
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('Add source')).toBeInTheDocument())
    await fireEvent.click(screen.getByText('Add source'))

    await fireEvent.input(screen.getByLabelText(/Git URL/), { target: { value: 'https://github.com/x/y.git' } })
    await fireEvent.input(screen.getByLabelText(/^Name/), { target: { value: 'backend' } })
    await fireEvent.click(screen.getByText('Add & clone'))

    await waitFor(() => expect(createCodeSource).toHaveBeenCalledWith({
      name: 'backend', git_url: 'https://github.com/x/y.git', ref: null, pat: null,
    }))
    await waitFor(() => expect(screen.queryByText('Add repository')).toBeNull())
    expect(screen.getByText('backend')).toBeInTheDocument()
  })

  it('attaches SSE for a newly added non-terminal source', async () => {
    createCodeSource.mockResolvedValue({ ...readySource, id: 's-new', last_index_status: 'cloning' })
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('Add source')).toBeInTheDocument())
    await fireEvent.click(screen.getByText('Add source'))
    await fireEvent.input(screen.getByLabelText(/Git URL/), { target: { value: 'https://github.com/x/y.git' } })
    await fireEvent.input(screen.getByLabelText(/^Name/), { target: { value: 'backend' } })

    await fireEvent.click(screen.getByText('Add & clone'))

    await waitFor(() => expect(subscribeToSourceEvents).toHaveBeenCalledWith(
      's-new', expect.any(Function), expect.any(Function), expect.any(Function),
    ))
  })

  it('notifies on add failure', async () => {
    createCodeSource.mockRejectedValue(new Error('invalid host'))
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('Add source')).toBeInTheDocument())
    await fireEvent.click(screen.getByText('Add source'))
    await fireEvent.input(screen.getByLabelText(/Git URL/), { target: { value: 'https://evil.com/x/y.git' } })
    await fireEvent.input(screen.getByLabelText(/^Name/), { target: { value: 'backend' } })

    await fireEvent.click(screen.getByText('Add & clone'))

    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('invalid host')))
  })
})

describe('CodeSources — delete and reindex', () => {
  beforeEach(() => {
    listCodeSources.mockResolvedValue([readySource])
  })

  it('deletes a source after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    deleteCodeSource.mockResolvedValue(null)
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('backend')).toBeInTheDocument())

    await fireEvent.click(screen.getByTitle('Delete source'))

    await waitFor(() => expect(deleteCodeSource).toHaveBeenCalledWith('s1'))
    await waitFor(() => expect(notify).toHaveBeenCalledWith('success', 'Source deleted.'))
    expect(screen.queryByText('backend')).toBeNull()
  })

  it('does not delete when confirmation is dismissed', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('backend')).toBeInTheDocument())

    await fireEvent.click(screen.getByTitle('Delete source'))

    expect(deleteCodeSource).not.toHaveBeenCalled()
  })

  it('notifies on delete failure', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    deleteCodeSource.mockRejectedValue(new Error('locked'))
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('backend')).toBeInTheDocument())

    await fireEvent.click(screen.getByTitle('Delete source'))

    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('locked')))
  })

  it('reindexes a source, optimistically marking it queued', async () => {
    reindexSource.mockResolvedValue({ ...readySource, last_index_status: 'cloning' })
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('backend')).toBeInTheDocument())

    await fireEvent.click(screen.getByTitle('Re-clone and re-index'))

    await waitFor(() => expect(reindexSource).toHaveBeenCalledWith('s1'))
    await waitFor(() => expect(screen.getByText('cloning')).toBeInTheDocument())
  })

  it('notifies and reloads on reindex failure', async () => {
    reindexSource.mockRejectedValue(new Error('busy'))
    listCodeSources.mockResolvedValueOnce([readySource]).mockResolvedValueOnce([readySource])
    render(CodeSources)
    await waitFor(() => expect(screen.getByText('backend')).toBeInTheDocument())

    await fireEvent.click(screen.getByTitle('Re-clone and re-index'))

    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('busy')))
  })
})
