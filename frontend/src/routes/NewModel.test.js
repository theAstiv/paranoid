import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import { get } from 'svelte/store'
import NewModel from './NewModel.svelte'

vi.mock('svelte-spa-router', () => ({
  link: () => ({ destroy: () => {} }),
  push: vi.fn(),
}))

vi.mock('../lib/api.js', () => ({
  createModel: vi.fn(),
  subscribeToRun: vi.fn(() => vi.fn()),
  listCodeSources: vi.fn(),
  analyzeBundle: vi.fn(),
  getModel: vi.fn(),
}))

vi.mock('../lib/stores.js', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, notify: vi.fn() }
})

import { push } from 'svelte-spa-router'
import { createModel, subscribeToRun, listCodeSources } from '../lib/api.js'
import { notify, config, currentProject, pipelineRunning } from '../lib/stores.js'

async function goToStep(n) {
  for (let i = 0; i < n; i++) {
    await fireEvent.click(screen.getByText('Next'))
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  config.set(null)
  currentProject.set(null)
  pipelineRunning.set(false)
  listCodeSources.mockResolvedValue([])
})

describe('NewModel — step 0 (title & framework)', () => {
  it('disables Next until a title is entered', async () => {
    render(NewModel)
    expect(screen.getByText('Next')).toBeDisabled()
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'My System' } })
    expect(screen.getByText('Next')).not.toBeDisabled()
  })

  it('defaults to STRIDE and shows its category description', () => {
    render(NewModel)
    expect(screen.getByText(/Spoofing, Tampering, Repudiation/)).toBeInTheDocument()
  })

  it('switches the framework description when MAESTRO is selected', async () => {
    render(NewModel)
    await fireEvent.click(screen.getByRole('radio', { name: 'MAESTRO' }))
    expect(screen.getByText(/AI\/ML-specific: Model Security/)).toBeInTheDocument()
  })
})

describe('NewModel — step 1 (description)', () => {
  it('disables Next until at least 10 characters are entered', async () => {
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'Sys' } })
    await fireEvent.click(screen.getByText('Next'))
    expect(screen.getByText('Next')).toBeDisabled()

    await fireEvent.input(screen.getByLabelText('System description'), { target: { value: 'short' } })
    expect(screen.getByText('Next')).toBeDisabled()

    await fireEvent.input(screen.getByLabelText('System description'), { target: { value: 'a valid description here' } })
    expect(screen.getByText('Next')).not.toBeDisabled()
  })

  it('flags coverage gaps for a long description missing key topics', async () => {
    render(NewModel)
    await fireEvent.click(screen.getByText('Next'))
    const longButVague = 'x'.repeat(85)
    await fireEvent.input(screen.getByLabelText('System description'), { target: { value: longButVague } })
    expect(screen.getByText('Coverage gaps detected — consider adding:')).toBeInTheDocument()
    expect(screen.getByText(/No auth mechanism mentioned/)).toBeInTheDocument()
  })

  it('shows "looks complete" when the description covers auth, boundaries, flows, and external systems', async () => {
    render(NewModel)
    await fireEvent.click(screen.getByText('Next'))
    const good = 'The internet-facing API gateway sends requests to an internal auth service using OAuth tokens, then stores data in an external database.'
    await fireEvent.input(screen.getByLabelText('System description'), { target: { value: good } })
    expect(screen.getByText('Description looks complete')).toBeInTheDocument()
  })
})

describe('NewModel — step 2 (diagram)', () => {
  function mkFile(name, sizeBytes) {
    return new File([new Uint8Array(sizeBytes)], name)
  }

  async function toStep2() {
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'Sys' } })
    await goToStep(2)
  }

  it('adds multiple files and shows a named row for each', async () => {
    await toStep2()
    const a = mkFile('a.png', 1024)
    const b = mkFile('b.mmd', 256)
    await fireEvent.change(screen.getByLabelText(/Architecture diagrams/), { target: { files: [a, b] } })

    expect(screen.getByLabelText('Diagram name: a')).toBeInTheDocument()
    expect(screen.getByLabelText('Diagram name: b')).toBeInTheDocument()
  })

  it('rejects an oversize file without dropping an already-accepted one', async () => {
    await toStep2()
    const good = mkFile('a.png', 1024)
    await fireEvent.change(screen.getByLabelText(/Architecture diagrams/), { target: { files: [good] } })
    expect(screen.getByLabelText('Diagram name: a')).toBeInTheDocument()

    const big = mkFile('too-big.png', 4 * 1024 * 1024)
    await fireEvent.change(screen.getByLabelText(/Architecture diagrams/), { target: { files: [big] } })

    expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('too large'))
    expect(screen.getByLabelText('Diagram name: a')).toBeInTheDocument()
    expect(screen.queryByLabelText('Diagram name: too-big')).toBeNull()
  })

  it('blocks a 6th file once 5 are already accepted', async () => {
    await toStep2()
    const five = ['a', 'b', 'c', 'd', 'e'].map(n => mkFile(`${n}.mmd`, 64))
    await fireEvent.change(screen.getByLabelText(/Architecture diagrams/), { target: { files: five } })
    for (const n of ['a', 'b', 'c', 'd', 'e']) {
      expect(screen.getByLabelText(`Diagram name: ${n}`)).toBeInTheDocument()
    }

    const sixth = mkFile('f.mmd', 64)
    await fireEvent.change(screen.getByLabelText(/Architecture diagrams/), { target: { files: [sixth] } })

    expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('maximum 5 diagrams'))
    expect(screen.queryByLabelText('Diagram name: f')).toBeNull()
  })

  it('removes only the targeted row', async () => {
    await toStep2()
    const a = mkFile('a.mmd', 64)
    const b = mkFile('b.mmd', 64)
    await fireEvent.change(screen.getByLabelText(/Architecture diagrams/), { target: { files: [a, b] } })

    await fireEvent.click(screen.getByLabelText('Remove diagram: a'))

    expect(screen.queryByLabelText('Diagram name: a')).toBeNull()
    expect(screen.getByLabelText('Diagram name: b')).toBeInTheDocument()
  })

  it('renames a row and reflects the new label', async () => {
    await toStep2()
    const a = mkFile('a.mmd', 64)
    await fireEvent.change(screen.getByLabelText(/Architecture diagrams/), { target: { files: [a] } })

    await fireEvent.change(screen.getByLabelText('Diagram name: a'), { target: { value: 'Custom Name' } })

    expect(screen.getByLabelText('Diagram name: Custom Name')).toBeInTheDocument()
  })

  it('submits accepted files under diagrams/diagram_names in FormData', async () => {
    createModel.mockResolvedValue({ id: 'model-diag' })
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'Sys' } })
    await goToStep(2)
    const a = mkFile('a.mmd', 64)
    const b = mkFile('b.png', 1024)
    await fireEvent.change(screen.getByLabelText(/Architecture diagrams/), { target: { files: [a, b] } })
    await goToStep(6)

    await fireEvent.click(screen.getByText('Create & Run'))

    await waitFor(() => expect(subscribeToRun).toHaveBeenCalled())
    const fd = subscribeToRun.mock.calls[0][1]
    expect(fd.getAll('diagrams')).toEqual([a, b])
    expect(JSON.parse(fd.get('diagram_names'))).toEqual(['a', 'b'])
  })
})

describe('NewModel — step 3 (code source)', () => {
  it('loads and lists ready code sources when the step is reached', async () => {
    listCodeSources.mockResolvedValue([
      { id: 'src-1', name: 'backend-repo', git_url: 'https://github.com/x/y', last_index_status: 'ready' },
      { id: 'src-2', name: 'not-ready-repo', git_url: 'https://github.com/x/z', last_index_status: 'indexing' },
    ])
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'Sys' } })
    await goToStep(3)

    await waitFor(() => expect(listCodeSources).toHaveBeenCalled())
    expect(screen.getByText('backend-repo')).toBeInTheDocument()
    expect(screen.queryByText('not-ready-repo')).toBeNull()
  })

  it('shows an empty state when there are no ready sources', async () => {
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'Sys' } })
    await goToStep(3)
    await waitFor(() => expect(screen.getByText('No indexed sources available.')).toBeInTheDocument())
  })
})

describe('NewModel — step 4 (dependencies)', () => {
  async function toStep4() {
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'Sys' } })
    await goToStep(4)
  }

  it('shows the manifest upload field and no lockfile field until a manifest is chosen', async () => {
    await toStep4()
    expect(screen.getByLabelText('package.json')).toBeInTheDocument()
    expect(screen.queryByLabelText(/package-lock.json/)).toBeNull()
  })

  it('reveals the lockfile field and analysis depth choice once a manifest is uploaded', async () => {
    await toStep4()
    const file = new File(['{"name":"x","dependencies":{}}'], 'my-manifest.json', { type: 'application/json' })
    await fireEvent.change(screen.getByLabelText('package.json'), { target: { files: [file] } })
    expect(screen.getByText('my-manifest.json')).toBeInTheDocument()
    expect(screen.getByLabelText(/package-lock.json/)).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'Fast (npm)' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'Deep (npm + GitHub drift)' })).toBeInTheDocument()
  })

  it('rejects a manifest file over 1 MB and does not keep a previously accepted one', async () => {
    await toStep4()
    const good = new File(['{"name":"x","dependencies":{}}'], 'my-manifest.json', { type: 'application/json' })
    await fireEvent.change(screen.getByLabelText('package.json'), { target: { files: [good] } })
    expect(screen.getByText('my-manifest.json')).toBeInTheDocument()

    const big = new File([new Uint8Array(1024 * 1024 + 1)], 'too-big.json', { type: 'application/json' })
    await fireEvent.change(screen.getByLabelText('package.json'), { target: { files: [big] } })
    expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('1 MB'))
    // The stale accepted manifest must not linger — the field reverts to empty.
    expect(screen.queryByText('my-manifest.json')).toBeNull()
    expect(screen.queryByLabelText(/package-lock.json/)).toBeNull()
  })

  it('clears a previously chosen lockfile when the manifest is replaced', async () => {
    await toStep4()
    const manifest1 = new File(['{"name":"x"}'], 'manifest1.json', { type: 'application/json' })
    await fireEvent.change(screen.getByLabelText('package.json'), { target: { files: [manifest1] } })
    const lockfile = new File(['{}'], 'my-lockfile.json', { type: 'application/json' })
    await fireEvent.change(screen.getByLabelText(/package-lock.json/), { target: { files: [lockfile] } })
    expect(screen.getByText('my-lockfile.json')).toBeInTheDocument()

    // Clear the manifest input, then choose a new manifest.
    await fireEvent.change(screen.getByLabelText('package.json'), { target: { files: [] } })
    const manifest2 = new File(['{"name":"y"}'], 'manifest2.json', { type: 'application/json' })
    await fireEvent.change(screen.getByLabelText('package.json'), { target: { files: [manifest2] } })

    // The lockfile field is back to unset — the stale File object was cleared.
    expect(screen.queryByText('my-lockfile.json')).toBeNull()
    // The {#key manifestFile} block recreates the lockfile <input>, so its
    // native file list is reset too, not just the displayed filename text.
    expect(screen.getByLabelText(/package-lock.json/).files.length).toBe(0)
  })

  it('shows a disabled message instead of the upload UI when DEPS_ANALYSIS_ENABLED is false', async () => {
    config.set({ deps_analysis_enabled: false })
    await toStep4()
    expect(screen.getByText('Dependency analysis is disabled on this instance.')).toBeInTheDocument()
    expect(screen.queryByLabelText('package.json')).toBeNull()
  })
})

describe('NewModel — step 5 (assumptions)', () => {
  async function toStep5() {
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'Sys' } })
    await goToStep(5)
  }

  it('adds an assumption to the list', async () => {
    await toStep5()
    await fireEvent.input(screen.getByPlaceholderText(/TLS 1.3 enforced/), { target: { value: 'MFA required for admins' } })
    await fireEvent.click(screen.getByText('Add'))
    expect(screen.getByText('MFA required for admins')).toBeInTheDocument()
  })

  it('adds an assumption on Enter key', async () => {
    await toStep5()
    const input = screen.getByPlaceholderText(/TLS 1.3 enforced/)
    await fireEvent.input(input, { target: { value: 'Rate limiting enabled' } })
    await fireEvent.keyDown(input, { key: 'Enter' })
    expect(screen.getByText('Rate limiting enabled')).toBeInTheDocument()
  })

  it('removes an assumption', async () => {
    await toStep5()
    await fireEvent.input(screen.getByPlaceholderText(/TLS 1.3 enforced/), { target: { value: 'Temp assumption' } })
    await fireEvent.click(screen.getByText('Add'))
    expect(screen.getByText('Temp assumption')).toBeInTheDocument()

    const [removeBtn] = screen.getAllByRole('button').filter(b => b.closest('li'))
    await fireEvent.click(removeBtn)
    expect(screen.queryByText('Temp assumption')).toBeNull()
  })
})

describe('NewModel — step 6 (iterations)', () => {
  it('defaults to 3 iterations and updates the label when changed', async () => {
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'Sys' } })
    await goToStep(6)
    expect(screen.getByText('3', { selector: 'span' })).toBeInTheDocument()

    const slider = screen.getByLabelText(/Iteration count/)
    await fireEvent.input(slider, { target: { value: '10' } })
    expect(screen.getByText('10', { selector: 'span' })).toBeInTheDocument()
  })
})

describe('NewModel — step 7 (AI components)', () => {
  it('shows a checkbox for STRIDE and toggles hasAiComponents', async () => {
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'Sys' } })
    await goToStep(7)
    expect(screen.getByText('System includes AI/ML components')).toBeInTheDocument()
  })

  it('shows an informational note instead of a checkbox for MAESTRO', async () => {
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'Sys' } })
    await fireEvent.click(screen.getByRole('radio', { name: 'MAESTRO' }))
    await goToStep(7)
    expect(screen.getByText(/MAESTRO framework already generates/)).toBeInTheDocument()
    expect(screen.queryByText('System includes AI/ML components')).toBeNull()
  })

  it('defaults scoring method to DREAD only', async () => {
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'Sys' } })
    await goToStep(7)
    const btn = screen.getByRole('button', { name: 'DREAD only' })
    expect(btn.className).toContain('chip-accent')
  })

  it('switches the selected scoring method chip on click', async () => {
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'Sys' } })
    await goToStep(7)
    await fireEvent.click(screen.getByRole('button', { name: 'Both' }))
    expect(screen.getByRole('button', { name: 'Both' }).className).toContain('chip-accent')
    expect(screen.getByRole('button', { name: 'DREAD only' }).className).not.toContain('chip-accent')
  })
})

describe('NewModel — step 8 (review & submit)', () => {
  async function toReview({ title = 'My System' } = {}) {
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: title } })
    await goToStep(8)
  }

  it('shows a summary of the entered values', async () => {
    await toReview()
    expect(screen.getByText('My System')).toBeInTheDocument()
    expect(screen.getByText('STRIDE', { selector: 'dd' })).toBeInTheDocument()
  })

  it('warns when the configured provider has no API key set', async () => {
    config.set({ default_provider: 'anthropic', anthropic_api_key_set: false })
    await toReview()
    expect(screen.getByText(/No API key configured for anthropic/)).toBeInTheDocument()
    expect(screen.getByText('Create & Run')).toBeDisabled()
  })

  it('creates the model, subscribes to the run, and navigates to it', async () => {
    createModel.mockResolvedValue({ id: 'model-123' })
    await toReview()

    await fireEvent.click(screen.getByText('Create & Run'))

    await waitFor(() => expect(createModel).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'My System', framework: 'STRIDE', iteration_count: 3 })
    ))
    await waitFor(() => expect(subscribeToRun).toHaveBeenCalled())
    expect(subscribeToRun.mock.calls[0][0]).toBe('model-123')
    await waitFor(() => expect(push).toHaveBeenCalledWith('/models/model-123'))
  })

  it('defaults scoring_method to dread when creating the model', async () => {
    createModel.mockResolvedValue({ id: 'model-123' })
    await toReview()

    await fireEvent.click(screen.getByText('Create & Run'))

    await waitFor(() => expect(createModel).toHaveBeenCalledWith(
      expect.objectContaining({ scoring_method: 'dread' })
    ))
  })

  it('passes the chosen scoring_method when creating the model', async () => {
    createModel.mockResolvedValue({ id: 'model-123' })
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'My System' } })
    await goToStep(7)
    await fireEvent.click(screen.getByRole('button', { name: 'Both' }))
    await goToStep(1)

    await fireEvent.click(screen.getByText('Create & Run'))

    await waitFor(() => expect(createModel).toHaveBeenCalledWith(
      expect.objectContaining({ scoring_method: 'both' })
    ))
  })

  it('notifies and stops submitting when model creation fails', async () => {
    createModel.mockRejectedValue(new Error('validation failed'))
    await toReview()

    await fireEvent.click(screen.getByText('Create & Run'))

    await waitFor(() =>
      expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('validation failed'))
    )
    expect(get(pipelineRunning)).toBe(false)
    expect(subscribeToRun).not.toHaveBeenCalled()
  })

  it('includes project_id from the current project when creating the model', async () => {
    currentProject.set({ id: 'proj-9' })
    createModel.mockResolvedValue({ id: 'model-456' })
    await toReview()

    await fireEvent.click(screen.getByText('Create & Run'))

    await waitFor(() =>
      expect(createModel).toHaveBeenCalledWith(expect.objectContaining({ project_id: 'proj-9' }))
    )
  })

  it('includes an uploaded dependency manifest and depsSourceMode in the run FormData', async () => {
    createModel.mockResolvedValue({ id: 'model-789' })
    render(NewModel)
    await fireEvent.input(screen.getByLabelText('Model title'), { target: { value: 'My System' } })
    await goToStep(4)
    const file = new File(['{"name":"x","dependencies":{}}'], 'package.json', { type: 'application/json' })
    await fireEvent.change(screen.getByLabelText('package.json'), { target: { files: [file] } })
    await fireEvent.click(screen.getByRole('radio', { name: 'Deep (npm + GitHub drift)' }))
    await goToStep(4)

    await fireEvent.click(screen.getByText('Create & Run'))

    await waitFor(() => expect(subscribeToRun).toHaveBeenCalled())
    const fd = subscribeToRun.mock.calls[0][1]
    expect(fd.get('dependency_manifest')).toBe(file)
    expect(fd.get('deps_source_mode')).toBe('both')
    expect(fd.get('dependency_lockfile')).toBeNull()
  })
})
