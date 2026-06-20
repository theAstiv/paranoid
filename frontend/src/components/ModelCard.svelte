<script>
  import { link } from 'svelte-spa-router'

  /** @type {{ id: string, title: string, framework: string, status: string, threat_count?: number, created_at: string, description?: string }} */
  export let model

  /** @type {() => void} */
  export let onDelete = null

  const FRAMEWORK_CHIP = {
    STRIDE: 'chip-blue',
    MAESTRO: 'chip-accent',
    HYBRID: 'chip-violet',
  }

  const STATUS_CHIP = {
    pending:     'chip-gray',
    in_progress: 'chip-blue',
    completed:   'chip-green',
    failed:      'chip-red',
    in_review:   'chip-amber',
    approved:    'chip-accent',
    archived:    'chip-gray',
  }

  const STATUS_DOT = {
    pending:     'bg-c-faint',
    in_progress: 'bg-c-blue animate-pulse-dot',
    completed:   'bg-c-green',
    failed:      'bg-c-critical',
    in_review:   'bg-c-high',
    approved:    'bg-c-accent',
    archived:    'bg-c-faint2',
  }

  function formatDate(iso) {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
  }

  $: frameworkChip = FRAMEWORK_CHIP[model.framework] ?? 'chip-gray'
  $: statusChip = STATUS_CHIP[model.status] ?? 'chip-gray'
  $: statusDot = STATUS_DOT[model.status] ?? 'bg-c-faint'
  $: statusLabel = (model.status ?? '').replace(/_/g, ' ')
</script>

<div class="relative group/card">
  <a
    href="/models/{model.id}"
    use:link
    class="card block p-5 hover:border-c-accent-deep transition-all group"
  >
    <!-- Header row: title + framework chip -->
    <div class="flex items-start justify-between gap-3 mb-3">
      <h2 class="text-c-text text-[15px] font-medium leading-snug line-clamp-2 flex-1 group-hover:text-c-accent transition-colors">
        {model.title}
      </h2>
      <span class="flex-shrink-0 font-mono text-[10px] tracking-wide px-2 py-0.5 rounded-chip {frameworkChip}">
        {model.framework}
      </span>
    </div>

    <!-- Description if present -->
    {#if model.description}
      <p class="text-c-faint text-[12px] leading-relaxed line-clamp-1 mb-3">
        {model.description}
      </p>
    {/if}

    <!-- Footer: status + meta -->
    <div class="flex items-center justify-between mt-auto pt-1">
      <div class="flex items-center gap-2">
        <span class="w-1.5 h-1.5 rounded-full flex-shrink-0 {statusDot}"></span>
        <span class="font-mono text-[11px] tracking-wide px-1.5 py-0.5 rounded-chip capitalize {statusChip}">
          {statusLabel}
        </span>
      </div>

      <div class="flex items-center gap-3 font-mono text-[11px] text-c-faint">
        {#if model.threat_count != null}
          <span>{model.threat_count} threats</span>
        {/if}
        <span>{formatDate(model.created_at)}</span>
      </div>
    </div>
  </a>

  <!-- Delete button — top-right overlay on card hover -->
  {#if onDelete}
    <button
      type="button"
      on:click|preventDefault|stopPropagation={onDelete}
      title="Delete threat model"
      class="absolute top-3 right-8 p-1.5 rounded-panel text-c-faint2 opacity-0 group-hover/card:opacity-100
             hover:bg-c-critical/10 hover:text-c-critical transition-all z-10"
    >
      <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/>
      </svg>
    </button>
  {/if}
</div>
