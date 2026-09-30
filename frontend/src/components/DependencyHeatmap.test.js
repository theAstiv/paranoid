import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/svelte'
import DependencyHeatmap from './DependencyHeatmap.svelte'

function scan(overrides = {}) {
  return {
    id: 'scan-1',
    package: 'lodash',
    version: '4.17.21',
    source_mode: 'npm',
    analysis: {
      ref: { name: 'lodash', version: '4.17.21' },
      npm_profile: {
        status: 'ok',
        evidence: [
          { category: 'dynamic_code', path_class: 'shipped', file: 'lib/index.js', line: 12, snippet: 'eval(x)', rule_id: 'js-eval' },
        ],
        install_hooks: [],
      },
      github_profile: null,
      drift: null,
      error: null,
    },
    ...overrides,
  }
}

describe('DependencyHeatmap', () => {
  it('renders an empty-state message when there are no scans', () => {
    render(DependencyHeatmap, { props: { scans: [] } })
    expect(screen.getByText('No dependency scans for this model.')).toBeInTheDocument()
  })

  it('renders a row per package with its name and version', () => {
    render(DependencyHeatmap, { props: { scans: [scan()] } })
    expect(screen.getByText('lodash@4.17.21')).toBeInTheDocument()
  })

  it('renders many packages as separate rows', () => {
    const scans = [
      scan({ id: 'scan-1', package: 'lodash', version: '4.17.21' }),
      scan({ id: 'scan-2', package: 'axios', version: '1.6.0' }),
      scan({ id: 'scan-3', package: 'express', version: '4.19.2' }),
    ]
    render(DependencyHeatmap, { props: { scans } })
    expect(screen.getByText('lodash@4.17.21')).toBeInTheDocument()
    expect(screen.getByText('axios@1.6.0')).toBeInTheDocument()
    expect(screen.getByText('express@4.19.2')).toBeInTheDocument()
  })

  it('shows a flag chip for a drift signal', () => {
    const s = scan({ analysis: { ...scan().analysis, drift: { signal: true, status: 'compared' } } })
    render(DependencyHeatmap, { props: { scans: [s] } })
    expect(screen.getByText('drift')).toBeInTheDocument()
  })

  it('shows a flag chip for a non-ok scan status (e.g. a skipped package)', () => {
    const s = scan({ analysis: { ...scan().analysis, npm_profile: { ...scan().analysis.npm_profile, status: 'semgrep_timeout' } } })
    render(DependencyHeatmap, { props: { scans: [s] } })
    expect(screen.getByText('semgrep_timeout')).toBeInTheDocument()
  })

  it('expands a row on click to show evidence file:line and snippet', async () => {
    render(DependencyHeatmap, { props: { scans: [scan()] } })
    expect(screen.queryByText('lib/index.js:12')).toBeNull()
    await fireEvent.click(screen.getByText('lodash@4.17.21'))
    expect(screen.getByText('lib/index.js:12')).toBeInTheDocument()
    expect(screen.getByText('eval(x)')).toBeInTheDocument()
  })

  it('shows the skip error for a package that failed to resolve', async () => {
    const s = scan({ analysis: { ref: { name: 'left-pad', version: '1.0.0' }, error: 'no resolvable version' } })
    render(DependencyHeatmap, { props: { scans: [s] } })
    await fireEvent.click(screen.getByText('lodash@4.17.21'))
    expect(screen.getByText('Skipped: no resolvable version')).toBeInTheDocument()
  })

  it('omits the dangling "@" for a package that was never resolved to a version', () => {
    const s = scan({ package: 'left-pad', version: '', analysis: { ref: { name: 'left-pad', version: '' }, error: 'no resolvable version' } })
    render(DependencyHeatmap, { props: { scans: [s] } })
    expect(screen.getByText('left-pad')).toBeInTheDocument()
    expect(screen.queryByText('left-pad@')).toBeNull()
  })

  it('labels evidence with its source (npm vs github)', async () => {
    render(DependencyHeatmap, { props: { scans: [scan()] } })
    await fireEvent.click(screen.getByText('lodash@4.17.21'))
    expect(screen.getByText('npm')).toBeInTheDocument()
  })

  it('caps evidence at 20 rows and shows an overflow count', async () => {
    const manyEvidence = Array.from({ length: 25 }, (_, i) => ({
      category: 'network', path_class: 'shipped', file: `lib/f${i}.js`, line: i, snippet: `call${i}()`,
    }))
    const s = scan({ analysis: { ...scan().analysis, npm_profile: { status: 'ok', evidence: manyEvidence, install_hooks: [] } } })
    render(DependencyHeatmap, { props: { scans: [s] } })
    await fireEvent.click(screen.getByText('lodash@4.17.21'))
    expect(screen.getByText('lib/f0.js:0')).toBeInTheDocument()
    expect(screen.queryByText('lib/f24.js:24')).toBeNull()
    expect(screen.getByText('+5 more')).toBeInTheDocument()
  })

  it('shows drift signal categories and affected files when drift.signal is true', async () => {
    const s = scan({
      analysis: {
        ...scan().analysis,
        drift: {
          signal: true,
          status: 'compared',
          signal_categories: ['dynamic_code'],
          signal_files: { 'lib/hidden.js': ['dynamic_code'] },
        },
      },
    })
    render(DependencyHeatmap, { props: { scans: [s] } })
    await fireEvent.click(screen.getByText('lodash@4.17.21'))
    expect(screen.getByText(/Signal: novel dynamic_code/)).toBeInTheDocument()
    expect(screen.getByText(/lib\/hidden\.js: dynamic_code/)).toBeInTheDocument()
  })

  it('shows a name-mismatch signal even when there are no signal categories', async () => {
    const s = scan({
      analysis: {
        ...scan().analysis,
        drift: { signal: true, status: 'compared', tarball_declared_name_mismatch: 'not-lodash' },
      },
    })
    render(DependencyHeatmap, { props: { scans: [s] } })
    await fireEvent.click(screen.getByText('lodash@4.17.21'))
    expect(screen.getByText(/declares name "not-lodash"/)).toBeInTheDocument()
    expect(screen.queryByText(/Signal: novel/)).toBeNull()
  })

  it('shows unscanned-reachable-files signal even when there are no signal categories', async () => {
    const s = scan({
      analysis: {
        ...scan().analysis,
        drift: { signal: true, status: 'compared', unscanned_reachable_files: ['lib/weird.xyz'] },
      },
    })
    render(DependencyHeatmap, { props: { scans: [s] } })
    await fireEvent.click(screen.getByText('lodash@4.17.21'))
    expect(screen.getByText(/1 reachable file never scanned/)).toBeInTheDocument()
    expect(screen.getByText('lib/weird.xyz')).toBeInTheDocument()
    expect(screen.queryByText(/Signal: novel/)).toBeNull()
  })

  it('shows explained_by_sourcemap and explained_by_build drift buckets', async () => {
    const s = scan({
      analysis: {
        ...scan().analysis,
        drift: {
          signal: false,
          status: 'compared',
          explained_by_sourcemap: ['a.js.map'],
          explained_by_build: ['dist/b.js'],
        },
      },
    })
    render(DependencyHeatmap, { props: { scans: [s] } })
    await fireEvent.click(screen.getByText('lodash@4.17.21'))
    expect(screen.getByText('explained_by_sourcemap: 1 file')).toBeInTheDocument()
    expect(screen.getByText('explained_by_build: 1 file')).toBeInTheDocument()
  })

  it('toggles the expanded row via the keyboard (Enter)', async () => {
    render(DependencyHeatmap, { props: { scans: [scan()] } })
    const row = screen.getByText('lodash@4.17.21').closest('tr')
    expect(screen.queryByText('lib/index.js:12')).toBeNull()
    await fireEvent.keyDown(row, { key: 'Enter' })
    expect(screen.getByText('lib/index.js:12')).toBeInTheDocument()
  })
})
