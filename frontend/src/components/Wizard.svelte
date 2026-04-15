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

<div class="bg-white rounded-xl border border-slate-200 overflow-hidden">
  <!-- Step indicator -->
  <div class="border-b border-slate-100 px-6 py-4">
    <div class="flex items-center gap-2">
      {#each steps as label, i}
        <div class="flex items-center gap-2">
          <div class="flex items-center justify-center w-6 h-6 rounded-full text-xs font-semibold flex-shrink-0
            {i < currentStep ? 'bg-indigo-600 text-white' : i === currentStep ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-400'}">
            {#if i < currentStep}
              <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>
            {:else}
              {i + 1}
            {/if}
          </div>
          <span class="text-xs font-medium hidden sm:block
            {i === currentStep ? 'text-slate-900' : i < currentStep ? 'text-indigo-600' : 'text-slate-400'}">
            {label}
          </span>
        </div>
        {#if i < steps.length - 1}
          <div class="flex-1 h-px {i < currentStep ? 'bg-indigo-300' : 'bg-slate-100'} min-w-4 max-w-12"></div>
        {/if}
      {/each}
    </div>
  </div>

  <!-- Step content -->
  <div class="p-6">
    <slot />
  </div>

  <!-- Navigation -->
  <div class="border-t border-slate-100 px-6 py-4 flex justify-between">
    <button
      type="button"
      on:click={() => dispatch('back')}
      disabled={isFirst}
      class="px-4 py-2 text-sm font-medium text-slate-600 rounded-md hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
      Back
    </button>
    <button
      type="button"
      on:click={() => isLast ? dispatch('submit') : dispatch('next')}
      disabled={nextDisabled || submitting}
      class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2">
      {#if submitting}
        <div class="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
      {/if}
      {isLast ? 'Create & Run' : 'Next'}
    </button>
  </div>
</div>
