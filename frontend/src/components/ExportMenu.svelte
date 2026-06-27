<script>
  import { exportUrl } from '../lib/api.js'

  /** @type {string} */
  export let modelId = ''
  /** @type {string} */
  export let statusFilter = ''

  let open = false

  const formats = [
    { value: 'markdown', label: 'Markdown', ext: '.md', note: null },
    { value: 'pdf', label: 'PDF', ext: '.pdf', note: null },
    { value: 'json', label: 'JSON', ext: '.json', note: null },
    { value: 'sarif', label: 'SARIF', ext: '.sarif', note: 'MAESTRO-only excluded; hybrid included' },
  ]

  function download(format) {
    window.open(exportUrl(modelId, format, statusFilter))
    open = false
  }
</script>

<div class="relative">
  <button
    type="button"
    on:click={() => open = !open}
    class="btn-ghost">
    Export
    <svg class="w-3.5 h-3.5 text-c-muted transition-transform {open ? 'rotate-180' : ''}" viewBox="0 0 20 20" fill="currentColor">
      <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/>
    </svg>
  </button>

  {#if open}
    <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
    <div class="fixed inset-0 z-10" on:click={() => open = false}></div>
    <div class="absolute right-0 mt-1.5 z-20 w-44 bg-c-panel border border-c-border rounded-panel shadow-xl py-1 animate-pop-in">
      {#each formats as fmt}
        <button
          type="button"
          on:click={() => download(fmt.value)}
          class="w-full flex flex-col px-3 py-2 text-sm text-c-text2 hover:bg-c-well hover:text-c-text text-left transition-colors">
          <div class="flex items-center justify-between w-full">
            {fmt.label}
            <span class="font-mono text-[11px] text-c-faint">{fmt.ext}</span>
          </div>
          {#if fmt.note}
            <span class="text-[11px] text-c-faint mt-0.5">{fmt.note}</span>
          {/if}
        </button>
      {/each}
    </div>
  {/if}
</div>
