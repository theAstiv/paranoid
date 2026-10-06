<script>
  import { cvssChip, cvssColor, cvssScoreLabel, normalizeCvssMetrics, CVSS_METRICS } from '../lib/utils.js'

  /**
   * Pass the full threat object. CvssBadge normalizes the CVSS data internally.
   *
   * Two shapes exist depending on the source:
   *   SSE events  → threat.cvss = { attack_vector, attack_complexity, ... } (8 base metrics)
   *   DB/API GET  → threat.cvss_vector = "AV:N/AC:L/..." (canonical vector string)
   * Both shapes carry flat threat.cvss_score / threat.cvss_severity — those
   * are never nested, computed server-side either way.
   *
   * @type {object|null}
   */
  export let threat = null

  let expanded = false

  $: score = threat?.cvss_score ?? null
  $: severity = threat?.cvss_severity ?? null
  $: metrics = normalizeCvssMetrics(threat)
</script>

{#if score != null}
  <div class="relative inline-block">
    <button
      type="button"
      on:click={() => expanded = !expanded}
      class="inline-flex items-center gap-1 font-mono text-[11px] px-2 py-0.5 rounded-chip border transition-colors {cvssChip(score)}">
      CVSS {cvssScoreLabel(score)}
    </button>

    {#if expanded}
      <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
      <div class="fixed inset-0 z-10" on:click={() => expanded = false}></div>
      <div class="absolute bottom-full left-0 mb-2 z-20 bg-c-panel border border-c-border rounded-panel shadow-xl p-3 w-56 animate-pop-in">
        <p class="font-mono text-[10px] font-semibold text-c-muted mb-2 uppercase tracking-wide">CVSS v3.1 breakdown</p>
        {#if severity}
          <p class="text-xs mb-2">
            <span class="text-c-muted">Severity:</span>
            <span class="font-semibold capitalize {cvssColor(score)}">{severity}</span>
          </p>
        {/if}
        {#if metrics}
          <dl class="space-y-1.5">
            {#each CVSS_METRICS as [, label, key, valueLabels]}
              <div class="flex items-center justify-between text-xs gap-2">
                <dt class="text-c-muted">{label}</dt>
                <dd class="font-mono font-semibold text-c-text text-right">
                  {metrics[key] ? (valueLabels[metrics[key]] ?? metrics[key]) : '—'}
                </dd>
              </div>
            {/each}
          </dl>
        {/if}
      </div>
    {/if}
  </div>
{/if}
