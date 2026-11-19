import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/svelte'
import Wizard from './Wizard.svelte'

const steps = ['Model Details', 'Framework', 'Description', 'Review']

describe('Wizard', () => {
  it('renders all step labels', () => {
    render(Wizard, { props: { steps, currentStep: 0 } })
    for (const label of steps) {
      // The current step's label also heads the step content.
      expect(screen.getAllByText(label).length).toBeGreaterThan(0)
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

  it('calls onback when Back is clicked', async () => {
    const handler = vi.fn()
    render(Wizard, { props: { steps, currentStep: 1, onback: handler } })
    await fireEvent.click(screen.getByText('Back'))
    expect(handler).toHaveBeenCalledOnce()
  })

  it('calls onnext when Next is clicked on non-last step', async () => {
    const handler = vi.fn()
    render(Wizard, { props: { steps, currentStep: 0, onnext: handler } })
    await fireEvent.click(screen.getByText('Next'))
    expect(handler).toHaveBeenCalledOnce()
  })

  it('calls onsubmit when Create & Run is clicked on last step', async () => {
    const handler = vi.fn()
    render(Wizard, { props: { steps, currentStep: steps.length - 1, onsubmit: handler } })
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

  // BB-111: one button used to turn from Next into Create & Run under the focus,
  // so a second Enter on "Next" started the run.
  it('replaces Next with a different Create & Run button on the last step', async () => {
    const onsubmit = vi.fn()
    const { rerender } = render(Wizard, { props: { steps, currentStep: steps.length - 2, onsubmit } })
    const next = screen.getByText('Next')

    await rerender({ steps, currentStep: steps.length - 1, onsubmit })

    const run = screen.getByText('Create & Run')
    expect(run).not.toBe(next)
    expect(next.isConnected).toBe(false)
    expect(screen.queryByText('Next')).toBeNull()
    // The old button is gone, so a click (or Enter) that lands on it can't submit.
    await fireEvent.click(next)
    expect(onsubmit).not.toHaveBeenCalled()
  })

  it('moves the focus to the new step heading after a step change, not on the first render', async () => {
    const { rerender } = render(Wizard, { props: { steps, currentStep: 0 } })
    expect(document.activeElement).toBe(document.body)

    await rerender({ steps, currentStep: 1 })

    expect(document.activeElement.tagName).toBe('H2')
    expect(document.activeElement).toHaveTextContent('2/4Framework')
    // And again on Back.
    await rerender({ steps, currentStep: 0 })
    expect(document.activeElement).toHaveTextContent('1/4Model Details')
  })

  it('does not take the focus when the step stays the same', async () => {
    const { rerender } = render(Wizard, { props: { steps, currentStep: 1, nextDisabled: true } })
    const outside = document.createElement('input')
    document.body.appendChild(outside)
    outside.focus()

    await rerender({ steps, currentStep: 1, nextDisabled: false })

    expect(document.activeElement).toBe(outside)
    outside.remove()
  })
})
