import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/svelte'
import DreadBadge from './DreadBadge.svelte'

const sseShape = {
  dread: {
    damage: 8,
    reproducibility: 6,
    exploitability: 7,
    affected_users: 5,
    discoverability: 4,
  },
}

const dbShape = {
  dread_damage: 8,
  dread_reproducibility: 6,
  dread_exploitability: 7,
  dread_affected_users: 5,
  dread_discoverability: 4,
}

describe('DreadBadge', () => {
  it('renders nothing when threat is null', () => {
    const { container } = render(DreadBadge, { props: { threat: null } })
    expect(container.querySelector('button')).toBeNull()
  })

  it('renders nothing when threat has no DREAD data', () => {
    const { container } = render(DreadBadge, { props: { threat: { name: 'No scores' } } })
    expect(container.querySelector('button')).toBeNull()
  })

  it('shows averaged score from SSE shape', () => {
    render(DreadBadge, { props: { threat: sseShape } })
    // avg(8,6,7,5,4) = 30/5 = 6
    expect(screen.getByText(/DREAD: 6/)).toBeInTheDocument()
  })

  it('shows averaged score from DB/API shape', () => {
    render(DreadBadge, { props: { threat: dbShape } })
    expect(screen.getByText(/DREAD: 6/)).toBeInTheDocument()
  })

  it('uses yellow color class for mid-range score', () => {
    render(DreadBadge, { props: { threat: dbShape } })
    const btn = screen.getByText(/DREAD: 6/).closest('button')
    expect(btn.className).toContain('bg-yellow-100')
  })

  it('uses red color class for high score', () => {
    const highThreat = {
      dread_damage: 9,
      dread_reproducibility: 9,
      dread_exploitability: 9,
      dread_affected_users: 8,
      dread_discoverability: 8,
    }
    render(DreadBadge, { props: { threat: highThreat } })
    const btn = screen.getByText(/DREAD:/).closest('button')
    expect(btn.className).toContain('bg-red-100')
  })

  it('uses green color class for low score', () => {
    const lowThreat = {
      dread_damage: 1,
      dread_reproducibility: 2,
      dread_exploitability: 1,
      dread_affected_users: 2,
      dread_discoverability: 1,
    }
    render(DreadBadge, { props: { threat: lowThreat } })
    const btn = screen.getByText(/DREAD:/).closest('button')
    expect(btn.className).toContain('bg-green-100')
  })
})
