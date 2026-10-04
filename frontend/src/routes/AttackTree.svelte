<script>
  import { onMount } from 'svelte'
  import { link } from 'svelte-spa-router'
  import { getThreat, listAttackTrees, generateAttackTree } from '../lib/api.js'
  import { currentModel, notify } from '../lib/stores.js'
  import DiagramView from '../components/DiagramView.svelte'

  /** @type {{ id: string }} */
  export let params = {}

  let threat = null
  let tree = null
  let loading = true
  let generating = false

  onMount(async () => {
    try {
      threat = await getThreat(params.id)
      const trees = await listAttackTrees(params.id)
      if (trees.length > 0) tree = trees[trees.length - 1]
    } catch (err) {
      notify('error', `Failed to load threat: ${err.message}`)
    } finally {
      loading = false
    }
  })

  async function generate() {
    generating = true
    try {
      tree = await generateAttackTree(params.id)
    } catch (err) {
      notify('error', `Failed to generate attack tree: ${err.message}`)
    } finally {
      generating = false
    }
  }
</script>

<div class="max-w-[1120px] mx-auto space-y-5">
  <div class="flex items-center justify-between">
    <h1 class="text-xl font-semibold text-c-text">Attack Tree</h1>
    {#if $currentModel}
      <a href="/models/{$currentModel.id}/review" use:link class="text-sm text-c-muted hover:text-c-text2">← Review</a>
    {/if}
  </div>

  {#if loading}
    <div class="flex justify-center py-16">
      <div class="w-6 h-6 border-2 border-c-accent border-t-transparent rounded-full animate-spin-slow"></div>
    </div>
  {:else}
    {#if threat}
      <div class="card p-5">
        <h2 class="font-semibold text-c-text">{threat.name}</h2>
        <p class="text-sm text-c-muted mt-1">{threat.description}</p>
      </div>
    {/if}

    <div class="card p-5">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-xs font-semibold text-c-muted uppercase tracking-wide">Attack Tree</h3>
        <button type="button" on:click={generate} disabled={generating}
          class="flex items-center gap-1.5 btn-ghost text-sm px-3 py-1.5 disabled:opacity-50">
          {#if generating}
            <div class="w-3.5 h-3.5 border-2 border-c-accent border-t-transparent rounded-full animate-spin-slow"></div>
          {/if}
          {tree ? 'Regenerate' : 'Generate'}
        </button>
      </div>

      {#if !tree && !generating}
        <div class="text-center py-10 text-c-faint text-sm">
          No attack tree yet. Click Generate to create one.
        </div>
      {:else if generating && !tree}
        <div class="flex justify-center py-10">
          <div class="w-6 h-6 border-2 border-c-accent border-t-transparent rounded-full animate-spin-slow"></div>
        </div>
      {:else if tree}
        <DiagramView kind="mermaid" content={tree.mermaid_source} name="attack-tree" />
      {/if}
    </div>
  {/if}
</div>
