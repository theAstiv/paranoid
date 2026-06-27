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
  let renderError = null
  let showRawSource = false

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
      await tick()
      if (!svgContainer) {
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
    mermaid.initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'strict' })
    const renderId = `tree-${params.id}-${Date.now()}`
    try {
      const { svg } = await mermaid.render(renderId, cleaned)
      svgContainer.innerHTML = svg
    } catch (err) {
      svgContainer.innerHTML = ''
      renderError = err?.message || 'Mermaid rendering failed.'
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
      {/if}

      <!-- Mermaid render target -->
      <div bind:this={svgContainer} class="overflow-auto" class:hidden={renderError !== null}></div>

      {#if renderError && tree}
        <div class="rounded-panel border border-c-high/40 bg-c-high/5 px-4 py-4 space-y-3">
          <div class="flex items-start gap-2">
            <svg class="w-5 h-5 text-c-high mt-0.5 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
            </svg>
            <div class="min-w-0">
              <p class="text-sm font-medium text-c-high">Mermaid rendering failed</p>
              <p class="text-xs text-c-muted mt-0.5">
                The generated diagram syntax couldn't be parsed. Regenerate to try again, or inspect the raw source below.
              </p>
            </div>
          </div>

          <div class="flex items-center gap-2">
            <button type="button" on:click={generate} disabled={generating}
              class="btn-primary text-xs px-3 py-1.5 disabled:opacity-50">
              Regenerate
            </button>
            <button type="button" on:click={() => { showRawSource = !showRawSource }}
              class="btn-ghost text-xs px-3 py-1.5">
              {showRawSource ? 'Hide' : 'Show'} raw source
            </button>
          </div>

          {#if showRawSource}
            <pre class="font-mono text-xs text-c-text2 bg-c-well border border-c-border rounded-panel p-3 overflow-auto max-h-80 whitespace-pre">{tree.mermaid_source}</pre>
          {/if}
        </div>
      {/if}
    </div>
  {/if}
</div>
