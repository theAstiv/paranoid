<script>
  /**
   * PreFlightPanel — shows description or assumptions coverage gaps.
   *
   * Props:
   *   title        string   e.g. "Description coverage" | "Assumptions coverage"
   *   loading      boolean  show spinner while the LLM analysis is in-flight
   *   gaps         Array<{ field: string, severity: 'error'|'warning'|'info', message: string }>
   *   collapsed    boolean  start collapsed (default false)
   */
  export let title = 'Coverage check'
  export let loading = false
  export let gaps = []
  export let collapsed = false

  let open = !collapsed

  $: errors   = gaps.filter(g => g.severity === 'error')
  $: warnings = gaps.filter(g => g.severity === 'warning')
  $: infos    = gaps.filter(g => g.severity === 'info')
  $: hasGaps  = gaps.length > 0

  const SEVERITY_CHIP = {
    error:   'chip-red',
    warning: 'chip-amber',
    info:    'chip-blue',
  }
</script>

<div class="rounded-panel border text-sm transition-colors
  {errors.length   ? 'border-c-critical/30 bg-c-critical/5'  :
   warnings.length ? 'border-c-high/30 bg-c-high/5'          :
   loading         ? 'border-c-border bg-c-panel'             :
                     'border-c-green/30 bg-c-green/5'}">

  <!-- Header row -->
  <button
    type="button"
    on:click={() => open = !open}
    class="w-full flex items-center justify-between px-3 py-2.5 text-left">
    <span class="flex items-center gap-2 font-medium
      {errors.length   ? 'text-c-critical'  :
       warnings.length ? 'text-c-high'      :
       loading         ? 'text-c-muted'     :
                         'text-c-green'}">

      {#if loading}
        <span class="w-3.5 h-3.5 border-2 border-c-muted border-t-transparent rounded-full animate-spin-slow flex-shrink-0"></span>
        Checking {title.toLowerCase()}…
      {:else if !hasGaps}
        <svg class="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
        </svg>
        {title} looks good
      {:else}
        <svg class="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
        </svg>
        {title}: {gaps.length} gap{gaps.length !== 1 ? 's' : ''} detected
      {/if}
    </span>

    {#if !loading}
      <svg class="w-3.5 h-3.5 flex-shrink-0 text-c-faint transition-transform {open ? 'rotate-180' : ''}"
           viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/>
      </svg>
    {/if}
  </button>

  {#if open && !loading && hasGaps}
    <ul class="border-t border-c-border divide-y divide-c-divider px-3 py-1">
      {#each [...errors, ...warnings, ...infos] as gap (gap.field + gap.severity)}
        <li class="flex items-start gap-2 py-2">
          <span class="mt-0.5 font-mono text-[10px] px-1.5 py-0.5 rounded-chip border flex-shrink-0
            {SEVERITY_CHIP[gap.severity] ?? 'chip-gray'}">
            {gap.severity}
          </span>
          <span class="text-c-muted leading-snug">
            <span class="font-medium text-c-text2">{gap.field.replace(/_/g, ' ')}:</span>
            {gap.message}
          </span>
        </li>
      {/each}
    </ul>
  {/if}
</div>
