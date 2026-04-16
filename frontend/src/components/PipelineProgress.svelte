<script>
  /** @type {object[]} SSE PipelineEvent objects */
  export let events = []
  /** @type {boolean} */
  export let running = false
  /** @type {string} stopped_reason from the complete event */
  export let stoppedReason = ''
  /** @type {number} total iteration count configured */
  export let totalIterations = 3

  // Step → base progress percentage
  const STEP_PROGRESS = {
    summarize: 10,
    summarize_code: 15,
    extract_assets: 25,
    extract_flows: 40,
    generate_threats: 75,  // dynamically computed per iteration below
    gap_analysis: 60,
    iterate: 42,
    rule_engine: 90,
    complete: 100,
  }

  const STEP_LABELS = {
    summarize: 'Summarize',
    summarize_code: 'Analyze Code',
    extract_assets: 'Extract Assets',
    extract_flows: 'Extract Flows',
    generate_threats: 'Generate Threats',
    gap_analysis: 'Gap Analysis',
    iterate: 'Next Iteration',
    rule_engine: 'Rule Engine',
    complete: 'Complete',
  }

  const STATUS_ICON = {
    started: '⟳',
    completed: '✓',
    failed: '✗',
    info: 'ℹ',
  }

  const STATUS_COLOR = {
    started: 'text-blue-500',
    completed: 'text-green-600',
    failed: 'text-red-500',
    info: 'text-slate-400',
  }

  $: progress = computeProgress(events, totalIterations)
  $: cumulativeThreats = getCumulativeThreats(events)
  $: currentIteration = getCurrentIteration(events)

  /**
   * Compute progress percentage from SSE events.
   *
   * generate_threats fires once per iteration in single-framework mode, and
   * TWICE per iteration in dual-framework mode (STRIDE + MAESTRO, each with
   * their own started/completed pair). We detect dual-framework by spotting
   * multiple completed events on the same iteration number, then divide
   * the 40-80% range proportionally across all expected completions.
   */
  function computeProgress(evts, totalIter) {
    if (!evts.length) return 0

    // Terminal states: check for completed status on decisive steps
    if (evts.some(e => e.step === 'complete' && e.status === 'completed')) return 100
    if (evts.some(e => e.step === 'rule_engine' && e.status === 'completed')) return 90

    // Count completed generate_threats events and detect dual-framework
    const completedThreats = evts.filter(e => e.step === 'generate_threats' && e.status === 'completed')
    if (completedThreats.length > 0) {
      // Detect dual-framework: 2+ completions on the same iteration
      const perIter = {}
      for (const e of completedThreats) {
        const it = e.iteration ?? 1
        perIter[it] = (perIter[it] ?? 0) + 1
      }
      const isDual = Object.values(perIter).some(c => c > 1)
      const expectedTotal = isDual ? totalIter * 2 : totalIter
      const pct = 40 + Math.min(completedThreats.length / expectedTotal, 1) * 40
      return Math.round(pct)
    }

    // Pre-iteration steps — use completed status only
    if (evts.some(e => e.step === 'extract_flows' && e.status === 'completed')) return 40
    if (evts.some(e => e.step === 'extract_assets' && e.status === 'completed')) return 25
    if (evts.some(e => (e.step === 'summarize' || e.step === 'summarize_code') && e.status === 'completed')) return 10

    return 5  // pipeline started but nothing completed yet
  }

  function getCumulativeThreats(evts) {
    let count = 0
    for (const e of [...evts].reverse()) {
      if (e.step === 'generate_threats' && e.data?.cumulative_threat_count != null) {
        return e.data.cumulative_threat_count
      }
      if (e.step === 'complete' && e.data?.total_threats != null) {
        return e.data.total_threats
      }
    }
    return count
  }

  function getCurrentIteration(evts) {
    for (const e of [...evts].reverse()) {
      if (e.iteration != null) return e.iteration
    }
    return null
  }

  const STOPPED_REASON_CONFIG = {
    gap_satisfied: { color: 'bg-green-50 text-green-800 border-green-200', label: 'Thorough coverage achieved' },
    max_iterations: { color: 'bg-green-50 text-green-800 border-green-200', label: 'Max iterations reached' },
    timeout: { color: 'bg-yellow-50 text-yellow-800 border-yellow-200', label: 'Pipeline timed out' },
    provider_offline: { color: 'bg-red-50 text-red-800 border-red-200', label: 'Provider offline — rule engine only results' },
  }
</script>

<div class="space-y-4">
  <!-- Progress bar -->
  <div>
    <div class="flex justify-between text-xs text-slate-500 mb-1">
      <span>
        {#if running}
          {#if currentIteration != null}
            Iteration {currentIteration} / {totalIterations}
          {:else}
            Running…
          {/if}
        {:else}
          Complete
        {/if}
      </span>
      <span>{progress}%</span>
    </div>
    <div class="w-full bg-slate-100 rounded-full h-2">
      <div
        class="h-2 rounded-full transition-all duration-500 {running ? 'bg-indigo-500' : 'bg-green-500'}"
        style="width: {progress}%"
      ></div>
    </div>
  </div>

  <!-- Stats row -->
  {#if cumulativeThreats > 0}
    <div class="flex items-center gap-4 text-sm text-slate-600">
      <span class="flex items-center gap-1.5">
        <svg class="w-4 h-4 text-indigo-500" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
        {cumulativeThreats} threats found
      </span>
    </div>
  {/if}

  <!-- Stopped reason banner -->
  {#if stoppedReason && STOPPED_REASON_CONFIG[stoppedReason]}
    {@const cfg = STOPPED_REASON_CONFIG[stoppedReason]}
    <div class="flex items-center gap-2 px-3 py-2 rounded-md border text-sm font-medium {cfg.color}">
      {#if stoppedReason === 'provider_offline'}
        <svg class="w-4 h-4 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
      {:else}
        <svg class="w-4 h-4 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>
      {/if}
      {cfg.label}
    </div>
  {/if}

  <!-- Event log -->
  <div class="border border-slate-100 rounded-lg divide-y divide-slate-50 max-h-80 overflow-y-auto">
    {#if events.length === 0}
      <div class="px-4 py-6 text-center text-sm text-slate-400">
        {running ? 'Starting pipeline…' : 'No events yet.'}
      </div>
    {:else}
      {#each events as evt (evt.timestamp + evt.step + evt.status)}
        <div class="flex items-start gap-3 px-4 py-2 text-sm hover:bg-slate-50">
          <span class="font-mono flex-shrink-0 mt-0.5 {STATUS_COLOR[evt.status] ?? 'text-slate-400'}">
            {STATUS_ICON[evt.status] ?? '·'}
          </span>
          <div class="flex-1 min-w-0">
            <span class="font-medium text-slate-700">{STEP_LABELS[evt.step] ?? evt.step}</span>
            {#if evt.iteration != null}
              <span class="text-xs text-slate-400 ml-1">iter {evt.iteration}</span>
            {/if}
            <p class="text-slate-500 text-xs mt-0.5 leading-snug">{evt.message}</p>
          </div>
        </div>
      {/each}
    {/if}
  </div>
</div>
