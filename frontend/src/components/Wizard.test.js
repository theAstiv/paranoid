import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/svelte'
import Wizard from './Wizard.svelte'

const steps = ['Model Details', 'Framework', 'Description', 'Review']

describe('Wizard', () => {
  it('renders all step labels', () => {
    render(Wizard, { props: { steps, currentStep: 0 } })
    for (const label of steps) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('shows step numbers for future steps', () => {
    render(Wizard, { props: { steps, currentStep: 0 } })
    // Steps 2, 3, 4 are future (indices 1, 2, 3)
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('4')).toBeInTheDocument()
  })

  it('shows Next button on non-last step', () => {
    render(Wizard, { props: { steps, currentStep: 0 } })
    expect(screen.getByText('Next')).toBeInTheDocument()
  })

  it('shows "Create & Run" on the last step', () => {
    render(Wizard, { props: { steps, currentStep: steps.length - 1 } })
    expect(screen.getByText('Create & Run')).toBeInTheDocument()
  })

  it('Back button is disabled on the first step', () => {
    render(Wizard, { props: { steps, currentStep: 0 } })
    const backBtn = screen.getByText('Back')
    expect(backBtn).toBeDisabled()
  })

  it('Back button is enabled on non-first steps', () => {
    render(Wizard, { props: { steps, currentStep: 2 } })
    const backBtn = screen.getByText('Back')
    expect(backBtn).not.toBeDisabled()
  })

  it('Next button is disabled when nextDisabled is true', () => {
    render(Wizard, { props: { steps, currentStep: 0, nextDisabled: true } })
    expect(screen.getByText('Next')).toBeDisabled()
  })

  it('Next button is disabled when submitting is true', () => {
    render(Wizard, { props: { steps, currentStep: steps.length - 1, submitting: true } })
    expect(screen.getByText('Create & Run')).toBeDisabled()
  })

  it('dispatches back event when Back is clicked', async () => {
    const { component } = render(Wizard, { props: { steps, currentStep: 1 } })
    const handler = vi.fn()
    component.$on('back', handler)
    await fireEvent.click(screen.getByText('Back'))
    expect(handler).toHaveBeenCalledOnce()
  })

  it('dispatches next event when Next is clicked on non-last step', async () => {
    const { component } = render(Wizard, { props: { steps, currentStep: 0 } })
    const handler = vi.fn()
    component.$on('next', handler)
    await fireEvent.click(screen.getByText('Next'))
    expect(handler).toHaveBeenCalledOnce()
  })

  it('dispatches submit event when Create & Run is clicked on last step', async () => {
    const { component } = render(Wizard, { props: { steps, currentStep: steps.length - 1 } })
    const handler = vi.fn()
    component.$on('submit', handler)
    await fireEvent.click(screen.getByText('Create & Run'))
    expect(handler).toHaveBeenCalledOnce()
  })

  it('renders slot content', () => {
    // Wizard uses a default slot — verify the slot region exists
    const { container } = render(Wizard, { props: { steps, currentStep: 0 } })
    // The p.6 slot div should exist
    const contentDiv = container.querySelector('.p-6')
    expect(contentDiv).not.toBeNull()
  })
})
