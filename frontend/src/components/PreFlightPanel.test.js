import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/svelte'
import PreFlightPanel from './PreFlightPanel.svelte'

const errorGap = { field: 'description', severity: 'error', message: 'Too short.' }
const warnGap = { field: 'target_users', severity: 'warning', message: 'Not specified.' }
const infoGap = { field: 'tech_stack', severity: 'info', message: 'Consider adding.' }

describe('PreFlightPanel', () => {
  it('shows spinner and loading text while loading', () => {
    render(PreFlightPanel, { props: { title: 'Description coverage', loading: true, gaps: [] } })
    expect(screen.getByText(/Checking description coverage/i)).toBeInTheDocument()
  })

  it('shows "looks good" when no gaps and not loading', () => {
    render(PreFlightPanel, { props: { title: 'Assumptions coverage', loading: false, gaps: [] } })
    expect(screen.getByText(/Assumptions coverage looks good/i)).toBeInTheDocument()
  })

  it('shows gap count in header when gaps exist', () => {
    render(PreFlightPanel, { props: { title: 'Description coverage', loading: false, gaps: [errorGap, warnGap] } })
    expect(screen.getByText(/2 gaps detected/i)).toBeInTheDocument()
  })

  it('shows singular "gap" for exactly one gap', () => {
    render(PreFlightPanel, { props: { title: 'Coverage', loading: false, gaps: [errorGap] } })
    expect(screen.getByText(/1 gap detected/i)).toBeInTheDocument()
  })

  it('renders gap messages when open', () => {
    render(PreFlightPanel, {
      props: { title: 'Coverage', loading: false, gaps: [errorGap, warnGap], collapsed: false }
    })
    expect(screen.getByText('Too short.')).toBeInTheDocument()
    expect(screen.getByText('Not specified.')).toBeInTheDocument()
  })

  it('renders severity badges for each gap', () => {
    render(PreFlightPanel, {
      props: { title: 'Coverage', loading: false, gaps: [errorGap, warnGap, infoGap], collapsed: false }
    })
    expect(screen.getByText('error')).toBeInTheDocument()
    expect(screen.getByText('warning')).toBeInTheDocument()
    expect(screen.getByText('info')).toBeInTheDocument()
  })

  it('replaces underscores with spaces in field name', () => {
    render(PreFlightPanel, {
      props: { title: 'Coverage', loading: false, gaps: [warnGap], collapsed: false }
    })
    expect(screen.getByText(/target users:/i)).toBeInTheDocument()
  })

  it('starts collapsed when collapsed prop is true', () => {
    render(PreFlightPanel, {
      props: { title: 'Coverage', loading: false, gaps: [errorGap], collapsed: true }
    })
    // Gap message should not be visible when collapsed
    expect(screen.queryByText('Too short.')).toBeNull()
  })

  it('expands when header button is clicked', async () => {
    render(PreFlightPanel, {
      props: { title: 'Coverage', loading: false, gaps: [errorGap], collapsed: true }
    })
    expect(screen.queryByText('Too short.')).toBeNull()
    // Click the header button to expand
    const header = screen.getByRole('button')
    await fireEvent.click(header)
    expect(screen.getByText('Too short.')).toBeInTheDocument()
  })

  it('hides chevron SVG while loading', () => {
    // The template renders the chevron only when !loading (`{#if !loading}`).
    // The spinner is present instead. We verify by counting SVG elements:
    // loading=true → 1 SVG (spinner); loading=false, no gaps → 2 SVGs (tick + chevron).
    const { container: loadingContainer } = render(PreFlightPanel, {
      props: { title: 'Coverage', loading: true, gaps: [] },
    })
    const svgsWhileLoading = loadingContainer.querySelectorAll('svg')

    const { container: doneContainer } = render(PreFlightPanel, {
      props: { title: 'Coverage', loading: false, gaps: [] },
    })
    const svgsWhenDone = doneContainer.querySelectorAll('svg')

    // Fewer SVGs while loading (no chevron), more when done (tick + chevron).
    expect(svgsWhileLoading.length).toBeLessThan(svgsWhenDone.length)
  })

  it('applies critical border for errors', () => {
    const { container } = render(PreFlightPanel, {
      props: { title: 'Coverage', loading: false, gaps: [errorGap] }
    })
    const wrapper = container.firstChild
    expect(wrapper.className).toContain('border-c-critical')
  })

  it('applies high border for warnings only', () => {
    const { container } = render(PreFlightPanel, {
      props: { title: 'Coverage', loading: false, gaps: [warnGap] }
    })
    const wrapper = container.firstChild
    expect(wrapper.className).toContain('border-c-high')
  })

  it('applies green border when no gaps', () => {
    const { container } = render(PreFlightPanel, {
      props: { title: 'Coverage', loading: false, gaps: [] }
    })
    const wrapper = container.firstChild
    expect(wrapper.className).toContain('border-c-green')
  })
})
