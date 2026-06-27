<script>
  import { createEventDispatcher } from 'svelte'

  /** @type {string[]} step labels */
  export let steps = []
  /** @type {number} 0-based current step index */
  export let currentStep = 0
  /** @type {boolean} disable the Next/Submit button */
  export let nextDisabled = false
  /** @type {boolean} show loading state on submit button */
  export let submitting = false

  const dispatch = createEventDispatcher()

  $: isLast = currentStep === steps.length - 1
  $: isFirst = currentStep === 0
</script>

<div class="card overflow-hidden">
  <!-- Step rail -->
  <div class="border-b border-c-border px-6 py-4 overflow-x-auto">
    <div class="flex items-center gap-2 flex-nowrap min-w-max">
      {#each steps as label, i}
        <div class="flex items-center gap-2 flex-shrink-0">
          <div class="flex items-center justify-center w-6 h-6 rounded-panel text-xs font-semibold flex-shrink-0
            {i < currentStep
              ? 'bg-c-accent/20 text-c-accent border border-c-accent/40'
              : i === currentStep
              ? 'bg-c-accent text-[#04141A]'
              : 'bg-c-well text-c-faint border border-c-border'}">
            {#if i < currentStep}
              <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>
            {:else}
              {i + 1}
            {/if}
          </div>
          <span class="text-xs font-medium whitespace-nowrap hidden sm:block
            {i === currentStep ? 'text-c-text' : i < currentStep ? 'text-c-accent' : 'text-c-faint'}">
            {label}
          </span>
        </div>
        {#if i < steps.length - 1}
          <div class="h-px w-8 flex-shrink-0 {i < currentStep ? 'bg-c-accent/30' : 'bg-c-border'}"></div>
        {/if}
      {/each}
    </div>
  </div>

  <!-- Step content -->
  <div class="p-6">
    <slot />
  </div>

  <!-- Navigation -->
  <div class="border-t border-c-border px-6 py-4 flex justify-between">
    <button
      type="button"
      on:click={() => dispatch('back')}
      disabled={isFirst}
      class="px-4 py-2 text-sm font-medium text-c-muted hover:text-c-text hover:bg-c-well rounded-panel disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
      Back
    </button>
    <button
      type="button"
      on:click={() => isLast ? dispatch('submit') : dispatch('next')}
      disabled={nextDisabled || submitting}
      class="btn-primary disabled:opacity-50 disabled:cursor-not-allowed disabled:shadow-none">
      {#if submitting}
        <div class="w-3.5 h-3.5 border-2 border-[#04141A] border-t-transparent rounded-full animate-spin-slow"></div>
      {/if}
      {isLast ? 'Create & Run' : 'Next'}
    </button>
  </div>
</div>
