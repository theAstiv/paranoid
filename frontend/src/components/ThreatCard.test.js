import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/svelte'
import ThreatCard from './ThreatCard.svelte'

vi.mock('../lib/api.js', () => ({
  updateThreat: vi.fn().mockResolvedValue({}),
}))

// link action from svelte-spa-router is a DOM action — stub it so tests
// don't depend on a router context.
vi.mock('svelte-spa-router', () => ({
  link: () => ({ destroy: () => {} }),
  push: vi.fn(),
}))

const baseThreat = {
  id: 'threat-1',
  name: 'SQL Injection via login form',
  description: 'Unsanitised input allows direct SQL execution.',
  stride_category: 'Tampering',
  status: 'pending',
  target: 'Database',
  impact: 'High',
  likelihood: 'Medium',
  mitigations: JSON.stringify(['Use parameterised queries', 'Input validation']),
}

describe('ThreatCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders threat name and description', () => {
    render(ThreatCard, { props: { threat: baseThreat } })
    expect(screen.getByText('SQL Injection via login form')).toBeInTheDocument()
    expect(screen.getByText('Unsanitised input allows direct SQL execution.')).toBeInTheDocument()
  })

  it('renders STRIDE category badge', () => {
    render(ThreatCard, { props: { threat: baseThreat } })
    expect(screen.getByText('Tampering')).toBeInTheDocument()
  })

  it('renders MAESTRO category when stride_category is absent', () => {
    const maestroThreat = { ...baseThreat, stride_category: undefined, maestro_category: 'Model Theft' }
    render(ThreatCard, { props: { threat: maestroThreat } })
    expect(screen.getByText('Model Theft')).toBeInTheDocument()
  })

  it('renders status badge', () => {
    render(ThreatCard, { props: { threat: baseThreat } })
    expect(screen.getByText('pending')).toBeInTheDocument()
  })

  it('renders target and impact', () => {
    render(ThreatCard, { props: { threat: baseThreat } })
    expect(screen.getByText('Database')).toBeInTheDocument()
    expect(screen.getByText('High')).toBeInTheDocument()
  })

  it('renders mitigations from JSON string', () => {
    render(ThreatCard, { props: { threat: baseThreat } })
    expect(screen.getByText('Use parameterised queries')).toBeInTheDocument()
    expect(screen.getByText('Input validation')).toBeInTheDocument()
  })

  it('renders mitigations from array directly', () => {
    const threat = { ...baseThreat, mitigations: ['Rate limiting', 'WAF'] }
    render(ThreatCard, { props: { threat } })
    expect(screen.getByText('Rate limiting')).toBeInTheDocument()
    expect(screen.getByText('WAF')).toBeInTheDocument()
  })

  it('shows Approve button when status is pending', () => {
    render(ThreatCard, { props: { threat: baseThreat } })
    expect(screen.getByText('Approve')).toBeInTheDocument()
  })

  it('hides Approve button when status is approved', () => {
    render(ThreatCard, { props: { threat: { ...baseThreat, status: 'approved' } } })
    expect(screen.queryByText('Approve')).toBeNull()
  })

  it('hides Reject button when status is rejected', () => {
    render(ThreatCard, { props: { threat: { ...baseThreat, status: 'rejected' } } })
    expect(screen.queryByText('Reject')).toBeNull()
  })

  it('shows attack tree and test case links only when approved', () => {
    const { queryByText } = render(ThreatCard, { props: { threat: baseThreat } })
    expect(queryByText('Attack tree →')).toBeNull()
    expect(queryByText('Test cases →')).toBeNull()
  })

  it('shows attack tree and test case links when approved', () => {
    render(ThreatCard, { props: { threat: { ...baseThreat, status: 'approved' } } })
    expect(screen.getByText('Attack tree →')).toBeInTheDocument()
    expect(screen.getByText('Test cases →')).toBeInTheDocument()
  })

  it('hides action buttons in readonly mode', () => {
    render(ThreatCard, { props: { threat: baseThreat, readonly: true } })
    expect(screen.queryByText('Approve')).toBeNull()
    expect(screen.queryByText('Reject')).toBeNull()
  })

  it('hides DREAD edit button in readonly mode', () => {
    render(ThreatCard, { props: { threat: baseThreat, readonly: true } })
    expect(screen.queryByText('DREAD')).toBeNull()
  })

  it('dispatches approve event when Approve is clicked', async () => {
    const { component } = render(ThreatCard, { props: { threat: baseThreat } })
    const handler = vi.fn()
    component.$on('approve', handler)
    await fireEvent.click(screen.getByText('Approve'))
    expect(handler).toHaveBeenCalledOnce()
    expect(handler.mock.calls[0][0].detail).toMatchObject({ id: 'threat-1' })
  })

  it('dispatches reject event when Reject is clicked', async () => {
    const { component } = render(ThreatCard, { props: { threat: baseThreat } })
    const handler = vi.fn()
    component.$on('reject', handler)
    await fireEvent.click(screen.getByText('Reject'))
    expect(handler).toHaveBeenCalledOnce()
  })

  it('opens DREAD edit form when DREAD button is clicked', async () => {
    render(ThreatCard, { props: { threat: baseThreat } })
    await fireEvent.click(screen.getByText('DREAD'))
    expect(screen.getByText('Edit DREAD scores')).toBeInTheDocument()
  })

  it('closes DREAD edit form on Cancel', async () => {
    render(ThreatCard, { props: { threat: baseThreat } })
    await fireEvent.click(screen.getByText('DREAD'))
    await fireEvent.click(screen.getByText('Cancel'))
    expect(screen.queryByText('Edit DREAD scores')).toBeNull()
  })
})
