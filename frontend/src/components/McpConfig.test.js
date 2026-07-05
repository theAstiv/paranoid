import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/svelte'
import McpConfig from './McpConfig.svelte'

describe('McpConfig', () => {
  it('renders the context-link heading', () => {
    render(McpConfig)
    expect(screen.getByText('Code Context via context-link')).toBeInTheDocument()
  })

  it('shows the CLI usage example including the --code flag', () => {
    render(McpConfig)
    expect(screen.getByText(/--code \/path\/to\/your\/repo/)).toBeInTheDocument()
  })

  it('shows the CONTEXT_LINK_BINARY environment variable example', () => {
    render(McpConfig)
    expect(screen.getByText('CONTEXT_LINK_BINARY=/path/to/context-link')).toBeInTheDocument()
  })
})
