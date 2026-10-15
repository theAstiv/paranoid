import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/svelte'
import MaestroCoverage from './MaestroCoverage.svelte'

const coverage = {
  assessed: true,
  categories: [
    { category: 'LLM Security', status: 'covered', threats: 3 },
    { category: 'Privacy', status: 'not_covered', threats: 0 },
    { category: 'Reinforcement Learning', status: 'na', threats: 0 },
  ],
}

describe('MaestroCoverage', () => {
  it('renders nothing without coverage data', () => {
    const { container } = render(MaestroCoverage, { props: { coverage: null } })
    expect(container.querySelector('[data-testid="maestro-coverage"]')).toBeNull()
  })

  it('shows covered with a count, not covered, and N/A with its reason', () => {
    render(MaestroCoverage, { props: { coverage } })
    expect(screen.getByTestId('maestro-LLM Security')).toHaveTextContent('Covered')
    expect(screen.getByTestId('maestro-LLM Security')).toHaveTextContent('3')
    expect(screen.getByTestId('maestro-Privacy')).toHaveTextContent('Not covered')
    expect(screen.getByTestId('maestro-Reinforcement Learning')).toHaveTextContent('N/A')
    expect(screen.getByTestId('maestro-Reinforcement Learning')).toHaveTextContent(
      'no component in the model',
    )
  })

  it('says not assessed, never N/A, when no asset could be tagged', () => {
    const untagged = {
      assessed: false,
      categories: [{ category: 'Privacy', status: 'not_assessed', threats: 0 }],
    }
    render(MaestroCoverage, { props: { coverage: untagged } })
    expect(screen.getByTestId('maestro-Privacy')).toHaveTextContent('Not assessed')
    expect(screen.queryByText(/N\/A/)).toBeNull()
  })
})
