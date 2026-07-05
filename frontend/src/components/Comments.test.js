import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import Comments from './Comments.svelte'

vi.mock('../lib/api.js', () => ({
  listComments: vi.fn(),
  createComment: vi.fn(),
  updateComment: vi.fn(),
  deleteComment: vi.fn(),
}))

vi.mock('../lib/stores.js', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, notify: vi.fn() }
})

import { listComments, createComment, updateComment, deleteComment } from '../lib/api.js'
import { currentUser, notify } from '../lib/stores.js'

const rootComment = {
  id: 'c1',
  parent_id: null,
  body: 'First comment',
  user_id: 'u1',
  username: 'alice',
  display_name: 'Alice A',
  created_at: '2026-01-01T00:00:00.000Z',
}
const replyComment = {
  id: 'c2',
  parent_id: 'c1',
  body: 'A reply',
  user_id: 'u2',
  username: 'bob',
  display_name: 'Bob B',
  created_at: '2026-01-01T01:00:00.000Z',
}

beforeEach(() => {
  vi.clearAllMocks()
  currentUser.set(null)
  listComments.mockResolvedValue([])
})

describe('Comments — loading and empty states', () => {
  it('shows an empty state when there are no comments', async () => {
    render(Comments, { props: { modelId: 'm1' } })
    await waitFor(() => expect(screen.getByText('No comments yet.')).toBeInTheDocument())
  })

  it('notifies on failure to load comments', async () => {
    listComments.mockRejectedValue(new Error('db down'))
    render(Comments, { props: { modelId: 'm1' } })
    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('db down')))
  })
})

describe('Comments — rendering + threading', () => {
  it('renders a root comment with author and body', async () => {
    listComments.mockResolvedValue([rootComment])
    render(Comments, { props: { modelId: 'm1' } })
    await waitFor(() => expect(screen.getByText('First comment')).toBeInTheDocument())
    expect(screen.getByText('Alice A')).toBeInTheDocument()
  })

  it('nests replies under their parent comment', async () => {
    listComments.mockResolvedValue([rootComment, replyComment])
    render(Comments, { props: { modelId: 'm1' } })
    await waitFor(() => expect(screen.getByText('First comment')).toBeInTheDocument())
    expect(screen.getByText('A reply')).toBeInTheDocument()
    expect(screen.getByText('Bob B')).toBeInTheDocument()
  })

  it('shows the comment count in the header', async () => {
    listComments.mockResolvedValue([rootComment, replyComment])
    render(Comments, { props: { modelId: 'm1' } })
    await waitFor(() => expect(screen.getByText('(2)')).toBeInTheDocument())
  })

  it('hides Edit/Delete for a comment authored by someone else', async () => {
    currentUser.set({ id: 'someone-else', is_admin: false })
    listComments.mockResolvedValue([rootComment])
    render(Comments, { props: { modelId: 'm1' } })
    await waitFor(() => expect(screen.getByText('First comment')).toBeInTheDocument())
    expect(screen.queryByText('Edit')).toBeNull()
    expect(screen.queryByText('Delete')).toBeNull()
  })

  it('shows Edit/Delete for the comment author', async () => {
    currentUser.set({ id: 'u1', is_admin: false })
    listComments.mockResolvedValue([rootComment])
    render(Comments, { props: { modelId: 'm1' } })
    await waitFor(() => expect(screen.getByText('Edit')).toBeInTheDocument())
    expect(screen.getByText('Delete')).toBeInTheDocument()
  })

  it('shows Edit/Delete on any comment for an instance admin', async () => {
    currentUser.set({ id: 'admin-1', is_admin: true })
    listComments.mockResolvedValue([rootComment])
    render(Comments, { props: { modelId: 'm1' } })
    await waitFor(() => expect(screen.getByText('Edit')).toBeInTheDocument())
  })
})

describe('Comments — posting', () => {
  it('disables Post when the draft is empty', async () => {
    render(Comments, { props: { modelId: 'm1' } })
    await waitFor(() => expect(screen.getByText('No comments yet.')).toBeInTheDocument())
    expect(screen.getByText('Post')).toBeDisabled()
  })

  it('posts a new root comment and appends it to the list', async () => {
    const created = { ...rootComment, id: 'new-1', body: 'Hello world' }
    createComment.mockResolvedValue(created)
    render(Comments, { props: { modelId: 'm1' } })
    await waitFor(() => expect(screen.getByText('No comments yet.')).toBeInTheDocument())

    const textarea = screen.getByPlaceholderText('Add a comment…')
    await fireEvent.input(textarea, { target: { value: 'Hello world' } })
    await fireEvent.click(screen.getByText('Post'))

    await waitFor(() => expect(createComment).toHaveBeenCalledWith('m1', { body: 'Hello world' }))
    await waitFor(() => expect(screen.getByText('Hello world')).toBeInTheDocument())
    expect(textarea.value).toBe('')
  })

  it('notifies on post failure', async () => {
    createComment.mockRejectedValue(new Error('rate limited'))
    render(Comments, { props: { modelId: 'm1' } })
    await waitFor(() => expect(screen.getByText('No comments yet.')).toBeInTheDocument())

    await fireEvent.input(screen.getByPlaceholderText('Add a comment…'), { target: { value: 'x' } })
    await fireEvent.click(screen.getByText('Post'))

    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('rate limited')))
  })
})

describe('Comments — replying', () => {
  it('opens a reply box and posts a reply with the parent_id', async () => {
    listComments.mockResolvedValue([rootComment])
    const createdReply = { ...replyComment, id: 'c3' }
    createComment.mockResolvedValue(createdReply)
    render(Comments, { props: { modelId: 'm1' } })
    await waitFor(() => expect(screen.getByText('First comment')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Reply'))
    const replyBox = screen.getByPlaceholderText('Write a reply…')
    await fireEvent.input(replyBox, { target: { value: 'Thanks!' } })
    await fireEvent.click(screen.getByText('Reply', { selector: 'button.btn-primary' }))

    await waitFor(() => expect(createComment).toHaveBeenCalledWith('m1', { body: 'Thanks!', parent_id: 'c1' }))
  })
})

describe('Comments — editing', () => {
  it('edits a comment and replaces it with the server response', async () => {
    currentUser.set({ id: 'u1', is_admin: false })
    listComments.mockResolvedValue([rootComment])
    const updated = { ...rootComment, body: 'Edited body' }
    updateComment.mockResolvedValue(updated)
    render(Comments, { props: { modelId: 'm1' } })
    await waitFor(() => expect(screen.getByText('Edit')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Edit'))
    const textarea = screen.getByDisplayValue('First comment')
    await fireEvent.input(textarea, { target: { value: 'Edited body' } })
    await fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(updateComment).toHaveBeenCalledWith('c1', { body: 'Edited body' }))
    await waitFor(() => expect(screen.getByText('Edited body')).toBeInTheDocument())
  })

  it('cancels an edit without calling the API', async () => {
    currentUser.set({ id: 'u1', is_admin: false })
    listComments.mockResolvedValue([rootComment])
    render(Comments, { props: { modelId: 'm1' } })
    await waitFor(() => expect(screen.getByText('Edit')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Edit'))
    await fireEvent.click(screen.getByText('Cancel'))

    expect(updateComment).not.toHaveBeenCalled()
    expect(screen.getByText('First comment')).toBeInTheDocument()
  })
})

describe('Comments — deleting', () => {
  it('deletes a comment and its replies after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    currentUser.set({ id: 'u1', is_admin: false })
    listComments.mockResolvedValue([rootComment, replyComment])
    deleteComment.mockResolvedValue(null)
    render(Comments, { props: { modelId: 'm1' } })
    await waitFor(() => expect(screen.getByText('Delete')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Delete'))

    await waitFor(() => expect(deleteComment).toHaveBeenCalledWith('c1'))
    await waitFor(() => expect(screen.queryByText('First comment')).toBeNull())
    // The reply (whose parent_id === c1) is also removed client-side
    expect(screen.queryByText('A reply')).toBeNull()
  })

  it('does not delete when the confirmation is dismissed', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    currentUser.set({ id: 'u1', is_admin: false })
    listComments.mockResolvedValue([rootComment])
    render(Comments, { props: { modelId: 'm1' } })
    await waitFor(() => expect(screen.getByText('Delete')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Delete'))

    expect(deleteComment).not.toHaveBeenCalled()
    expect(screen.getByText('First comment')).toBeInTheDocument()
  })
})
