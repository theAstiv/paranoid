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
    class="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-md hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-indigo-500">
    Export
    <svg class="w-4 h-4 text-slate-400 transition-transform {open ? 'rotate-180' : ''}" viewBox="0 0 20 20" fill="currentColor">
      <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/>
    </svg>
  </button>

  {#if open}
    <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
    <div class="fixed inset-0 z-10" on:click={() => open = false}></div>
    <div class="absolute right-0 mt-1 z-20 w-40 bg-white border border-slate-200 rounded-lg shadow-lg py-1">
      {#each formats as fmt}
        <button
          type="button"
          on:click={() => download(fmt.value)}
          class="w-full flex flex-col px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 text-left">
          <div class="flex items-center justify-between w-full">
            {fmt.label}
            <span class="text-xs text-slate-400 font-mono">{fmt.ext}</span>
          </div>
          {#if fmt.note}
            <span class="text-xs text-slate-400 mt-0.5">{fmt.note}</span>
          {/if}
        </button>
      {/each}
    </div>
  {/if}
</div>
