import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import Settings from './Settings.svelte'

vi.mock('../lib/api.js', () => ({
  getConfig: vi.fn(),
  updateConfig: vi.fn(),
  getHealth: vi.fn(),
  testProvider: vi.fn(),
}))

vi.mock('../lib/stores.js', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, notify: vi.fn() }
})

import { getConfig, updateConfig, getHealth, testProvider } from '../lib/api.js'
import { notify, config } from '../lib/stores.js'

const baseConfig = {
  default_provider: 'anthropic',
  model: 'claude-sonnet-4-20250514',
  fast_model: 'claude-haiku-4-5',
  default_iterations: 3,
  similarity_threshold: 0.85,
  ollama_base_url: '',
  anthropic_api_key_set: false,
  anthropic_api_key_source: null,
  openai_api_key_set: false,
  openai_api_key_source: null,
  config_secret_required: false,
  first_run: false,
}

beforeEach(() => {
  vi.clearAllMocks()
  config.set(null)
  getConfig.mockResolvedValue({ ...baseConfig })
  getHealth.mockResolvedValue({ status: 'healthy', version: '1.0.0', provider: 'anthropic', model: 'claude-sonnet-4' })
})

describe('Settings — loading', () => {
  it('loads config and health on mount', async () => {
    render(Settings)
    await waitFor(() => expect(getConfig).toHaveBeenCalled())
    expect(getHealth).toHaveBeenCalled()
    await waitFor(() => expect(screen.getByText('healthy')).toBeInTheDocument())
  })

  it('notifies on config load failure', async () => {
    getConfig.mockRejectedValue(new Error('unreachable'))
    render(Settings)
    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('unreachable')))
  })

  it('shows "Backend unreachable" when health check fails', async () => {
    getHealth.mockRejectedValue(new Error('down'))
    render(Settings)
    await waitFor(() => expect(screen.getByText('Backend unreachable')).toBeInTheDocument())
  })

  it('shows the first-run welcome banner when config.first_run is true', async () => {
    getConfig.mockResolvedValue({ ...baseConfig, first_run: true })
    render(Settings)
    await waitFor(() => expect(screen.getByText(/let's get you connected/)).toBeInTheDocument())
  })

  it('does not show the welcome banner when first_run is false', async () => {
    render(Settings)
    await waitFor(() => expect(screen.getByText('healthy')).toBeInTheDocument())
    expect(screen.queryByText(/let's get you connected/)).toBeNull()
  })
})

describe('Settings — form fields', () => {
  it('populates the draft from the loaded config', async () => {
    render(Settings)
    await waitFor(() => expect(screen.getByDisplayValue('claude-sonnet-4-20250514')).toBeInTheDocument())
    expect(screen.getByDisplayValue('claude-haiku-4-5')).toBeInTheDocument()
    expect(screen.getByDisplayValue('3')).toBeInTheDocument()
    expect(screen.getByDisplayValue('0.85')).toBeInTheDocument()
  })

  it('shows the config secret field only when required', async () => {
    getConfig.mockResolvedValue({ ...baseConfig, config_secret_required: true })
    render(Settings)
    await waitFor(() => expect(screen.getByLabelText(/Config secret/)).toBeInTheDocument())
  })

  it('hides the config secret field when not required', async () => {
    render(Settings)
    await waitFor(() => expect(screen.getByText('healthy')).toBeInTheDocument())
    expect(screen.queryByLabelText(/Config secret/)).toBeNull()
  })
})

describe('Settings — API keys', () => {
  it('shows an env-managed key as locked and non-editable', async () => {
    getConfig.mockResolvedValue({ ...baseConfig, anthropic_api_key_set: true, anthropic_api_key_source: 'env' })
    render(Settings)
    await waitFor(() => expect(screen.getByText('managed via env')).toBeInTheDocument())
    const input = screen.getByDisplayValue('••••••••')
    expect(input).toBeDisabled()
  })

  it('shows Replace/Clear for a stored (non-env) key', async () => {
    getConfig.mockResolvedValue({ ...baseConfig, anthropic_api_key_set: true, anthropic_api_key_source: 'db' })
    render(Settings)
    await waitFor(() => expect(screen.getByText('stored (encrypted)')).toBeInTheDocument())
    expect(screen.getByText('Replace')).toBeInTheDocument()
    expect(screen.getByText('Clear')).toBeInTheDocument()
  })

  it('marks a key for clearing and allows undo', async () => {
    getConfig.mockResolvedValue({ ...baseConfig, anthropic_api_key_set: true, anthropic_api_key_source: 'db' })
    render(Settings)
    await waitFor(() => expect(screen.getByText('Clear')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Clear'))
    expect(screen.getByText('will be cleared on save')).toBeInTheDocument()

    await fireEvent.click(screen.getByText('Undo'))
    expect(screen.getByText('stored (encrypted)')).toBeInTheDocument()
  })

  it('shows a paste-to-save input when no key is set', async () => {
    render(Settings)
    await waitFor(() => expect(screen.getAllByText('paste to save').length).toBeGreaterThan(0))
  })

  it('tests a provider connection and shows the result', async () => {
    testProvider.mockResolvedValue({ ok: true, latency_ms: 42 })
    render(Settings)
    await waitFor(() => expect(screen.getByPlaceholderText('sk-ant-…')).toBeInTheDocument())

    await fireEvent.input(screen.getByPlaceholderText('sk-ant-…'), { target: { value: 'sk-ant-test' } })
    await fireEvent.click(screen.getByText('Test'))

    await waitFor(() => expect(testProvider).toHaveBeenCalledWith(
      expect.objectContaining({ provider: 'anthropic', api_key: 'sk-ant-test' })
    ))
    await waitFor(() => expect(screen.getByText('✓ Connected (42 ms)')).toBeInTheDocument())
  })

  it('shows a failure message when the connection test fails', async () => {
    testProvider.mockResolvedValue({ ok: false, message: 'invalid key' })
    render(Settings)
    await waitFor(() => expect(screen.getByPlaceholderText('sk-ant-…')).toBeInTheDocument())

    await fireEvent.input(screen.getByPlaceholderText('sk-ant-…'), { target: { value: 'bad-key' } })
    await fireEvent.click(screen.getByText('Test'))

    await waitFor(() => expect(screen.getByText('✗ invalid key')).toBeInTheDocument())
  })
})

describe('Settings — save', () => {
  it('saves the draft and updates the config store', async () => {
    const updated = { ...baseConfig, default_iterations: 5 }
    updateConfig.mockResolvedValue(updated)
    render(Settings)
    await waitFor(() => expect(screen.getByDisplayValue('3')).toBeInTheDocument())

    await fireEvent.input(screen.getByLabelText('Default iterations'), { target: { value: '5' } })
    await fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(updateConfig).toHaveBeenCalledWith(
      expect.objectContaining({ default_iterations: 5 }),
      undefined,
    ))
    await waitFor(() => expect(notify).toHaveBeenCalledWith('success', 'Settings saved'))
  })

  it('includes the config secret header value when provided', async () => {
    getConfig.mockResolvedValue({ ...baseConfig, config_secret_required: true })
    updateConfig.mockResolvedValue(baseConfig)
    render(Settings)
    await waitFor(() => expect(screen.getByLabelText(/Config secret/)).toBeInTheDocument())

    await fireEvent.input(screen.getByLabelText(/Config secret/), { target: { value: 'shh' } })
    await fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(updateConfig).toHaveBeenCalledWith(expect.any(Object), 'shh'))
  })

  it('notifies on save failure', async () => {
    updateConfig.mockRejectedValue(new Error('forbidden'))
    render(Settings)
    await waitFor(() => expect(screen.getByText('healthy')).toBeInTheDocument())

    await fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('forbidden')))
  })

  it('resets the draft back to the last-loaded config', async () => {
    render(Settings)
    await waitFor(() => expect(screen.getByDisplayValue('3')).toBeInTheDocument())

    await fireEvent.input(screen.getByLabelText('Default iterations'), { target: { value: '9' } })
    expect(screen.getByDisplayValue('9')).toBeInTheDocument()

    await fireEvent.click(screen.getByText('Reset'))
    expect(screen.getByDisplayValue('3')).toBeInTheDocument()
  })
})

describe('Settings — env var reference and McpConfig', () => {
  it('renders the env var reference table', async () => {
    render(Settings)
    await waitFor(() => expect(screen.getByText('ANTHROPIC_API_KEY')).toBeInTheDocument())
    expect(screen.getByText('DEFAULT_ITERATIONS')).toBeInTheDocument()
  })

  it('renders the McpConfig panel', async () => {
    render(Settings)
    await waitFor(() => expect(screen.getByText('Code Context via context-link')).toBeInTheDocument())
  })
})
