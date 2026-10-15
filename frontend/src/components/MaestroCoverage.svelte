<script>
  /**
   * Per-category MAESTRO coverage from GET /models/{id}/maestro-coverage.
   * @type {{ assessed: boolean, categories: { category: string, status: string, threats: number }[] } | null}
   */
  export let coverage = null

  const STATUS = {
    covered:      { label: 'Covered',      chip: 'chip-green' },
    not_covered:  { label: 'Not covered',  chip: 'chip-amber' },
    na:           { label: 'N/A',          chip: 'chip-gray' },
    not_assessed: { label: 'Not assessed', chip: 'chip-gray' },
  }
</script>

{#if coverage?.categories?.length}
  <div class="card p-5" data-testid="maestro-coverage">
    <h2 class="text-xs font-semibold text-c-muted uppercase tracking-wide">MAESTRO coverage</h2>
    <p class="text-xs text-c-faint mt-1 mb-4">
      {#if coverage.assessed}
        A category is N/A when no component in the model makes it applicable.
      {:else}
        No component could be matched to a category, so applicability is unknown.
      {/if}
    </p>
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
      {#each coverage.categories as c (c.category)}
        {@const s = STATUS[c.status] ?? STATUS.not_assessed}
        <div
          class="flex items-center gap-2 text-sm py-1.5 border-b border-c-divider"
          data-testid="maestro-{c.category}"
        >
          <span class="text-c-text2 flex-1 truncate">{c.category}</span>
          {#if c.status === 'covered'}
            <span class="font-mono text-[11px] text-c-faint">{c.threats}</span>
          {:else if c.status === 'na'}
            <span class="text-[11px] text-c-faint">no component in the model</span>
          {/if}
          <span class="font-mono text-[11px] px-2 py-0.5 rounded-chip border {s.chip}">{s.label}</span>
        </div>
      {/each}
    </div>
  </div>
{/if}
