import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import ThreatCard from './ThreatCard.svelte'

vi.mock('../lib/api.js', () => ({
  updateThreat: vi.fn().mockResolvedValue({}),
  scoreCvss: vi.fn().mockResolvedValue({ score: 9.8, severity: 'critical' }),
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

  it('renders a Dependency chip with package@version · file:line for dependency-sourced threats', () => {
    const threat = {
      ...baseThreat,
      source: 'dependency',
      dependency_ref: { package: 'lodash', version: '4.17.21', file: 'lib/index.js', line: 42, rule_id: 'js-dynamic-code' },
    }
    render(ThreatCard, { props: { threat } })
    expect(screen.getByText('Dependency')).toBeInTheDocument()
    expect(screen.getByText('lodash@4.17.21 · lib/index.js:42')).toBeInTheDocument()
  })

  it('omits the dependency label when dependency_ref is absent', () => {
    render(ThreatCard, { props: { threat: baseThreat } })
    expect(screen.queryByText(/@.*·/)).toBeNull()
  })

  it('renders a plain technique chip for a trusted (table) match', () => {
    const threat = {
      ...baseThreat,
      attack_techniques: [
        { id: 'T1195.002', name: 'Compromise Software Supply Chain', url: 'https://attack.mitre.org/techniques/T1195/002', confidence: 0.9, method: 'table' },
      ],
    }
    render(ThreatCard, { props: { threat } })
    const link = screen.getByRole('link', { name: 'T1195.002' })
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute('href', 'https://attack.mitre.org/techniques/T1195/002')
  })

  it('renders a plain technique chip for a trusted (seed) match', () => {
    const threat = {
      ...baseThreat,
      attack_techniques: [
        { id: 'T1078.004', name: 'Cloud Accounts', url: 'https://attack.mitre.org/techniques/T1078/004', confidence: 0.95, method: 'seed' },
      ],
    }
    render(ThreatCard, { props: { threat } })
    expect(screen.getByRole('link', { name: 'T1078.004' })).toBeInTheDocument()
  })

  it('marks an embedding-sourced match as suggested, not confirmed', () => {
    const threat = {
      ...baseThreat,
      attack_techniques: [{ id: 'AML.T0020', name: 'ML Training Data Poisoning', confidence: 0.6, method: 'embedding' }],
    }
    render(ThreatCard, { props: { threat } })
    const link = screen.getByRole('link', { name: 'AML.T0020 (suggested)' })
    expect(link).toHaveAttribute('href', 'https://atlas.mitre.org/techniques/AML.T0020')
    expect(link).toHaveAttribute('title', expect.stringContaining('suggested match'))
  })

  it('treats a missing method as suggested, not confirmed', () => {
    const threat = {
      ...baseThreat,
      attack_techniques: [{ id: 'AML.T0020', name: 'ML Training Data Poisoning', confidence: 0.6 }],
    }
    render(ThreatCard, { props: { threat } })
    expect(screen.getByRole('link', { name: 'AML.T0020 (suggested)' })).toBeInTheDocument()
  })

  it('renders no technique chip when attack_techniques is empty', () => {
    render(ThreatCard, { props: { threat: baseThreat } })
    expect(screen.queryByRole('link', { name: /^T\d|^AML\./ })).toBeNull()
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

  it('calls onapprove with the threat when Approve is clicked', async () => {
    const handler = vi.fn()
    render(ThreatCard, { props: { threat: baseThreat, onapprove: handler } })
    await fireEvent.click(screen.getByText('Approve'))
    expect(handler).toHaveBeenCalledOnce()
    expect(handler.mock.calls[0][0]).toMatchObject({ id: 'threat-1' })
  })

  it('calls onreject with the threat when Reject is clicked', async () => {
    const handler = vi.fn()
    render(ThreatCard, { props: { threat: baseThreat, onreject: handler } })
    await fireEvent.click(screen.getByText('Reject'))
    expect(handler).toHaveBeenCalledOnce()
    expect(handler.mock.calls[0][0]).toMatchObject({ id: 'threat-1' })
  })

  it('calls ondreadUpdated with the merged threat after saving DREAD scores', async () => {
    const handler = vi.fn()
    render(ThreatCard, { props: { threat: baseThreat, ondreadUpdated: handler } })
    await fireEvent.click(screen.getByText('DREAD'))

    const [damage] = screen.getAllByRole('spinbutton')
    await fireEvent.input(damage, { target: { value: '7' } })
    await fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(handler).toHaveBeenCalledOnce())
    // Props are read-only under runes — the card reports the merged record
    // upward instead of mutating its own prop.
    expect(handler.mock.calls[0][0]).toMatchObject({ id: 'threat-1', dread_damage: 7 })
  })

  it('does not call ondreadUpdated when a score is out of range', async () => {
    const handler = vi.fn()
    render(ThreatCard, { props: { threat: baseThreat, ondreadUpdated: handler } })
    await fireEvent.click(screen.getByText('DREAD'))

    const [damage] = screen.getAllByRole('spinbutton')
    await fireEvent.input(damage, { target: { value: '42' } })
    await fireEvent.click(screen.getByText('Save'))

    expect(await screen.findByText(/must be integers between 1 and 10/)).toBeInTheDocument()
    expect(handler).not.toHaveBeenCalled()
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

  it('hides CVSS edit button in readonly mode', () => {
    render(ThreatCard, { props: { threat: baseThreat, readonly: true } })
    expect(screen.queryByText('CVSS')).toBeNull()
  })

  it('opens CVSS edit form when CVSS button is clicked', async () => {
    render(ThreatCard, { props: { threat: baseThreat } })
    await fireEvent.click(screen.getByText('CVSS'))
    expect(screen.getByText('Edit CVSS v3.1 vector')).toBeInTheDocument()
  })

  it('closes CVSS edit form on Cancel', async () => {
    render(ThreatCard, { props: { threat: baseThreat } })
    await fireEvent.click(screen.getByText('CVSS'))
    await fireEvent.click(screen.getByText('Cancel'))
    expect(screen.queryByText('Edit CVSS v3.1 vector')).toBeNull()
  })

  it('previews a score immediately when the CVSS edit form opens', async () => {
    const { scoreCvss } = await import('../lib/api.js')
    render(ThreatCard, { props: { threat: baseThreat } })
    await fireEvent.click(screen.getByText('CVSS'))

    await waitFor(() => expect(scoreCvss).toHaveBeenCalledOnce())
    expect(await screen.findByText(/Score preview:/)).toBeInTheDocument()
  })

  it('calls scoreCvss again for a live preview when a dropdown changes', async () => {
    const { scoreCvss } = await import('../lib/api.js')
    render(ThreatCard, { props: { threat: baseThreat } })
    await fireEvent.click(screen.getByText('CVSS'))
    await waitFor(() => expect(scoreCvss).toHaveBeenCalledOnce())

    const [attackVector] = screen.getAllByRole('combobox')
    await fireEvent.change(attackVector, { target: { value: 'N' } })

    await waitFor(() => expect(scoreCvss).toHaveBeenCalledTimes(2))
    expect(await screen.findByText(/Score preview:/)).toBeInTheDocument()
  })

  const scoredThreat = {
    ...baseThreat,
    dread_damage: 8,
    dread_reproducibility: 6,
    dread_exploitability: 7,
    dread_affected_users: 5,
    dread_discoverability: 4,
    cvss_vector: 'AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H',
    cvss_score: 9.8,
    cvss_severity: 'critical',
  }

  it('shows only the DREAD badge/edit button when scoringMethod is dread', () => {
    render(ThreatCard, { props: { threat: scoredThreat, scoringMethod: 'dread' } })
    expect(screen.getByRole('button', { name: /DREAD 6/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /CVSS/ })).toBeNull()
    expect(screen.getByText('DREAD', { selector: 'button' })).toBeInTheDocument()
    expect(screen.queryByText('CVSS', { selector: 'button' })).toBeNull()
  })

  it('shows only the CVSS badge/edit button when scoringMethod is cvss', () => {
    render(ThreatCard, { props: { threat: scoredThreat, scoringMethod: 'cvss' } })
    expect(screen.queryByRole('button', { name: /DREAD 6/ })).toBeNull()
    expect(screen.getByRole('button', { name: /CVSS 9.8/ })).toBeInTheDocument()
    expect(screen.queryByText('DREAD', { selector: 'button' })).toBeNull()
    expect(screen.getByText('CVSS', { selector: 'button' })).toBeInTheDocument()
  })

  it('shows both badges/edit buttons when scoringMethod is both', () => {
    render(ThreatCard, { props: { threat: scoredThreat, scoringMethod: 'both' } })
    expect(screen.getByRole('button', { name: /DREAD 6/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /CVSS 9.8/ })).toBeInTheDocument()
  })

  it('defaults to showing both when scoringMethod is not passed', () => {
    render(ThreatCard, { props: { threat: scoredThreat } })
    expect(screen.getByRole('button', { name: /DREAD 6/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /CVSS 9.8/ })).toBeInTheDocument()
  })

  it('calls oncvssUpdated with the merged threat after saving a CVSS vector', async () => {
    const { updateThreat } = await import('../lib/api.js')
    updateThreat.mockResolvedValueOnce({
      id: 'threat-1',
      cvss_vector: 'AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H',
      cvss_score: 9.8,
      cvss_severity: 'critical',
    })
    const handler = vi.fn()
    render(ThreatCard, { props: { threat: baseThreat, oncvssUpdated: handler } })
    await fireEvent.click(screen.getByText('CVSS'))
    await fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(handler).toHaveBeenCalledOnce())
    expect(handler.mock.calls[0][0]).toMatchObject({ id: 'threat-1', cvss_score: 9.8 })
  })

  it('shows no Clear button when the threat has no CVSS vector yet', async () => {
    render(ThreatCard, { props: { threat: baseThreat } })
    await fireEvent.click(screen.getByText('CVSS'))
    expect(screen.queryByText('Clear')).toBeNull()
  })

  it('shows a Clear button for a threat that already has a CVSS vector', async () => {
    const existing = { ...baseThreat, cvss_vector: 'AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H', cvss_score: 9.8, cvss_severity: 'critical' }
    render(ThreatCard, { props: { threat: existing } })
    await fireEvent.click(screen.getByText('CVSS'))
    expect(screen.getByText('Clear')).toBeInTheDocument()
  })

  it('calls oncvssUpdated with a cleared threat when Clear is clicked', async () => {
    const { updateThreat } = await import('../lib/api.js')
    updateThreat.mockResolvedValueOnce({ id: 'threat-1', cvss_vector: null, cvss_score: null, cvss_severity: null })
    const existing = { ...baseThreat, cvss_vector: 'AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H', cvss_score: 9.8, cvss_severity: 'critical' }
    const handler = vi.fn()
    render(ThreatCard, { props: { threat: existing, oncvssUpdated: handler } })
    await fireEvent.click(screen.getByText('CVSS'))
    await fireEvent.click(screen.getByText('Clear'))

    await waitFor(() => expect(updateThreat).toHaveBeenCalledWith('threat-1', { cvss_vector: null }))
    expect(handler.mock.calls[0][0]).toMatchObject({ id: 'threat-1', cvss_vector: null })
  })

  it('formats a whole-number score preview with one decimal place', async () => {
    const { scoreCvss } = await import('../lib/api.js')
    scoreCvss.mockResolvedValueOnce({ score: 7, severity: 'high' })
    render(ThreatCard, { props: { threat: baseThreat } })
    await fireEvent.click(screen.getByText('CVSS'))

    expect(await screen.findByText('7.0')).toBeInTheDocument()
  })
})
