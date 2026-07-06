import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/svelte'
import ModelCard from './ModelCard.svelte'

// link action from svelte-spa-router is a DOM action — stub it so tests
// don't depend on a router context.
vi.mock('svelte-spa-router', () => ({
  link: () => ({ destroy: () => {} }),
}))

const baseModel = {
  id: 'model-1',
  title: 'Payments API',
  framework: 'STRIDE',
  status: 'completed',
  threat_count: 12,
  created_at: '2026-01-15T00:00:00.000Z',
  description: 'Threat model for the payments service.',
}

describe('ModelCard', () => {
  it('renders title, framework chip, and formatted date', () => {
    render(ModelCard, { props: { model: baseModel } })
    expect(screen.getByText('Payments API')).toBeInTheDocument()
    expect(screen.getByText('STRIDE')).toBeInTheDocument()
    // Date formatting is locale-dependent (toLocaleDateString) — assert on the
    // parts rather than a fixed string so this doesn't break under a different locale.
    const dateText = new Date(baseModel.created_at).toLocaleDateString(undefined, {
      month: 'short', day: 'numeric', year: 'numeric',
    })
    expect(screen.getByText(dateText)).toBeInTheDocument()
  })

  it('renders the description when present', () => {
    render(ModelCard, { props: { model: baseModel } })
    expect(screen.getByText('Threat model for the payments service.')).toBeInTheDocument()
  })

  it('omits the description paragraph when absent', () => {
    const { container } = render(ModelCard, { props: { model: { ...baseModel, description: undefined } } })
    expect(container.querySelector('p')).toBeNull()
  })

  it('shows threat count when present', () => {
    render(ModelCard, { props: { model: baseModel } })
    expect(screen.getByText('12 threats')).toBeInTheDocument()
  })

  it('hides threat count when null', () => {
    render(ModelCard, { props: { model: { ...baseModel, threat_count: null } } })
    expect(screen.queryByText(/threats$/)).toBeNull()
  })

  it('renders a humanized status label with underscores replaced by spaces', () => {
    render(ModelCard, { props: { model: { ...baseModel, status: 'in_review' } } })
    expect(screen.getByText('in review')).toBeInTheDocument()
  })

  it('falls back to a gray chip for an unknown framework or status', () => {
    const { container } = render(ModelCard, {
      props: { model: { ...baseModel, framework: 'UNKNOWN', status: 'weird_status' } },
    })
    const chips = container.querySelectorAll('.chip-gray')
    expect(chips.length).toBeGreaterThanOrEqual(2)
  })

  it('links to the model detail page', () => {
    const { container } = render(ModelCard, { props: { model: baseModel } })
    const anchor = container.querySelector('a')
    expect(anchor.getAttribute('href')).toBe('/models/model-1')
  })

  it('does not render a delete button when onDelete is not provided', () => {
    render(ModelCard, { props: { model: baseModel } })
    expect(screen.queryByTitle('Delete threat model')).toBeNull()
  })

  it('renders a delete button and calls onDelete when clicked', async () => {
    const onDelete = vi.fn()
    render(ModelCard, { props: { model: baseModel, onDelete } })
    const btn = screen.getByTitle('Delete threat model')
    await fireEvent.click(btn)
    expect(onDelete).toHaveBeenCalledOnce()
  })
})
