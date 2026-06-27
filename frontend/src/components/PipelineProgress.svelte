<script>
  /** @type {object[]} SSE PipelineEvent objects */
  export let events = []
  /** @type {boolean} */
  export let running = false
  /** @type {string} stopped_reason from the complete event */
  export let stoppedReason = ''
  /** @type {number} total iteration count configured */
  export let totalIterations = 3

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
    started:   'text-c-blue',
    completed: 'text-c-green',
    failed:    'text-c-critical',
    info:      'text-c-faint',
  }

  $: progress = computeProgress(events, totalIterations)
  $: cumulativeThreats = getCumulativeThreats(events)
  $: currentIteration = getCurrentIteration(events)

  let codeDetailOpen = false

  function computeProgress(evts, totalIter) {
    if (!evts.length) return 0
    if (evts.some(e => e.step === 'complete' && e.status === 'completed')) return 100
    if (evts.some(e => e.step === 'rule_engine' && e.status === 'completed')) return 90

    const completedThreats = evts.filter(e => e.step === 'generate_threats' && e.status === 'completed')
    if (completedThreats.length > 0) {
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

    if (evts.some(e => e.step === 'extract_flows' && e.status === 'completed')) return 40
    if (evts.some(e => e.step === 'extract_assets' && e.status === 'completed')) return 25
    if (evts.some(e => (e.step === 'summarize' || e.step === 'summarize_code') && e.status === 'completed')) return 10

    return 5
  }

  function getCumulativeThreats(evts) {
    for (const e of [...evts].reverse()) {
      if (e.step === 'generate_threats' && e.data?.cumulative_threat_count != null) {
        return e.data.cumulative_threat_count
      }
      if (e.step === 'complete' && e.data?.total_threats != null) {
        return e.data.total_threats
      }
    }
    return 0
  }

  function getCurrentIteration(evts) {
    for (const e of [...evts].reverse()) {
      if (e.iteration != null) return e.iteration
    }
    return null
  }

  const STOPPED_REASON_CONFIG = {
    gap_satisfied:    { chip: 'chip-green',  label: 'Thorough coverage achieved' },
    max_iterations:   { chip: 'chip-green',  label: 'Max iterations reached' },
    timeout:          { chip: 'chip-amber',  label: 'Pipeline timed out' },
    provider_offline: { chip: 'chip-red',    label: 'Provider offline — rule engine only results' },
  }
</script>

<div class="space-y-4">
  <!-- Progress bar -->
  <div>
    <div class="flex justify-between font-mono text-[11px] text-c-muted mb-1.5">
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
    <div class="w-full bg-c-border rounded-full h-1.5 overflow-hidden">
      <div
        class="h-1.5 rounded-full transition-all duration-500 {running ? 'bg-c-accent' : 'bg-c-green'}"
        style="width: {progress}%"
      ></div>
    </div>
  </div>

  <!-- Stats row -->
  {#if cumulativeThreats > 0}
    <div class="flex items-center gap-1.5 text-sm text-c-muted">
      <svg class="w-3.5 h-3.5 text-c-accent" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
      <span class="font-mono">{cumulativeThreats} threats found</span>
    </div>
  {/if}

  <!-- Stopped reason banner -->
  {#if stoppedReason && STOPPED_REASON_CONFIG[stoppedReason]}
    {@const cfg = STOPPED_REASON_CONFIG[stoppedReason]}
    <div class="flex items-center gap-2 font-mono text-[11px] px-3 py-1.5 rounded-chip border {cfg.chip}">
      {#if stoppedReason === 'provider_offline'}
        <svg class="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
      {:else}
        <svg class="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>
      {/if}
      {cfg.label}
    </div>
  {/if}

  <!-- Event log -->
  <div class="border border-c-border rounded-panel divide-y divide-c-divider max-h-80 overflow-y-auto bg-c-well/50">
    {#if events.length === 0}
      <div class="px-4 py-6 text-center text-sm text-c-faint">
        {running ? 'Starting pipeline…' : 'No events yet.'}
      </div>
    {:else}
      {#each events as evt (evt.timestamp + evt.step + evt.status)}
        <div class="text-sm">
          <div class="flex items-start gap-3 px-4 py-2 hover:bg-c-well/80">
            <span class="font-mono flex-shrink-0 mt-0.5 {STATUS_COLOR[evt.status] ?? 'text-c-faint'}">
              {STATUS_ICON[evt.status] ?? '·'}
            </span>
            <div class="flex-1 min-w-0">
              <span class="font-medium text-c-text2">{STEP_LABELS[evt.step] ?? evt.step}</span>
              {#if evt.iteration != null}
                <span class="font-mono text-[11px] text-c-faint ml-1">iter {evt.iteration}</span>
              {/if}
              <p class="text-c-faint text-xs mt-0.5 leading-snug">{evt.message}</p>
            </div>
            {#if evt.step === 'summarize_code' && evt.status === 'completed' && evt.data?.code_summary}
              <button
                type="button"
                on:click={() => codeDetailOpen = !codeDetailOpen}
                class="flex-shrink-0 text-c-faint hover:text-c-muted mt-0.5"
                aria-label="Toggle code analysis detail"
              >
                <svg class="w-4 h-4 transition-transform {codeDetailOpen ? 'rotate-180' : ''}" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/>
                </svg>
              </button>
            {/if}
          </div>
          {#if codeDetailOpen && evt.step === 'summarize_code' && evt.status === 'completed' && evt.data?.code_summary}
            {@const cs = evt.data.code_summary}
            <div class="mx-4 mb-2 px-3 py-2.5 bg-c-panel border border-c-border rounded-panel space-y-2 text-xs">
              {#if cs.tech_stack?.length}
                <div class="flex flex-wrap gap-1 items-center">
                  <span class="text-c-faint mr-1 flex-shrink-0">Stack</span>
                  {#each cs.tech_stack as t}
                    <span class="font-mono text-[11px] px-1.5 py-0.5 rounded-chip border chip-blue">{t}</span>
                  {/each}
                </div>
              {/if}
              {#if cs.entry_points?.length && cs.entry_points[0] !== 'No entry points detected'}
                <div>
                  <span class="text-c-faint block mb-1">Entry Points</span>
                  <div class="space-y-0.5 max-h-24 overflow-y-auto">
                    {#each cs.entry_points as ep}
                      <div class="font-mono text-c-text2">{ep}</div>
                    {/each}
                  </div>
                </div>
              {/if}
              {#if cs.auth_patterns?.length && cs.auth_patterns[0] !== 'No auth patterns detected'}
                <div class="flex flex-wrap gap-1 items-center">
                  <span class="text-c-faint mr-1 flex-shrink-0">Auth</span>
                  {#each cs.auth_patterns as a}
                    <span class="font-mono text-[11px] px-1.5 py-0.5 rounded-chip border chip-accent">{a}</span>
                  {/each}
                </div>
              {/if}
              {#if cs.security_observations?.length && cs.security_observations[0] !== 'No security issues detected in automated scan'}
                <div>
                  <span class="text-c-faint block mb-1">Observations</span>
                  {#each cs.security_observations as obs}
                    <div class="flex items-start gap-1">
                      <span class="{obs.startsWith('CRITICAL') ? 'text-c-critical' : 'text-c-high'} flex-shrink-0">⚠</span>
                      <span class="text-c-muted">{obs}</span>
                    </div>
                  {/each}
                </div>
              {/if}
            </div>
          {/if}
        </div>
      {/each}
    {/if}
  </div>
</div>
