import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import ExportMenu from './ExportMenu.svelte'
import { downloadExport } from '../lib/api.js'
import { notify } from '../lib/stores.js'

vi.mock('../lib/api.js', () => ({
  downloadExport: vi.fn(() => Promise.resolve()),
}))

vi.mock('../lib/stores.js', () => ({
  notify: vi.fn(),
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

  it('downloads through downloadExport with the status filter, not window.open', async () => {
    render(ExportMenu, { props: { modelId: 'model-42', statusFilter: 'approved' } })
    await fireEvent.click(screen.getByText('Export'))
    await fireEvent.click(screen.getByText('PDF'))
    expect(downloadExport).toHaveBeenCalledOnce()
    // statusFilter must be forwarded or filtered exports silently break.
    expect(downloadExport).toHaveBeenCalledWith('model-42', 'pdf', 'approved')
    expect(window.open).not.toHaveBeenCalled()
  })

  it('shows an error toast when the download fails', async () => {
    downloadExport.mockRejectedValueOnce(new Error('Model not found'))
    render(ExportMenu, { props: { modelId: 'model-1' } })
    await fireEvent.click(screen.getByText('Export'))
    await fireEvent.click(screen.getByText('PDF'))
    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', 'Export failed: Model not found'))
  })

  it('disables the Export button while a download is pending', async () => {
    let finish
    downloadExport.mockReturnValueOnce(new Promise((resolve) => { finish = resolve }))
    render(ExportMenu, { props: { modelId: 'model-1' } })
    await fireEvent.click(screen.getByText('Export'))
    await fireEvent.click(screen.getByText('PDF'))
    const button = screen.getByText('Export').closest('button')
    expect(button).toBeDisabled()
    finish()
    await waitFor(() => expect(button).not.toBeDisabled())
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
