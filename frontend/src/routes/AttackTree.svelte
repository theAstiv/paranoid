<script>
  import { onMount, tick } from 'svelte'
  import { link } from 'svelte-spa-router'
  import { getThreat, listAttackTrees, generateAttackTree } from '../lib/api.js'
  import { currentModel, notify } from '../lib/stores.js'
  import { sanitizeMermaid } from '../lib/mermaid_sanitize.js'

  /** @type {{ id: string }} */
  export let params = {}

  let threat = null
  let tree = null
  let loading = true
  let generating = false
  let svgContainer
  let renderError = null      // Error message if Mermaid parsing failed
  let showRawSource = false   // Toggle: show raw Mermaid in fallback card

  onMount(async () => {
    try {
      threat = await getThreat(params.id)
      const trees = await listAttackTrees(params.id)
      if (trees.length > 0) {
        tree = trees[trees.length - 1]
      }
    } catch (err) {
      notify('error', `Failed to load threat: ${err.message}`)
    } finally {
      loading = false
    }
    // tick() waits for the DOM to update (svgContainer is inside {:else}, so it
    // only exists after loading = false flips the block).
    if (tree) {
      await tick()
      await renderMermaid(tree.mermaid_source)
    }
  })

  async function generate() {
    generating = true
    renderError = null
    showRawSource = false
    try {
      tree = await generateAttackTree(params.id)
      // tick() flushes Svelte's DOM updates so the {#if tree} block mounts
      // svgContainer before renderMermaid tries to write to it.
      await tick()
      if (!svgContainer) {
        // Should not happen after tick(), but guard defensively so errors
        // are visible rather than silently discarded.
        console.warn('AttackTree: svgContainer not mounted after tick — skipping render')
        return
      }
      await renderMermaid(tree.mermaid_source)
    } catch (err) {
      notify('error', `Failed to generate attack tree: ${err.message}`)
    } finally {
      generating = false
    }
  }

  async function renderMermaid(source) {
    if (!svgContainer) return
    renderError = null
    const cleaned = sanitizeMermaid(source)
    if (!cleaned) {
      renderError = 'Mermaid source is empty.'
      svgContainer.innerHTML = ''
      return
    }
    const mermaid = (await import('mermaid')).default
    // 'strict' disables click handlers — the sanitizeMermaid pass already
    // strips click directives, but strict adds a second layer of defence.
    mermaid.initialize({ startOnLoad: false, theme: 'neutral', securityLevel: 'strict' })
    // Timestamp suffix avoids mermaid.render() ID collisions on regenerate
    // without a page reload.
    const renderId = `tree-${params.id}-${Date.now()}`
    try {
      const { svg } = await mermaid.render(renderId, cleaned)
      svgContainer.innerHTML = svg
    } catch (err) {
      // Clear the container so a stale SVG doesn't sit next to the fallback card.
      svgContainer.innerHTML = ''
      renderError = err?.message || 'Mermaid rendering failed.'
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

      <!-- Mermaid render target — hidden when we fall back to the error card. -->
      <div bind:this={svgContainer} class="overflow-auto" class:hidden={renderError !== null}></div>

      {#if renderError && tree}
        <div class="rounded-lg border border-amber-300 bg-amber-50 px-4 py-4 space-y-3">
          <div class="flex items-start gap-2">
            <svg class="w-5 h-5 text-amber-600 mt-0.5 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
            <div class="min-w-0">
              <p class="text-sm font-medium text-amber-900">Mermaid rendering failed</p>
              <p class="text-xs text-amber-800 mt-0.5">
                The generated diagram syntax couldn't be parsed. Regenerate to try again, or inspect the raw source below.
              </p>
            </div>
          </div>

          <div class="flex items-center gap-2">
            <button
              type="button"
              on:click={generate}
              disabled={generating}
              class="px-3 py-1.5 text-xs font-medium text-white bg-amber-700 rounded-md hover:bg-amber-800 disabled:opacity-50 transition-colors">
              Regenerate
            </button>
            <button
              type="button"
              on:click={() => { showRawSource = !showRawSource }}
              class="px-3 py-1.5 text-xs font-medium text-amber-900 border border-amber-300 rounded-md hover:bg-amber-100 transition-colors">
              {showRawSource ? 'Hide' : 'Show'} raw source
            </button>
          </div>

          {#if showRawSource}
            <pre class="text-xs text-slate-700 bg-white border border-amber-200 rounded p-3 overflow-auto max-h-80 whitespace-pre">{tree.mermaid_source}</pre>
          {/if}
        </div>
      {/if}
    </div>
  {/if}
</div>
