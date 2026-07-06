import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import ReviewContext from './ReviewContext.svelte'

vi.mock('svelte-spa-router', () => ({
  link: () => ({ destroy: () => {} }),
}))

vi.mock('../lib/api.js', () => ({
  getModel: vi.fn(),
  getModelAssets: vi.fn(),
  getModelFlows: vi.fn(),
  getModelTrustBoundaries: vi.fn(),
  createAsset: vi.fn(),
  updateAsset: vi.fn(),
  deleteAsset: vi.fn(),
  createFlow: vi.fn(),
  updateFlow: vi.fn(),
  deleteFlow: vi.fn(),
  createTrustBoundary: vi.fn(),
  updateTrustBoundary: vi.fn(),
  deleteTrustBoundary: vi.fn(),
  subscribeToExtract: vi.fn(() => vi.fn()),
}))

vi.mock('../lib/stores.js', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, notify: vi.fn() }
})

import {
  getModel, getModelAssets, getModelFlows, getModelTrustBoundaries,
  createAsset, updateAsset, deleteAsset,
  createFlow, deleteFlow,
  createTrustBoundary, deleteTrustBoundary,
  subscribeToExtract,
} from '../lib/api.js'
import { notify } from '../lib/stores.js'

const baseModel = { id: 'm1', title: 'Payments Service' }
const assetA = { id: 'a1', name: 'User DB', description: 'Stores user records', type: 'Asset' }
const flowA = { id: 'f1', source_entity: 'Client', target_entity: 'API', flow_description: 'HTTPS request' }
const boundaryA = { id: 'b1', source_entity: 'Internet', target_entity: 'VPC', purpose: 'Perimeter' }

beforeEach(() => {
  vi.clearAllMocks()
  getModel.mockResolvedValue(baseModel)
  getModelAssets.mockResolvedValue([])
  getModelFlows.mockResolvedValue([])
  getModelTrustBoundaries.mockResolvedValue([])
  subscribeToExtract.mockReturnValue(vi.fn())
})

describe('ReviewContext — loading', () => {
  it('loads model and context data on mount', async () => {
    render(ReviewContext, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Payments Service')).toBeInTheDocument())
    expect(getModelAssets).toHaveBeenCalledWith('m1')
    expect(getModelFlows).toHaveBeenCalledWith('m1')
    expect(getModelTrustBoundaries).toHaveBeenCalledWith('m1')
  })

  it('notifies on load failure', async () => {
    getModel.mockRejectedValue(new Error('not found'))
    render(ReviewContext, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('not found')))
  })

  it('shows section counts', async () => {
    getModelAssets.mockResolvedValue([assetA])
    getModelFlows.mockResolvedValue([flowA])
    getModelTrustBoundaries.mockResolvedValue([boundaryA])
    render(ReviewContext, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getAllByText('(1)')).toHaveLength(3))
  })
})

describe('ReviewContext — re-extract', () => {
  it('streams extraction events into the log and reloads on completion', async () => {
    let onEvent, onDone
    subscribeToExtract.mockImplementation((id, evtCb, errCb, doneCb) => {
      onEvent = evtCb; onDone = doneCb
      return vi.fn()
    })
    render(ReviewContext, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Payments Service')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Re-extract from description'))
    expect(screen.getByText('Extracting…')).toBeInTheDocument()

    onEvent({ step: 'summarize', message: 'Summarizing…' })
    await waitFor(() => expect(screen.getByText('[summarize] Summarizing…')).toBeInTheDocument())

    getModelAssets.mockResolvedValue([assetA])
    await onDone()
    await waitFor(() => expect(notify).toHaveBeenCalledWith('success', 'Context extracted successfully'))
    expect(screen.getByText('User DB')).toBeInTheDocument()
  })

  it('notifies and stops on extraction error', async () => {
    let onErr
    subscribeToExtract.mockImplementation((id, evtCb, errCb) => { onErr = errCb; return vi.fn() })
    render(ReviewContext, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Payments Service')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Re-extract from description'))
    onErr(new Error('LLM down'))

    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('LLM down')))
    expect(screen.getByText('Re-extract from description')).toBeInTheDocument()
  })
})

describe('ReviewContext — assets CRUD', () => {
  it('adds a new asset', async () => {
    createAsset.mockResolvedValue({ id: 'a2', name: 'New Asset', description: '', type: 'Asset' })
    render(ReviewContext, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Payments Service')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('+ Add asset'))
    await fireEvent.input(screen.getByLabelText('New asset name'), { target: { value: 'New Asset' } })
    await fireEvent.click(screen.getByText('Add'))

    await waitFor(() => expect(createAsset).toHaveBeenCalledWith('m1', expect.objectContaining({ name: 'New Asset' })))
    await waitFor(() => expect(screen.getByText('New Asset')).toBeInTheDocument())
  })

  it('does not submit a new asset with a blank name', async () => {
    render(ReviewContext, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Payments Service')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('+ Add asset'))
    await fireEvent.click(screen.getByText('Add'))

    expect(createAsset).not.toHaveBeenCalled()
  })

  it('edits an existing asset', async () => {
    getModelAssets.mockResolvedValue([assetA])
    updateAsset.mockResolvedValue({})
    render(ReviewContext, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('User DB')).toBeInTheDocument())

    const [editBtn] = screen.getAllByRole('button').filter(b => b.querySelector('path[d^="M13.586"]'))
    await fireEvent.click(editBtn)
    await fireEvent.input(screen.getByLabelText('Asset name'), { target: { value: 'Renamed DB' } })
    await fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(updateAsset).toHaveBeenCalledWith('m1', 'a1', expect.objectContaining({ name: 'Renamed DB' })))
    await waitFor(() => expect(screen.getByText('Renamed DB')).toBeInTheDocument())
  })

  it('deletes an asset', async () => {
    getModelAssets.mockResolvedValue([assetA])
    deleteAsset.mockResolvedValue(null)
    render(ReviewContext, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('User DB')).toBeInTheDocument())

    const [, deleteBtn] = screen.getAllByRole('button').filter(b => b.querySelector('path[fill-rule="evenodd"]'))
    await fireEvent.click(deleteBtn)

    await waitFor(() => expect(deleteAsset).toHaveBeenCalledWith('m1', 'a1'))
    await waitFor(() => expect(screen.queryByText('User DB')).toBeNull())
  })

  it('notifies on asset create failure', async () => {
    createAsset.mockRejectedValue(new Error('duplicate'))
    render(ReviewContext, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Payments Service')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('+ Add asset'))
    await fireEvent.input(screen.getByLabelText('New asset name'), { target: { value: 'Dup' } })
    await fireEvent.click(screen.getByText('Add'))

    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('duplicate')))
  })
})

describe('ReviewContext — flows CRUD', () => {
  it('adds a new flow requiring both source and target', async () => {
    createFlow.mockResolvedValue({ id: 'f2', source_entity: 'A', target_entity: 'B', flow_description: '' })
    render(ReviewContext, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Payments Service')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('+ Add flow'))
    await fireEvent.click(screen.getByText('Add'))
    expect(createFlow).not.toHaveBeenCalled()

    await fireEvent.input(screen.getByLabelText('New flow source'), { target: { value: 'A' } })
    await fireEvent.input(screen.getByLabelText('New flow target'), { target: { value: 'B' } })
    await fireEvent.click(screen.getByText('Add'))

    await waitFor(() => expect(createFlow).toHaveBeenCalledWith('m1', expect.objectContaining({ source_entity: 'A', target_entity: 'B' })))
  })

  it('deletes a flow', async () => {
    getModelFlows.mockResolvedValue([flowA])
    deleteFlow.mockResolvedValue(null)
    render(ReviewContext, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('HTTPS request')).toBeInTheDocument())

    const [, deleteBtn] = screen.getAllByRole('button').filter(b => b.querySelector('path[fill-rule="evenodd"]'))
    await fireEvent.click(deleteBtn)

    await waitFor(() => expect(deleteFlow).toHaveBeenCalledWith('m1', 'f1'))
    await waitFor(() => expect(screen.queryByText('HTTPS request')).toBeNull())
  })
})

describe('ReviewContext — trust boundaries CRUD', () => {
  it('adds a new trust boundary requiring both source and target', async () => {
    createTrustBoundary.mockResolvedValue({ id: 'b2', source_entity: 'X', target_entity: 'Y', purpose: '' })
    render(ReviewContext, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Payments Service')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('+ Add boundary'))
    await fireEvent.input(screen.getByLabelText('New boundary source'), { target: { value: 'X' } })
    await fireEvent.input(screen.getByLabelText('New boundary target'), { target: { value: 'Y' } })
    await fireEvent.click(screen.getByText('Add'))

    await waitFor(() => expect(createTrustBoundary).toHaveBeenCalledWith('m1', expect.objectContaining({ source_entity: 'X', target_entity: 'Y' })))
  })

  it('deletes a trust boundary', async () => {
    getModelTrustBoundaries.mockResolvedValue([boundaryA])
    deleteTrustBoundary.mockResolvedValue(null)
    render(ReviewContext, { props: { params: { id: 'm1' } } })
    await waitFor(() => expect(screen.getByText('Perimeter')).toBeInTheDocument())

    const [, deleteBtn] = screen.getAllByRole('button').filter(b => b.querySelector('path[fill-rule="evenodd"]'))
    await fireEvent.click(deleteBtn)

    await waitFor(() => expect(deleteTrustBoundary).toHaveBeenCalledWith('m1', 'b1'))
    await waitFor(() => expect(screen.queryByText('Perimeter')).toBeNull())
  })
})
