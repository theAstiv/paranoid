import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/svelte'
import Dashboard from './Dashboard.svelte'

vi.mock('svelte-spa-router', () => ({
  link: () => ({ destroy: () => {} }),
}))

vi.mock('../lib/api.js', () => ({
  getProjectDashboard: vi.fn(),
}))

vi.mock('../lib/stores.js', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, notify: vi.fn() }
})

import { getProjectDashboard } from '../lib/api.js'
import { notify, currentProject } from '../lib/stores.js'

const fullData = {
  stats: { model_count: 4, open_threats: 10, pending_review: 2, member_count: 3, last_run_at: '2026-01-01T00:00:00.000Z' },
  severity: { critical: 1, high: 2, medium: 3, low: 4 },
  activity: [
    { id: 'a1', display_name: 'Alice A', username: 'alice', action: 'threat_status_changed', entity_type: 'threat', details: { title: 'SQLi' }, created_at: '2026-01-01T00:00:00.000Z' },
  ],
  assigned_to_you: [
    { id: 't1', model_id: 'm1', name: 'SQL Injection', model_title: 'Payments', dread_score: 8.5, stride_category: 'Tampering' },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  currentProject.set(null)
  getProjectDashboard.mockResolvedValue(fullData)
})

describe('Dashboard — project gating', () => {
  it('shows a message when no project is selected', () => {
    render(Dashboard)
    expect(screen.getByText('No project selected.')).toBeInTheDocument()
  })

  it('loads dashboard data once a project is set', async () => {
    currentProject.set({ id: 'p1', name: 'My Project' })
    render(Dashboard)
    await waitFor(() => expect(getProjectDashboard).toHaveBeenCalledWith('p1'))
  })

  it('notifies on load failure', async () => {
    getProjectDashboard.mockRejectedValue(new Error('boom'))
    currentProject.set({ id: 'p1', name: 'My Project' })
    render(Dashboard)
    await waitFor(() => expect(notify).toHaveBeenCalledWith('error', expect.stringContaining('boom')))
  })
})

describe('Dashboard — header', () => {
  it('shows the project name, role, member count, and last run', async () => {
    currentProject.set({ id: 'p1', name: 'My Project', member_role: 'owner' })
    render(Dashboard)
    await waitFor(() => expect(screen.getByText('My Project')).toBeInTheDocument())
    expect(screen.getByText(/owner/)).toBeInTheDocument()
    expect(screen.getByText(/3 members/)).toBeInTheDocument()
    expect(screen.getByText(/last run/)).toBeInTheDocument()
  })
})

describe('Dashboard — stats and severity', () => {
  beforeEach(() => currentProject.set({ id: 'p1', name: 'My Project' }))

  it('renders the stat cards', async () => {
    render(Dashboard)
    await waitFor(() => expect(screen.getByText('Threat models')).toBeInTheDocument())
    expect(screen.getByText('4')).toBeInTheDocument()
    expect(screen.getByText('10')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
  })

  it('renders the severity breakdown with per-severity counts', async () => {
    render(Dashboard)
    await waitFor(() => expect(screen.getByText('10 total')).toBeInTheDocument())
    expect(screen.getByText('Critical 1')).toBeInTheDocument()
    expect(screen.getByText('High 2')).toBeInTheDocument()
    expect(screen.getByText('Medium 3')).toBeInTheDocument()
    expect(screen.getByText('Low 4')).toBeInTheDocument()
  })

  it('shows a "no open threats" message when severity totals are zero', async () => {
    getProjectDashboard.mockResolvedValue({
      ...fullData,
      severity: { critical: 0, high: 0, medium: 0, low: 0 },
    })
    render(Dashboard)
    await waitFor(() => expect(screen.getByText('No open threats.')).toBeInTheDocument())
  })
})

describe('Dashboard — activity feed', () => {
  beforeEach(() => currentProject.set({ id: 'p1', name: 'My Project' }))

  it('renders an activity line with actor and action', async () => {
    render(Dashboard)
    await waitFor(() => expect(screen.getByText(/threat status changed SQLi/)).toBeInTheDocument())
  })

  it('shows an empty state when there is no activity', async () => {
    getProjectDashboard.mockResolvedValue({ ...fullData, activity: [] })
    render(Dashboard)
    await waitFor(() => expect(screen.getByText('No activity yet.')).toBeInTheDocument())
  })
})

describe('Dashboard — assigned to you', () => {
  beforeEach(() => currentProject.set({ id: 'p1', name: 'My Project' }))

  it('renders assigned threats with DREAD score and category', async () => {
    render(Dashboard)
    await waitFor(() => expect(screen.getByText('SQL Injection')).toBeInTheDocument())
    expect(screen.getByText('8.5')).toBeInTheDocument()
    expect(screen.getByText('Payments')).toBeInTheDocument()
    expect(screen.getByText('Tampering')).toBeInTheDocument()
  })

  it('links to the threat review page', async () => {
    const { container } = render(Dashboard)
    await waitFor(() => expect(screen.getByText('SQL Injection')).toBeInTheDocument())
    const link = container.querySelector('a[href="#/models/m1/review"]')
    expect(link).not.toBeNull()
  })

  it('shows an empty state when nothing is assigned', async () => {
    getProjectDashboard.mockResolvedValue({ ...fullData, assigned_to_you: [] })
    render(Dashboard)
    await waitFor(() => expect(screen.getByText('Nothing assigned to you.')).toBeInTheDocument())
  })

  it('shows a dash when a threat has no DREAD score', async () => {
    getProjectDashboard.mockResolvedValue({
      ...fullData,
      assigned_to_you: [{ id: 't2', model_id: 'm2', name: 'No score threat', model_title: 'X', dread_score: null }],
    })
    render(Dashboard)
    await waitFor(() => expect(screen.getByText('No score threat')).toBeInTheDocument())
    expect(screen.getByText('—')).toBeInTheDocument()
  })
})
