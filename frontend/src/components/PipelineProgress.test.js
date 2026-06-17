import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/svelte'
import PipelineProgress from './PipelineProgress.svelte'

// Helper: build a minimal SSE event object
function evt(step, status, extras = {}) {
  return { step, status, message: `${step} ${status}`, timestamp: Date.now(), ...extras }
}

describe('PipelineProgress', () => {
  it('shows "No events yet." when events is empty and not running', () => {
    render(PipelineProgress, { props: { events: [], running: false } })
    expect(screen.getByText('No events yet.')).toBeInTheDocument()
  })

  it('shows "Starting pipeline…" when events is empty and running', () => {
    render(PipelineProgress, { props: { events: [], running: true } })
    expect(screen.getByText('Starting pipeline…')).toBeInTheDocument()
  })

  it('shows 0% progress when no events', () => {
    render(PipelineProgress, { props: { events: [], running: false } })
    expect(screen.getByText('0%')).toBeInTheDocument()
  })

  it('shows 10% after summarize completes', () => {
    const events = [evt('summarize', 'completed')]
    render(PipelineProgress, { props: { events, running: true } })
    expect(screen.getByText('10%')).toBeInTheDocument()
  })

  it('shows 25% after extract_assets completes', () => {
    const events = [
      evt('summarize', 'completed'),
      evt('extract_assets', 'completed'),
    ]
    render(PipelineProgress, { props: { events, running: true } })
    expect(screen.getByText('25%')).toBeInTheDocument()
  })

  it('shows 40% after extract_flows completes', () => {
    const events = [
      evt('extract_flows', 'completed'),
    ]
    render(PipelineProgress, { props: { events, running: true } })
    expect(screen.getByText('40%')).toBeInTheDocument()
  })

  it('shows 100% when complete event arrives', () => {
    const events = [evt('complete', 'completed')]
    render(PipelineProgress, { props: { events, running: false } })
    expect(screen.getByText('100%')).toBeInTheDocument()
  })

  it('shows 90% after rule_engine completes', () => {
    const events = [evt('rule_engine', 'completed')]
    render(PipelineProgress, { props: { events, running: true } })
    expect(screen.getByText('90%')).toBeInTheDocument()
  })

  it('displays cumulative threat count', () => {
    const events = [
      evt('generate_threats', 'completed', {
        iteration: 1,
        data: { cumulative_threat_count: 12 },
      }),
    ]
    render(PipelineProgress, { props: { events, running: true, totalIterations: 3 } })
    expect(screen.getByText(/12 threats found/)).toBeInTheDocument()
  })

  it('shows iteration label while running', () => {
    const events = [evt('generate_threats', 'started', { iteration: 2 })]
    render(PipelineProgress, { props: { events, running: true, totalIterations: 3 } })
    expect(screen.getByText('Iteration 2 / 3')).toBeInTheDocument()
  })

  it('shows Complete label when not running', () => {
    render(PipelineProgress, { props: { events: [], running: false } })
    expect(screen.getByText('Complete')).toBeInTheDocument()
  })

  it('renders event log entries with step labels', () => {
    const events = [evt('extract_assets', 'completed')]
    render(PipelineProgress, { props: { events, running: false } })
    expect(screen.getByText('Extract Assets')).toBeInTheDocument()
  })

  it('shows gap_satisfied stopped reason banner', () => {
    render(PipelineProgress, { props: { events: [], stoppedReason: 'gap_satisfied' } })
    expect(screen.getByText('Thorough coverage achieved')).toBeInTheDocument()
  })

  it('shows timeout stopped reason banner', () => {
    render(PipelineProgress, { props: { events: [], stoppedReason: 'timeout' } })
    expect(screen.getByText('Pipeline timed out')).toBeInTheDocument()
  })

  it('shows provider_offline stopped reason banner', () => {
    render(PipelineProgress, { props: { events: [], stoppedReason: 'provider_offline' } })
    expect(screen.getByText('Provider offline — rule engine only results')).toBeInTheDocument()
  })

  it('shows max_iterations stopped reason banner', () => {
    render(PipelineProgress, { props: { events: [], stoppedReason: 'max_iterations' } })
    expect(screen.getByText('Max iterations reached')).toBeInTheDocument()
  })

  it('detects dual-framework and computes progress proportionally', () => {
    // 2 completed generate_threats on iteration 1 = dual-framework detected.
    // Use distinct timestamps so the keyed {#each} in the template doesn't
    // throw a duplicate-key error (key = timestamp + step + status).
    // With totalIterations=2, expectedTotal=4, done=2 → 40 + (2/4)*40 = 60%
    const events = [
      evt('generate_threats', 'completed', { iteration: 1, timestamp: 1000 }),
      evt('generate_threats', 'completed', { iteration: 1, timestamp: 1001 }),
    ]
    render(PipelineProgress, { props: { events, running: true, totalIterations: 2 } })
    expect(screen.getByText('60%')).toBeInTheDocument()
  })

  it('renders unknown step names verbatim', () => {
    const events = [evt('custom_step', 'info')]
    render(PipelineProgress, { props: { events, running: false } })
    expect(screen.getByText('custom_step')).toBeInTheDocument()
  })
})
