import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/svelte'
import CvssBadge from './CvssBadge.svelte'

const sseShape = {
  cvss: {
    attack_vector: 'N',
    attack_complexity: 'L',
    privileges_required: 'N',
    user_interaction: 'N',
    scope: 'U',
    confidentiality: 'H',
    integrity: 'H',
    availability: 'H',
  },
  cvss_score: 9.8,
  cvss_severity: 'critical',
}

const dbShape = {
  cvss_vector: 'AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H',
  cvss_score: 9.8,
  cvss_severity: 'critical',
}

describe('CvssBadge', () => {
  it('renders nothing when threat is null', () => {
    const { container } = render(CvssBadge, { props: { threat: null } })
    expect(container.querySelector('button')).toBeNull()
  })

  it('renders nothing when threat has no CVSS score', () => {
    const { container } = render(CvssBadge, { props: { threat: { name: 'No score' } } })
    expect(container.querySelector('button')).toBeNull()
  })

  it('shows the score from SSE (nested cvss) shape', () => {
    render(CvssBadge, { props: { threat: sseShape } })
    expect(screen.getByRole('button', { name: /CVSS 9.8/ })).toBeInTheDocument()
  })

  it('shows the score from DB/API (flat cvss_vector) shape', () => {
    render(CvssBadge, { props: { threat: dbShape } })
    expect(screen.getByRole('button', { name: /CVSS 9.8/ })).toBeInTheDocument()
  })

  it('formats a whole-number score with one decimal place', () => {
    // JSON round-trips 7.0 as the JS number 7 — the badge must still read "7.0".
    const wholeNumberScore = { cvss_vector: 'AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:N', cvss_score: 7, cvss_severity: 'high' }
    render(CvssBadge, { props: { threat: wholeNumberScore } })
    expect(screen.getByRole('button', { name: 'CVSS 7.0' })).toBeInTheDocument()
  })

  it('uses red chip class for critical score', () => {
    render(CvssBadge, { props: { threat: dbShape } })
    const btn = screen.getByRole('button', { name: /CVSS/ })
    expect(btn.className).toContain('chip-red')
  })

  it('uses green chip class for low score', () => {
    const low = { cvss_score: 2.0, cvss_severity: 'low', cvss_vector: 'AV:P/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N' }
    render(CvssBadge, { props: { threat: low } })
    const btn = screen.getByRole('button', { name: /CVSS/ })
    expect(btn.className).toContain('chip-green')
  })

  it('expands to show the 8-metric breakdown, parsed from the vector string', async () => {
    render(CvssBadge, { props: { threat: dbShape } })
    await fireEvent.click(screen.getByRole('button', { name: /CVSS/ }))
    expect(screen.getByText('Attack Vector')).toBeInTheDocument()
    expect(screen.getByText('Network')).toBeInTheDocument()
    expect(screen.getByText('critical', { exact: false })).toBeInTheDocument()
  })

  it('expands to show the 8-metric breakdown from the nested cvss object', async () => {
    render(CvssBadge, { props: { threat: sseShape } })
    await fireEvent.click(screen.getByRole('button', { name: /CVSS/ }))
    expect(screen.getByText('Privileges Required')).toBeInTheDocument()
    expect(screen.getAllByText('None').length).toBeGreaterThan(0)
  })
})
