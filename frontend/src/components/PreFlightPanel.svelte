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

  const SEVERITY_BADGE = {
    error:   { bg: 'bg-red-100 text-red-700',    label: 'error' },
    warning: { bg: 'bg-yellow-100 text-yellow-700', label: 'warn'  },
    info:    { bg: 'bg-blue-100 text-blue-700',   label: 'info'  },
  }
</script>

<div class="rounded-lg border text-sm transition-colors
  {errors.length   ? 'border-red-200 bg-red-50'     :
   warnings.length ? 'border-yellow-200 bg-yellow-50' :
   loading         ? 'border-slate-200 bg-slate-50'  :
                     'border-green-200 bg-green-50'}">

  <!-- Header row -->
  <button
    type="button"
    on:click={() => open = !open}
    class="w-full flex items-center justify-between px-3 py-2.5 text-left">
    <span class="flex items-center gap-2 font-medium
      {errors.length   ? 'text-red-800'     :
       warnings.length ? 'text-yellow-800'  :
       loading         ? 'text-slate-600'   :
                         'text-green-800'}">

      {#if loading}
        <!-- Spinner -->
        <span class="w-4 h-4 border-2 border-slate-400 border-t-transparent rounded-full animate-spin flex-shrink-0"></span>
        Checking {title.toLowerCase()}…
      {:else if !hasGaps}
        <!-- Green tick -->
        <svg class="w-4 h-4 flex-shrink-0 text-green-600" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
        </svg>
        {title} looks good
      {:else}
        <!-- Warning/Error icon -->
        <svg class="w-4 h-4 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
        </svg>
        {title}: {gaps.length} gap{gaps.length !== 1 ? 's' : ''} detected
      {/if}
    </span>

    <!-- Chevron -->
    {#if !loading}
      <svg class="w-4 h-4 flex-shrink-0 text-slate-400 transition-transform {open ? 'rotate-180' : ''}"
           viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/>
      </svg>
    {/if}
  </button>

  <!-- Body -->
  {#if open && !loading && hasGaps}
    <ul class="border-t border-inherit divide-y divide-inherit px-3 py-1">
      {#each [...errors, ...warnings, ...infos] as gap (gap.field + gap.severity)}
        <li class="flex items-start gap-2 py-2">
          <span class="mt-0.5 px-1.5 py-0.5 rounded text-xs font-medium flex-shrink-0
            {SEVERITY_BADGE[gap.severity]?.bg ?? 'bg-slate-100 text-slate-600'}">
            {SEVERITY_BADGE[gap.severity]?.label ?? gap.severity}
          </span>
          <span class="text-slate-700 leading-snug">
            <span class="font-medium">{gap.field.replace(/_/g, ' ')}:</span>
            {gap.message}
          </span>
        </li>
      {/each}
    </ul>
  {/if}
</div>
