<script>
  import { onMount } from 'svelte'
  import { link } from 'svelte-spa-router'
  import { getThreat, listTestCases, generateTestCases } from '../lib/api.js'
  import { currentModel, notify } from '../lib/stores.js'

  /** @type {{ id: string }} */
  export let params = {}

  let threat = null
  let testCase = null
  let loading = true
  let generating = false

  onMount(async () => {
    try {
      threat = await getThreat(params.id)
      const cases = await listTestCases(params.id)
      testCase = cases[cases.length - 1] ?? null
    } catch (err) {
      notify('error', `Failed to load: ${err.message}`)
    } finally {
      loading = false
    }
  })

  async function generate() {
    generating = true
    try {
      testCase = await generateTestCases(params.id)
    } catch (err) {
      notify('error', `Failed to generate test cases: ${err.message}`)
    } finally {
      generating = false
    }
  }

  function copyToClipboard() {
    if (!testCase) return
    navigator.clipboard.writeText(testCase.gherkin_source)
      .then(() => notify('success', 'Copied to clipboard'))
      .catch(() => notify('error', 'Failed to copy'))
  }
</script>

<div class="max-w-[1120px] mx-auto space-y-5">
  <div class="flex items-center justify-between">
    <h1 class="text-xl font-semibold text-c-text">Test Cases</h1>
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
        <h3 class="text-xs font-semibold text-c-muted uppercase tracking-wide">Gherkin Test Cases</h3>
        <div class="flex gap-2">
          {#if testCase}
            <button type="button" on:click={copyToClipboard} class="btn-ghost text-xs px-3 py-1.5">
              Copy
            </button>
          {/if}
          <button type="button" on:click={generate} disabled={generating}
            class="flex items-center gap-1.5 btn-ghost text-xs px-3 py-1.5 disabled:opacity-50">
            {#if generating}
              <div class="w-3.5 h-3.5 border-2 border-c-accent border-t-transparent rounded-full animate-spin-slow"></div>
            {/if}
            {testCase ? 'Regenerate' : 'Generate'}
          </button>
        </div>
      </div>

      {#if !testCase && !generating}
        <div class="text-center py-10 text-c-faint text-sm">
          No test cases yet. Click Generate to create Gherkin scenarios.
        </div>
      {:else if generating && !testCase}
        <div class="flex justify-center py-10">
          <div class="w-6 h-6 border-2 border-c-accent border-t-transparent rounded-full animate-spin-slow"></div>
        </div>
      {:else if testCase}
        <pre class="font-mono text-xs text-c-text2 bg-c-well border border-c-border rounded-panel p-4 overflow-auto whitespace-pre-wrap leading-relaxed">{testCase.gherkin_source}</pre>
      {/if}
    </div>
  {/if}
</div>
