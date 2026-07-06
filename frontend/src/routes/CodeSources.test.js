import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
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
import { notify } from '../lib/stores.js'

const readySource = {
  id: 's1', name: 'backend', git_url: 'https://github.com/x/y.git', ref: null,
  last_index_status: 'ready', has_pat: false,
}

beforeEach(() => {
  vi.clearAllMocks()
  subscribeToSourceEvents.mockReturnValue(vi.fn())
  listCodeSources.mockResolvedValue([])
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
