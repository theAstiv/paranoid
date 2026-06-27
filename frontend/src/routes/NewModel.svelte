<script>
  import { push, link } from 'svelte-spa-router'
  import Wizard from '../components/Wizard.svelte'
  import PreFlightPanel from '../components/PreFlightPanel.svelte'
  import { createModel, subscribeToRun, listCodeSources, analyzeBundle } from '../lib/api.js'
  import { getModel } from '../lib/api.js'
  import { notify, pipelineEvents, pipelineRunning, threats, currentModel, abortRun, config } from '../lib/stores.js'

  const STEPS = ['Title & Framework', 'Description', 'Diagram', 'Code Source', 'Assumptions', 'Iterations', 'AI Components', 'Review & Run']

  let step = 0
  let submitting = false

  let title = ''
  let framework = 'STRIDE'
  let description = ''
  let diagramFile = null
  let diagramPreview = null
  let assumptions = []
  let newAssumption = ''
  let iterationCount = 3
  let hasAiComponents = false
  let strictMode = false

  let llmAnalysisLoading = false
  let llmDescriptionGaps = []
  let llmAssumptionsGaps = []
  let _analyzeDebounceTimer = null
  let _analyzeController = null

  function _clearLlmResults() {
    llmDescriptionGaps = []
    llmAssumptionsGaps = []
    llmAnalysisLoading = false
  }

  function scheduleAnalysis() {
    clearTimeout(_analyzeDebounceTimer)
    if (_analyzeController) _analyzeController.abort()
    _analyzeController = null
    if (description.trim().length < 200) { _clearLlmResults(); return }
    _analyzeDebounceTimer = setTimeout(runAnalysis, 600)
  }

  async function runAnalysis() {
    _analyzeController = new AbortController()
    const signal = _analyzeController.signal
    llmAnalysisLoading = true
    try {
      const result = await analyzeBundle({ description: description.trim(), assumptions, framework, hasAi: hasAiComponents, signal })
      llmDescriptionGaps = result.description.gaps
      llmAssumptionsGaps = result.assumptions.gaps
    } catch (err) {
      if (err.name !== 'AbortError') console.warn('Pre-flight analysis failed:', err.message)
    } finally {
      llmAnalysisLoading = false
    }
  }

  $: { description; assumptions; scheduleAnalysis() }

  $: strictBlocked = strictMode && (
    llmDescriptionGaps.some(g => g.severity === 'error') ||
    llmAssumptionsGaps.some(g => g.severity === 'error')
  )

  $: providerKeyMissing = (() => {
    if (!$config) return false
    const p = $config.default_provider
    if (p === 'anthropic') return $config.anthropic_api_key_set === false
    if (p === 'openai') return $config.openai_api_key_set === false
    return false
  })()
  $: providerLabel = $config?.default_provider ?? 'the provider'

  let selectedCodeSourceId = null
  let readySources = []
  let loadingSources = false
  let sourcesLoaded = false

  $: if (step === 3 && !sourcesLoaded) loadSources()

  async function loadSources() {
    loadingSources = true
    sourcesLoaded = true
    try {
      const all = await listCodeSources()
      readySources = all.filter(s => s.last_index_status === 'ready')
    } catch (err) {
      console.warn('NewModel: failed to load code sources', err)
    } finally {
      loadingSources = false
    }
  }

  const AUTH_RE = /\b(auth(?:entication|orization)?|oauth|jwt|token|saml|sso|password|credential|api.?key|bearer|session|login|mfa|2fa)\b/i
  const BOUNDARY_RE = /\b(trust.?boundary|network.?segment|dmz|firewall|vlan|subnet|vpc|perimeter|internet.?facing|internal|external|public|private)\b/i
  const FLOW_RE = /\b(sends?|receives?|transfers?|communicates?|calls?|requests?|responses?|reads?|writes?|stores?|fetches?|connects?|publishes?|subscribes?)\b/i
  const EXTERNAL_RE = /\b(third.?party|external|vendor|api|webhook|integration|partner|upstream|downstream|database|db|queue|broker|cache|cdn|dns|smtp|email)\b/i

  $: descriptionGaps = (() => {
    const d = description.trim()
    if (d.length < 80) return []
    const gaps = []
    if (!AUTH_RE.test(d)) gaps.push({ field: 'authentication', message: 'No auth mechanism mentioned (OAuth, JWT, API key, etc.)' })
    if (!BOUNDARY_RE.test(d)) gaps.push({ field: 'trust boundaries', message: 'No trust boundaries described (internet-facing, internal, VPC, etc.)' })
    if (!FLOW_RE.test(d)) gaps.push({ field: 'data flows', message: 'No data flows mentioned (sends, receives, stores, etc.)' })
    if (!EXTERNAL_RE.test(d)) gaps.push({ field: 'external systems', message: 'No external systems named (DB, queue, 3rd-party API, etc.)' })
    return gaps
  })()

  $: nextDisabled = (() => {
    if (step === 0) return !title.trim() || title.length > 200
    if (step === 1) return description.trim().length < 10
    if (step === 7) return submitting || strictBlocked || providerKeyMissing
    return false
  })()

  function handleDiagramChange(e) {
    const file = e.target.files[0]
    if (!file) { diagramFile = null; diagramPreview = null; return }
    if (file.size > 5 * 1024 * 1024) {
      notify('error', 'Diagram file must be under 5 MB')
      e.target.value = ''
      return
    }
    diagramFile = file
    if (file.type.startsWith('image/')) {
      const reader = new FileReader()
      reader.onload = ev => { diagramPreview = ev.target.result }
      reader.readAsDataURL(file)
    } else {
      diagramPreview = null
    }
  }

  function addAssumption() {
    const val = newAssumption.trim()
    if (val) { assumptions = [...assumptions, val]; newAssumption = '' }
  }

  function removeAssumption(i) {
    assumptions = assumptions.filter((_, idx) => idx !== i)
  }

  async function handleSubmit() {
    submitting = true
    try {
      const model = await createModel({ title: title.trim(), description: description.trim(), framework, iteration_count: iterationCount })
      const fd = new FormData()
      fd.append('assumptions', JSON.stringify(assumptions))
      fd.append('has_ai_components', String(hasAiComponents))
      if (diagramFile) fd.append('diagram', diagramFile)
      if (selectedCodeSourceId) fd.append('code_source_id', selectedCodeSourceId)
      pipelineEvents.set([])
      pipelineRunning.set(true)
      const modelId = model.id
      const abort = subscribeToRun(
        modelId, fd,
        evt => {
          pipelineEvents.update(es => [...es, evt])
          if (evt.step === 'complete' && evt.data?.threats?.threats) threats.set(evt.data.threats.threats)
        },
        err => { notify('error', `Pipeline error: ${err.message}`); pipelineRunning.set(false) },
        async () => {
          pipelineRunning.set(false)
          try { const refreshed = await getModel(modelId); currentModel.set(refreshed); threats.set(refreshed.threats ?? []) } catch { /* ignore */ }
        },
      )
      abortRun.set(abort)
      await push(`/models/${model.id}`)
    } catch (err) {
      notify('error', `Failed to create model: ${err.message}`)
      pipelineRunning.set(false)
      submitting = false
    }
  }

  const LABEL_CLASS = 'block text-xs font-medium text-c-muted mb-1 uppercase tracking-wide'
  const INPUT_CLASS = 'field w-full'
</script>

<div class="max-w-[880px] mx-auto">
  <Wizard
    steps={STEPS}
    currentStep={step}
    {nextDisabled}
    {submitting}
    on:next={() => step++}
    on:back={() => step--}
    on:submit={handleSubmit}
  >
    {#if step === 0}
      <div class="space-y-5">
        <div>
          <label class="{LABEL_CLASS}" for="title">Model title</label>
          <input id="title" type="text" bind:value={title} maxlength="200"
            placeholder="e.g. Payment Gateway, Auth Service"
            class="{INPUT_CLASS}" />
          <p class="mt-1 font-mono text-[11px] text-c-faint">{title.length}/200</p>
        </div>
        <div>
          <p class="{LABEL_CLASS}">Threat framework</p>
          <div class="flex gap-4 mt-2">
            {#each ['STRIDE', 'MAESTRO', 'HYBRID'] as fw}
              <label class="flex items-center gap-2 cursor-pointer">
                <input type="radio" bind:group={framework} value={fw}
                  class="text-c-accent focus:ring-c-accent" />
                <span class="text-sm font-medium text-c-text2">{fw}</span>
              </label>
            {/each}
          </div>
          <p class="mt-2 text-xs text-c-muted">
            {#if framework === 'STRIDE'}
              Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, Elevation of Privilege.
            {:else if framework === 'MAESTRO'}
              AI/ML-specific: Model Security, Data Security, LLM Security, Pipeline Security, and more.
            {:else}
              Both STRIDE and MAESTRO — full coverage for systems with AI/ML components.
            {/if}
          </p>
        </div>
      </div>

    {:else if step === 1}
      <div class="space-y-3">
        <div>
          <label class="{LABEL_CLASS}" for="description">System description</label>
          <textarea id="description" bind:value={description} rows="6"
            placeholder="Describe your system architecture, components, data flows, and trust boundaries. The more detail you provide, the more targeted the threat model will be."
            class="{INPUT_CLASS} resize-none animate-blink"></textarea>
          <p class="mt-1 font-mono text-[11px] {description.trim().length < 10 ? 'text-c-critical' : 'text-c-faint'}">
            {description.trim().length} chars (min 10)
          </p>
        </div>

        {#if description.trim().length >= 80}
          <div class="rounded-panel border px-3 py-2.5 space-y-1.5
            {descriptionGaps.length === 0 ? 'border-c-green/30 bg-c-green/5' : 'border-c-high/30 bg-c-high/5'}">
            {#if descriptionGaps.length === 0}
              <p class="text-xs font-medium text-c-green flex items-center gap-1.5">
                <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>
                Description looks complete
              </p>
            {:else}
              <p class="text-xs font-medium text-c-high">Coverage gaps detected — consider adding:</p>
              <ul class="space-y-1">
                {#each descriptionGaps as gap}
                  <li class="text-xs text-c-muted flex items-start gap-1.5">
                    <svg class="w-3 h-3 mt-0.5 flex-shrink-0 text-c-high" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
                    <span><span class="font-medium text-c-text2">{gap.field}:</span> {gap.message}</span>
                  </li>
                {/each}
              </ul>
            {/if}
          </div>
        {/if}

        {#if description.trim().length >= 200}
          <PreFlightPanel title="Description coverage (AI)" loading={llmAnalysisLoading} gaps={llmDescriptionGaps} collapsed={true} />
        {/if}
      </div>

    {:else if step === 2}
      <div class="space-y-4">
        <div>
          <label class="{LABEL_CLASS}" for="file-diagram">Architecture diagram <span class="text-c-faint font-normal normal-case">(optional)</span></label>
          <input id="file-diagram" type="file" accept=".png,.jpg,.jpeg,.mmd,.txt"
            on:change={handleDiagramChange}
            class="block w-full text-sm text-c-muted file:mr-3 file:py-1.5 file:px-3 file:rounded-panel file:border file:border-c-border file:text-xs file:font-medium file:bg-c-well file:text-c-text2 hover:file:bg-c-panel" />
          <p class="mt-1 text-xs text-c-faint">PNG/JPG (max 5 MB) or Mermaid .mmd file.</p>
        </div>
        {#if diagramPreview}
          <img src={diagramPreview} alt="Diagram preview" class="max-h-48 rounded-panel border border-c-border object-contain" />
        {:else if diagramFile}
          <div class="flex items-center gap-2 text-sm text-c-muted bg-c-well border border-c-border rounded-panel px-3 py-2">
            <svg class="w-4 h-4 text-c-faint" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clip-rule="evenodd"/></svg>
            {diagramFile.name}
          </div>
        {/if}
      </div>

    {:else if step === 3}
      <div class="space-y-4">
        <div class="flex items-center justify-between">
          <p class="text-sm font-medium text-c-text2">Code context <span class="text-c-faint font-normal">(optional)</span></p>
          <div class="flex items-center gap-3">
            <button type="button" on:click={() => { sourcesLoaded = false }}
              class="text-xs text-c-muted hover:text-c-text" title="Refresh source list">Refresh</button>
            <a href="/sources" use:link class="text-xs text-c-accent hover:underline">Manage sources</a>
          </div>
        </div>
        <p class="text-xs text-c-muted">Select an indexed code repository to give the pipeline additional context.</p>

        {#if loadingSources}
          <p class="text-sm text-c-faint py-4 text-center">Loading sources…</p>
        {:else if readySources.length === 0}
          <div class="rounded-panel border border-c-border bg-c-well px-4 py-6 text-center space-y-1">
            <p class="text-sm text-c-muted">No indexed sources available.</p>
            <a href="/sources" use:link class="text-xs text-c-accent hover:underline">Add a repository on the Sources page →</a>
          </div>
        {:else}
          <div class="space-y-2">
            <label class="flex items-center gap-3 p-3 rounded-panel border cursor-pointer transition-colors
              {selectedCodeSourceId === null ? 'border-c-accent/40 bg-c-accent/5' : 'border-c-border hover:bg-c-well'}">
              <input type="radio" bind:group={selectedCodeSourceId} value={null} class="text-c-accent" />
              <div>
                <p class="text-sm font-medium text-c-text2">None</p>
                <p class="text-xs text-c-faint">No code context</p>
              </div>
            </label>
            {#each readySources as src (src.id)}
              <label class="flex items-center gap-3 p-3 rounded-panel border cursor-pointer transition-colors
                {selectedCodeSourceId === src.id ? 'border-c-accent/40 bg-c-accent/5' : 'border-c-border hover:bg-c-well'}">
                <input type="radio" bind:group={selectedCodeSourceId} value={src.id} class="text-c-accent" />
                <div class="min-w-0">
                  <p class="text-sm font-medium text-c-text2">{src.name}</p>
                  <p class="font-mono text-xs text-c-faint truncate">{src.git_url}{src.ref ? ` @ ${src.ref}` : ''}</p>
                </div>
              </label>
            {/each}
          </div>
        {/if}
      </div>

    {:else if step === 4}
      <div class="space-y-3">
        <p class="text-sm font-medium text-c-text2">Assumptions <span class="text-c-faint font-normal">(optional)</span></p>
        <p class="text-xs text-c-muted">List existing security controls, scope boundaries, and focus areas.</p>
        <div class="flex gap-2">
          <input type="text" bind:value={newAssumption}
            placeholder="e.g. TLS 1.3 enforced on all client connections"
            on:keydown={e => e.key === 'Enter' && addAssumption()}
            class="flex-1 field" />
          <button type="button" on:click={addAssumption} class="btn-ghost text-xs px-3">Add</button>
        </div>
        {#if assumptions.length > 0}
          <ul class="space-y-1">
            {#each assumptions as a, i}
              <li class="flex items-center justify-between bg-c-well border border-c-border rounded-panel px-3 py-1.5 text-sm text-c-text2">
                {a}
                <button type="button" on:click={() => removeAssumption(i)}
                  class="text-c-faint hover:text-c-critical ml-2 transition-colors">
                  <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
                </button>
              </li>
            {/each}
          </ul>
        {/if}

        {#if description.trim().length >= 200}
          <PreFlightPanel title="Assumptions coverage (AI)" loading={llmAnalysisLoading} gaps={llmAssumptionsGaps} />
        {/if}
      </div>

    {:else if step === 5}
      <div class="space-y-4">
        <div>
          <label class="{LABEL_CLASS}" for="iterations">
            Iteration count: <span class="text-c-accent font-semibold font-mono">{iterationCount}</span>
          </label>
          <input id="iterations" type="range" min="1" max="15" bind:value={iterationCount}
            class="w-full accent-c-accent mt-2" />
          <div class="flex justify-between font-mono text-[11px] text-c-faint mt-1">
            <span>1 — Quick</span>
            <span>15 — Thorough</span>
          </div>
        </div>
        <p class="text-xs text-c-muted">Each iteration runs gap analysis and generates additional threats. More iterations = broader coverage, longer runtime.</p>
      </div>

    {:else if step === 6}
      <div class="space-y-4">
        {#if framework === 'MAESTRO' || framework === 'HYBRID'}
          <div class="rounded-panel border border-c-accent/30 bg-c-accent/5 px-4 py-3 text-sm text-c-accent">
            {#if framework === 'MAESTRO'}
              MAESTRO framework already generates AI/ML-specific threats exclusively.
            {:else}
              HYBRID framework generates threats with both STRIDE and MAESTRO categories in a single pass.
            {/if}
          </div>
        {:else}
          <label class="flex items-start gap-3 cursor-pointer">
            <input type="checkbox" bind:checked={hasAiComponents}
              class="mt-0.5 h-4 w-4 rounded border-c-border text-c-accent focus:ring-c-accent" />
            <div>
              <p class="text-sm font-medium text-c-text2">System includes AI/ML components</p>
              <p class="text-xs text-c-muted mt-0.5">Enables MAESTRO threat generation alongside STRIDE: model inversion, prompt injection, data poisoning, and other AI-specific risks.</p>
            </div>
          </label>
        {/if}
      </div>

    {:else if step === 7}
      <div class="space-y-4">
        <h3 class="text-sm font-semibold text-c-text">Ready to run</h3>

        {#if providerKeyMissing}
          <div class="rounded-panel border border-c-high/40 bg-c-high/5 px-4 py-3 space-y-2">
            <div class="flex items-start gap-2">
              <svg class="w-4 h-4 text-c-high mt-0.5 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
              <div>
                <p class="text-sm font-medium text-c-high">No API key configured for {providerLabel}</p>
                <p class="text-xs text-c-muted mt-0.5">The pipeline can't reach {providerLabel} without a key. Add one in Settings, then come back to run.</p>
              </div>
            </div>
            <a href="/settings" use:link class="inline-block text-xs font-medium text-c-accent hover:underline">Open Settings →</a>
          </div>
        {/if}

        <dl class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <dt class="text-c-muted">Title</dt>
          <dd class="text-c-text font-medium truncate">{title}</dd>
          <dt class="text-c-muted">Framework</dt>
          <dd class="font-mono text-c-text2">{framework}</dd>
          <dt class="text-c-muted">Iterations</dt>
          <dd class="font-mono text-c-text2">{iterationCount}</dd>
          <dt class="text-c-muted">AI components</dt>
          <dd class="text-c-text2">{hasAiComponents ? 'Yes (MAESTRO enabled)' : 'No'}</dd>
          <dt class="text-c-muted">Diagram</dt>
          <dd class="text-c-text2">{diagramFile ? diagramFile.name : '—'}</dd>
          <dt class="text-c-muted">Code source</dt>
          <dd class="text-c-text2">{selectedCodeSourceId ? (readySources.find(s => s.id === selectedCodeSourceId)?.name ?? '—') : '—'}</dd>
          <dt class="text-c-muted">Assumptions</dt>
          <dd class="text-c-text2">{assumptions.length > 0 ? assumptions.length + ' added' : '—'}</dd>
        </dl>

        {#if llmDescriptionGaps.length > 0 || llmAssumptionsGaps.length > 0 || llmAnalysisLoading}
          <div class="space-y-2 pt-2 border-t border-c-border">
            <p class="text-xs font-medium text-c-muted">Pre-flight analysis</p>
            <PreFlightPanel title="Description" loading={llmAnalysisLoading} gaps={llmDescriptionGaps} collapsed={llmDescriptionGaps.length === 0} />
            <PreFlightPanel title="Assumptions" loading={llmAnalysisLoading} gaps={llmAssumptionsGaps} collapsed={llmAssumptionsGaps.length === 0} />
          </div>
        {/if}

        <div class="flex items-start gap-3 pt-2 border-t border-c-border">
          <input id="strict-mode" type="checkbox" bind:checked={strictMode}
            class="mt-0.5 h-4 w-4 rounded border-c-border text-c-accent focus:ring-c-accent" />
          <label for="strict-mode" class="cursor-pointer">
            <p class="text-sm font-medium text-c-text2">Block run on error-severity gaps</p>
            <p class="text-xs text-c-muted mt-0.5">When enabled, the Run button is disabled if the AI analysis found any error-severity gaps.</p>
          </label>
        </div>

        {#if strictBlocked}
          <p class="text-xs text-c-critical font-medium">✗ Run blocked — fix the error-severity gaps above or disable strict mode.</p>
        {/if}

        <p class="text-xs text-c-faint pt-2 border-t border-c-border">
          The pipeline will run {iterationCount} iteration{iterationCount !== 1 ? 's' : ''} of threat generation. You'll see live progress on the next screen.
        </p>
      </div>
    {/if}
  </Wizard>
</div>
