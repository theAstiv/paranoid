import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import TestCases from './TestCases.svelte'

vi.mock('svelte-spa-router', () => ({
  link: () => ({ destroy: () => {} }),
}))

vi.mock('../lib/api.js', () => ({
  getThreat: vi.fn(),
  listTestCases: vi.fn(),
  generateTestCases: vi.fn(),
}))

vi.mock('../lib/stores.js', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, notify: vi.fn() }
})

import { getThreat, listTestCases, generateTestCases } from '../lib/api.js'
import { notify, currentModel } from '../lib/stores.js'

const baseThreat = { id: 't1', name: 'SQL Injection', description: 'desc' }

beforeEach(() => {
  vi.clearAllMocks()
  currentModel.set(null)
  getThreat.mockResolvedValue(baseThreat)
  listTestCases.mockResolvedValue([])
})

describe('TestCases — loading', () => {
  it('loads the threat and shows its details', async () => {
    render(TestCases, { props: { params: { id: 't1' } } })
    await waitFor(() => expect(screen.getByText('SQL Injection')).toBeInTheDocument())
    expect(screen.getByText('desc')).toBeInTheDocument()
  })

  it('notifies on load failure', async () => {
    getThreat.mockRejectedValue(new Error('not found'))
    render(TestCases, { props: { params: { id: 't1' } } })
    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('not found')))
  })

  it('shows an empty state when there are no test cases yet', async () => {
    render(TestCases, { props: { params: { id: 't1' } } })
    await waitFor(() => expect(screen.getByText(/No test cases yet/)).toBeInTheDocument())
    expect(screen.getByText('Generate')).toBeInTheDocument()
  })

  it('picks the most recently generated test case', async () => {
    listTestCases.mockResolvedValue([
      { id: 'tc1', gherkin_source: 'Scenario: old' },
      { id: 'tc2', gherkin_source: 'Scenario: newest' },
    ])
    render(TestCases, { props: { params: { id: 't1' } } })
    await waitFor(() => expect(screen.getByText('Scenario: newest')).toBeInTheDocument())
    expect(screen.queryByText('Scenario: old')).toBeNull()
  })

  it('shows the "← Review" link only when a current model is set', async () => {
    currentModel.set({ id: 'm1' })
    const { container } = render(TestCases, { props: { params: { id: 't1' } } })
    await waitFor(() => expect(screen.getByText('SQL Injection')).toBeInTheDocument())
    expect(container.querySelector('a[href="/models/m1/review"]')).not.toBeNull()
  })
})

describe('TestCases — generate', () => {
  it('generates test cases and renders the Gherkin source', async () => {
    generateTestCases.mockResolvedValue({ id: 'tc1', gherkin_source: 'Scenario: injected' })
    render(TestCases, { props: { params: { id: 't1' } } })
    await waitFor(() => expect(screen.getByText('Generate')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Generate'))

    await waitFor(() => expect(generateTestCases).toHaveBeenCalledWith('t1'))
    await waitFor(() => expect(screen.getByText('Scenario: injected')).toBeInTheDocument())
    expect(screen.getByText('Regenerate')).toBeInTheDocument()
  })

  it('notifies on generation failure', async () => {
    generateTestCases.mockRejectedValue(new Error('LLM timeout'))
    render(TestCases, { props: { params: { id: 't1' } } })
    await waitFor(() => expect(screen.getByText('Generate')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Generate'))

    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('LLM timeout')))
  })

  it('does not show a Copy button before a test case exists', async () => {
    render(TestCases, { props: { params: { id: 't1' } } })
    await waitFor(() => expect(screen.getByText('Generate')).toBeInTheDocument())
    expect(screen.queryByText('Copy')).toBeNull()
  })
})

describe('TestCases — copy to clipboard', () => {
  it('copies the gherkin source and notifies success', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    listTestCases.mockResolvedValue([{ id: 'tc1', gherkin_source: 'Scenario: injected' }])
    render(TestCases, { props: { params: { id: 't1' } } })
    await waitFor(() => expect(screen.getByText('Copy')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Copy'))

    expect(writeText).toHaveBeenCalledWith('Scenario: injected')
    await waitFor(() => expect(notify).toHaveBeenCalledWith('success', 'Copied to clipboard'))
    vi.unstubAllGlobals()
  })

  it('notifies an error when the clipboard write fails', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('denied'))
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    listTestCases.mockResolvedValue([{ id: 'tc1', gherkin_source: 'Scenario: injected' }])
    render(TestCases, { props: { params: { id: 't1' } } })
    await waitFor(() => expect(screen.getByText('Copy')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Copy'))

    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', 'Failed to copy'))
    vi.unstubAllGlobals()
  })
})
