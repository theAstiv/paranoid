<script>
  import { push } from 'svelte-spa-router'
  import Wizard from '../components/Wizard.svelte'
  import { createModel, subscribeToRun } from '../lib/api.js'
  import { getModel } from '../lib/api.js'
  import { notify, pipelineEvents, pipelineRunning, threats, currentModel, abortRun } from '../lib/stores.js'

  const STEPS = ['Title & Framework', 'Description', 'Diagram', 'Assumptions', 'Iterations', 'AI Components', 'Review & Run']

  let step = 0
  let submitting = false

  // Step 1
  let title = ''
  let framework = 'STRIDE'

  // Step 2
  let description = ''

  // Step 3
  let diagramFile = null
  let diagramPreview = null

  // Step 4
  let assumptions = []
  let newAssumption = ''

  // Step 5
  let iterationCount = 3

  // Step 6
  let hasAiComponents = false

  // Client-side gap regexes mirror backend/pipeline/pre_flight.py so the wizard
  // can flag gaps before the model is created (and before /analyze is reachable).
  // Backend is authoritative at run time; keep these in sync when editing.
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
      const model = await createModel({
        title: title.trim(),
        description: description.trim(),
        framework,
        iteration_count: iterationCount,
      })

      // Build FormData now — diagramFile is a File object that only exists in this
      // component's scope. We must start the SSE stream BEFORE navigating away so
      // the File reference stays alive. Results.svelte checks $pipelineRunning on
      // mount and skips triggering a second run.
      const fd = new FormData()
      fd.append('assumptions', JSON.stringify(assumptions))
      fd.append('has_ai_components', String(hasAiComponents))
      if (diagramFile) fd.append('diagram', diagramFile)

      // Reset run state, then start the SSE stream
      pipelineEvents.set([])
      pipelineRunning.set(true)
      const modelId = model.id

      const abort = subscribeToRun(
        modelId,
        fd,
        evt => {
          pipelineEvents.update(es => [...es, evt])
          if (evt.step === 'complete' && evt.data?.threats?.threats) {
            threats.set(evt.data.threats.threats)
          }
        },
        err => {
          notify('error', `Pipeline error: ${err.message}`)
          pipelineRunning.set(false)
        },
        async () => {
          pipelineRunning.set(false)
          // Refresh model so Results page picks up final state
          try {
            const refreshed = await getModel(modelId)
            currentModel.set(refreshed)
            threats.set(refreshed.threats ?? [])
          } catch { /* ignore */ }
        },
      )

      // Store abort so Results.onDestroy can cancel if user navigates away
      abortRun.set(abort)

      await push(`/models/${model.id}`)
    } catch (err) {
      notify('error', `Failed to create model: ${err.message}`)
      pipelineRunning.set(false)
      submitting = false
    }
  }
</script>

<div class="max-w-2xl mx-auto">
  <h1 class="text-2xl font-semibold text-slate-900 mb-6">New Threat Model</h1>

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
      <!-- Title + Framework -->
      <div class="space-y-5">
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="title">Model title</label>
          <input
            id="title"
            type="text"
            bind:value={title}
            maxlength="200"
            placeholder="e.g. Payment Gateway, Auth Service"
            class="block w-full rounded-md border-slate-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
          />
          <p class="mt-1 text-xs text-slate-400">{title.length}/200</p>
        </div>
        <div>
          <p class="block text-sm font-medium text-slate-700 mb-2">Threat framework</p>
          <div class="flex gap-4">
            {#each ['STRIDE', 'MAESTRO', 'HYBRID'] as fw}
              <label class="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  bind:group={framework}
                  value={fw}
                  class="text-indigo-600 focus:ring-indigo-500"
                />
                <span class="text-sm font-medium text-slate-700">{fw}</span>
              </label>
            {/each}
          </div>
          <p class="mt-2 text-xs text-slate-500">
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
      <!-- Description -->
      <div class="space-y-3">
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="description">System description</label>
          <textarea
            id="description"
            bind:value={description}
            rows="6"
            placeholder="Describe your system architecture, components, data flows, and trust boundaries. The more detail you provide, the more targeted the threat model will be."
            class="block w-full rounded-md border-slate-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm resize-none"
          ></textarea>
          <p class="mt-1 text-xs {description.trim().length < 10 ? 'text-red-400' : 'text-slate-400'}">
            {description.trim().length} chars (min 10)
          </p>
        </div>

        <!-- Pre-flight gap panel (shows once description is long enough to analyze) -->
        {#if description.trim().length >= 80}
          <div class="rounded-lg border {descriptionGaps.length === 0 ? 'border-green-200 bg-green-50' : 'border-yellow-200 bg-yellow-50'} px-3 py-2.5 space-y-1.5">
            {#if descriptionGaps.length === 0}
              <p class="text-xs font-medium text-green-700 flex items-center gap-1.5">
                <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>
                Description looks complete
              </p>
            {:else}
              <p class="text-xs font-medium text-yellow-800">Coverage gaps detected — consider adding:</p>
              <ul class="space-y-1">
                {#each descriptionGaps as gap}
                  <li class="text-xs text-yellow-700 flex items-start gap-1.5">
                    <svg class="w-3 h-3 mt-0.5 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
                    <span><span class="font-medium">{gap.field}:</span> {gap.message}</span>
                  </li>
                {/each}
              </ul>
            {/if}
          </div>
        {/if}
      </div>

    {:else if step === 2}
      <!-- Diagram (optional) -->
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="file-diagram">Architecture diagram <span class="text-slate-400 font-normal">(optional)</span></label>
          <input
            id="file-diagram"
            type="file"
            accept=".png,.jpg,.jpeg,.mmd,.txt"
            on:change={handleDiagramChange}
            class="block w-full text-sm text-slate-500 file:mr-3 file:py-1.5 file:px-3 file:rounded file:border-0 file:text-sm file:font-medium file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100"
          />
          <p class="mt-1 text-xs text-slate-400">PNG/JPG (max 5 MB) or Mermaid .mmd file. Vision-capable providers will analyze the diagram directly.</p>
        </div>
        {#if diagramPreview}
          <img src={diagramPreview} alt="Diagram preview" class="max-h-48 rounded-lg border border-slate-200 object-contain" />
        {:else if diagramFile}
          <div class="flex items-center gap-2 text-sm text-slate-600 bg-slate-50 rounded-md px-3 py-2">
            <svg class="w-4 h-4 text-slate-400" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clip-rule="evenodd"/></svg>
            {diagramFile.name}
          </div>
        {/if}
      </div>

    {:else if step === 3}
      <!-- Assumptions (optional) -->
      <div class="space-y-3">
        <p class="text-sm font-medium text-slate-700">Assumptions <span class="text-slate-400 font-normal">(optional)</span></p>
        <p class="text-xs text-slate-500">Add constraints or assumptions already in place (e.g. "TLS enforced", "Auth via OAuth2").</p>
        <div class="flex gap-2">
          <input
            type="text"
            bind:value={newAssumption}
            placeholder="e.g. TLS 1.3 enforced"
            on:keydown={e => e.key === 'Enter' && addAssumption()}
            class="flex-1 rounded-md border-slate-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
          />
          <button type="button" on:click={addAssumption}
            class="px-3 py-2 text-sm font-medium text-indigo-700 bg-indigo-50 rounded-md hover:bg-indigo-100">
            Add
          </button>
        </div>
        {#if assumptions.length > 0}
          <ul class="space-y-1">
            {#each assumptions as a, i}
              <li class="flex items-center justify-between bg-slate-50 rounded px-3 py-1.5 text-sm">
                {a}
                <button type="button" on:click={() => removeAssumption(i)}
                  class="text-slate-400 hover:text-red-500 ml-2">
                  <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
                </button>
              </li>
            {/each}
          </ul>
        {/if}
      </div>

    {:else if step === 4}
      <!-- Iterations -->
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1" for="iterations">
            Iteration count: <span class="text-indigo-600 font-semibold">{iterationCount}</span>
          </label>
          <input
            id="iterations"
            type="range"
            min="1"
            max="15"
            bind:value={iterationCount}
            class="w-full accent-indigo-600"
          />
          <div class="flex justify-between text-xs text-slate-400 mt-1">
            <span>1 — Quick</span>
            <span>15 — Thorough</span>
          </div>
        </div>
        <p class="text-xs text-slate-500">
          Each iteration runs gap analysis and generates additional threats. More iterations = broader coverage, longer runtime.
        </p>
      </div>

    {:else if step === 5}
      <!-- AI Components -->
      <div class="space-y-4">
        {#if framework === 'MAESTRO' || framework === 'HYBRID'}
          <div class="rounded-lg bg-teal-50 border border-teal-200 px-4 py-3 text-sm text-teal-800">
            {#if framework === 'MAESTRO'}
              MAESTRO framework already generates AI/ML-specific threats exclusively. This option only applies to STRIDE.
            {:else}
              HYBRID framework generates threats with both STRIDE and MAESTRO categories in a single pass. This option only applies to STRIDE.
            {/if}
          </div>
        {:else}
          <label class="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              bind:checked={hasAiComponents}
              class="mt-0.5 h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
            />
            <div>
              <p class="text-sm font-medium text-slate-700">System includes AI/ML components</p>
              <p class="text-xs text-slate-500 mt-0.5">
                Enables MAESTRO threat generation alongside STRIDE: model inversion, prompt injection, data poisoning, and other AI-specific risks. Threats from both frameworks are deduplicated and merged.
              </p>
            </div>
          </label>
        {/if}
      </div>

    {:else if step === 6}
      <!-- Review & Run -->
      <div class="space-y-4">
        <h3 class="text-sm font-semibold text-slate-700">Ready to run</h3>
        <dl class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <dt class="text-slate-500">Title</dt>
          <dd class="text-slate-900 font-medium truncate">{title}</dd>
          <dt class="text-slate-500">Framework</dt>
          <dd class="text-slate-900">{framework}</dd>
          <dt class="text-slate-500">Iterations</dt>
          <dd class="text-slate-900">{iterationCount}</dd>
          <dt class="text-slate-500">AI components</dt>
          <dd class="text-slate-900">{hasAiComponents ? 'Yes (MAESTRO enabled)' : 'No'}</dd>
          <dt class="text-slate-500">Diagram</dt>
          <dd class="text-slate-900">{diagramFile ? diagramFile.name : '—'}</dd>
          <dt class="text-slate-500">Assumptions</dt>
          <dd class="text-slate-900">{assumptions.length > 0 ? assumptions.length + ' added' : '—'}</dd>
        </dl>
        <p class="text-xs text-slate-500 pt-2 border-t border-slate-100">
          The pipeline will run {iterationCount} iteration{iterationCount !== 1 ? 's' : ''} of threat generation. You'll see live progress on the next screen.
        </p>
      </div>
    {/if}
  </Wizard>
</div>
