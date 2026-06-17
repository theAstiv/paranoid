import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/svelte'
import ExportMenu from './ExportMenu.svelte'

vi.mock('../lib/api.js', () => ({
  exportUrl: vi.fn((modelId, format, statusFilter) => {
    const params = new URLSearchParams({ format })
    if (statusFilter) params.set('status_filter', statusFilter)
    return `/api/export/${modelId}?${params.toString()}`
  }),
}))

describe('ExportMenu', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(window, 'open').mockImplementation(() => null)
  })

  it('renders the Export button', () => {
    render(ExportMenu, { props: { modelId: 'model-1' } })
    expect(screen.getByText('Export')).toBeInTheDocument()
  })

  it('dropdown is closed by default', () => {
    render(ExportMenu, { props: { modelId: 'model-1' } })
    expect(screen.queryByText('Markdown')).toBeNull()
    expect(screen.queryByText('PDF')).toBeNull()
  })

  it('opens dropdown when Export button is clicked', async () => {
    render(ExportMenu, { props: { modelId: 'model-1' } })
    await fireEvent.click(screen.getByText('Export'))
    expect(screen.getByText('Markdown')).toBeInTheDocument()
    expect(screen.getByText('PDF')).toBeInTheDocument()
    expect(screen.getByText('JSON')).toBeInTheDocument()
    expect(screen.getByText('SARIF')).toBeInTheDocument()
  })

  it('shows all four format buttons', async () => {
    render(ExportMenu, { props: { modelId: 'model-1' } })
    await fireEvent.click(screen.getByText('Export'))
    const formats = ['Markdown', 'PDF', 'JSON', 'SARIF']
    for (const fmt of formats) {
      expect(screen.getByText(fmt)).toBeInTheDocument()
    }
  })

  it('shows SARIF note about MAESTRO-only exclusion', async () => {
    render(ExportMenu, { props: { modelId: 'model-1' } })
    await fireEvent.click(screen.getByText('Export'))
    expect(screen.getByText(/MAESTRO-only excluded/)).toBeInTheDocument()
  })

  it('calls window.open with correct URL when a format is clicked', async () => {
    render(ExportMenu, { props: { modelId: 'model-42', statusFilter: 'approved' } })
    await fireEvent.click(screen.getByText('Export'))
    await fireEvent.click(screen.getByText('PDF'))
    expect(window.open).toHaveBeenCalledOnce()
    const url = window.open.mock.calls[0][0]
    expect(url).toContain('model-42')
    expect(url).toContain('format=pdf')
    // Verify statusFilter is forwarded — if ExportMenu stopped passing it to
    // exportUrl the filtered-export wiring would silently break.
    expect(url).toContain('status_filter=approved')
  })

  it('closes dropdown after a format is selected', async () => {
    render(ExportMenu, { props: { modelId: 'model-1' } })
    await fireEvent.click(screen.getByText('Export'))
    await fireEvent.click(screen.getByText('Markdown'))
    expect(screen.queryByText('PDF')).toBeNull()
  })

  it('toggles dropdown closed when Export is clicked again', async () => {
    render(ExportMenu, { props: { modelId: 'model-1' } })
    await fireEvent.click(screen.getByText('Export'))
    expect(screen.getByText('Markdown')).toBeInTheDocument()
    await fireEvent.click(screen.getByText('Export'))
    expect(screen.queryByText('Markdown')).toBeNull()
  })
})
