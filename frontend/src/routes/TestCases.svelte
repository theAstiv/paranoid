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
      testCase = cases[0] ?? null
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

<div class="max-w-4xl mx-auto space-y-5">
  <div class="flex items-center justify-between">
    <h1 class="text-2xl font-semibold text-slate-900">Test Cases</h1>
    {#if $currentModel}
      <a href="/models/{$currentModel.id}/review" use:link class="text-sm text-slate-500 hover:text-slate-700">← Review</a>
    {/if}
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
        <h3 class="text-sm font-semibold text-slate-700">Gherkin Test Cases</h3>
        <div class="flex gap-2">
          {#if testCase}
            <button
              type="button"
              on:click={copyToClipboard}
              class="px-3 py-1.5 text-sm font-medium text-slate-600 bg-slate-100 rounded-md hover:bg-slate-200">
              Copy
            </button>
          {/if}
          <button
            type="button"
            on:click={generate}
            disabled={generating}
            class="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-indigo-700 bg-indigo-50 rounded-md hover:bg-indigo-100 disabled:opacity-50">
            {#if generating}
              <div class="w-3.5 h-3.5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
            {/if}
            {testCase ? 'Regenerate' : 'Generate'}
          </button>
        </div>
      </div>

      {#if !testCase && !generating}
        <div class="text-center py-10 text-slate-400 text-sm">
          No test cases yet. Click Generate to create Gherkin scenarios.
        </div>
      {:else if generating && !testCase}
        <div class="flex justify-center py-10">
          <div class="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
        </div>
      {:else if testCase}
        <pre class="text-xs font-mono text-slate-700 bg-slate-50 rounded-lg p-4 overflow-auto whitespace-pre-wrap leading-relaxed">{testCase.gherkin_source}</pre>
      {/if}
    </div>
  {/if}
</div>
