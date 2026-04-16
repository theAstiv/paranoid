<script>
  import { onMount } from 'svelte'
  import { link } from 'svelte-spa-router'
  import { getThreat, listAttackTrees, generateAttackTree } from '../lib/api.js'
  import { currentModel, notify } from '../lib/stores.js'

  /** @type {{ id: string }} */
  export let params = {}

  let threat = null
  let tree = null
  let loading = true
  let generating = false
  let svgContainer

  onMount(async () => {
    try {
      threat = await getThreat(params.id)
      await loadTree()
    } catch (err) {
      notify('error', `Failed to load threat: ${err.message}`)
    } finally {
      loading = false
    }
  })

  async function loadTree() {
    const trees = await listAttackTrees(params.id)
    if (trees.length > 0) {
      tree = trees[0]
      await renderMermaid(tree.mermaid_source)
    }
  }

  async function generate() {
    generating = true
    try {
      tree = await generateAttackTree(params.id)
      await renderMermaid(tree.mermaid_source)
    } catch (err) {
      notify('error', `Failed to generate attack tree: ${err.message}`)
    } finally {
      generating = false
    }
  }

  async function renderMermaid(source) {
    if (!svgContainer) return
    const mermaid = (await import('mermaid')).default
    mermaid.initialize({ startOnLoad: false, theme: 'neutral', securityLevel: 'loose' })
    try {
      const { svg } = await mermaid.render(`tree-${params.id}`, source)
      svgContainer.innerHTML = svg
    } catch (err) {
      svgContainer.innerHTML = `<pre class="text-xs text-slate-500 overflow-auto">${source}</pre>`
    }
  }
</script>

<div class="max-w-4xl mx-auto space-y-5">
  <!-- Header -->
  <div class="flex items-center justify-between">
    <h1 class="text-2xl font-semibold text-slate-900">Attack Tree</h1>
    <div class="flex items-center gap-2">
      {#if $currentModel}
        <a href="/models/{$currentModel.id}/review" use:link class="text-sm text-slate-500 hover:text-slate-700">← Review</a>
      {/if}
    </div>
  </div>

  {#if loading}
    <div class="flex justify-center py-16">
      <div class="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
    </div>
  {:else}
    {#if threat}
      <div class="bg-white rounded-xl border border-slate-200 p-5">
        <h2 class="font-semibold text-slate-900">{threat.name}</h2>
        <p class="text-sm text-slate-600 mt-1">{threat.description}</p>
      </div>
    {/if}

    <div class="bg-white rounded-xl border border-slate-200 p-5">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-sm font-semibold text-slate-700">Attack Tree</h3>
        <button
          type="button"
          on:click={generate}
          disabled={generating}
          class="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-indigo-700 bg-indigo-50 rounded-md hover:bg-indigo-100 disabled:opacity-50 transition-colors">
          {#if generating}
            <div class="w-3.5 h-3.5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
          {/if}
          {tree ? 'Regenerate' : 'Generate'}
        </button>
      </div>

      {#if !tree && !generating}
        <div class="text-center py-10 text-slate-400 text-sm">
          No attack tree yet. Click Generate to create one.
        </div>
      {:else if generating && !tree}
        <div class="flex justify-center py-10">
          <div class="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
        </div>
      {/if}

      <div bind:this={svgContainer} class="overflow-auto"></div>
    </div>
  {/if}
</div>
