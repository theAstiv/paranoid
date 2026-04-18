<script>
  import { onMount } from 'svelte'
  import { getConfig, updateConfig, getHealth, testProvider } from '../lib/api.js'
  import { config, notify } from '../lib/stores.js'
  import McpConfig from '../components/McpConfig.svelte'

  let health = null
  let loading = true
  let saving = false
  // Not persisted — user re-enters if needed. Only sent when CONFIG_SECRET is set on backend.
  let configSecret = ''
  let configSecretRequired = false

  // API-key UI state. `input` holds a new value the user is typing.
  // `replacing` toggles between the masked "••••••••" display and the
  // editable input when a key is already stored. `clearPending` is set
  // when the user clicks "Clear" — saves send null to delete the DB row.
  // `testing` / `testResult` drive the per-provider "Test connection"
  // spinner + badge. testResult is {ok, latency_ms, error, message} | null.
  let keys = {
    anthropic: { set: false, source: null, input: '', replacing: false, clearPending: false, testing: false, testResult: null },
    openai:    { set: false, source: null, input: '', replacing: false, clearPending: false, testing: false, testResult: null },
  }

  // Local draft — only committed on "Save"
  let draft = {
    default_provider: 'anthropic',
    model: '',
    fast_model: '',
    default_iterations: 3,
    similarity_threshold: 0.85,
    ollama_base_url: '',
  }

  onMount(async () => {
    try {
      const [cfg, h] = await Promise.all([
        getConfig(),
        getHealth().catch(() => null),
      ])
      config.set(cfg)
      health = h
      configSecretRequired = cfg.config_secret_required ?? false
      syncDraft(cfg)
    } catch (err) {
      notify('error', `Failed to load config: ${err.message}`)
    } finally {
      loading = false
    }
  })

  function syncDraft(cfg) {
    draft = {
      default_provider: cfg.default_provider ?? 'anthropic',
      model: cfg.model ?? '',
      fast_model: cfg.fast_model ?? '',
      default_iterations: cfg.default_iterations ?? 3,
      similarity_threshold: cfg.similarity_threshold ?? 0.85,
      ollama_base_url: cfg.ollama_base_url ?? '',
    }
    keys = {
      anthropic: {
        set: cfg.anthropic_api_key_set ?? false,
        source: cfg.anthropic_api_key_source ?? null,
        input: '', replacing: false, clearPending: false, testing: false, testResult: null,
      },
      openai: {
        set: cfg.openai_api_key_set ?? false,
        source: cfg.openai_api_key_source ?? null,
        input: '', replacing: false, clearPending: false, testing: false, testResult: null,
      },
    }
  }

  async function runTest(provider, apiKey) {
    // When the user just pasted a key, test with that value (not what's
    // in the DB yet). Otherwise the backend falls back to env/DB.
    keys[provider] = { ...keys[provider], testing: true, testResult: null }
    try {
      const payload = { provider }
      if (apiKey) payload.api_key = apiKey
      if (provider === 'anthropic' && draft.model) payload.model = draft.model
      if (provider === 'ollama' && draft.ollama_base_url) payload.ollama_base_url = draft.ollama_base_url
      const result = await testProvider(payload)
      keys[provider] = { ...keys[provider], testing: false, testResult: result }
    } catch (err) {
      keys[provider] = {
        ...keys[provider],
        testing: false,
        testResult: { ok: false, error: 'request_failed', message: err.message, latency_ms: 0 },
      }
    }
  }

  function testButtonClick(provider) {
    const state = keys[provider]
    // Prefer the live input (unsaved new value); otherwise let the backend
    // resolve env → DB.  Env-locked provider still tests the env-sourced key.
    runTest(provider, state.input?.trim() || null)
  }

  function startReplace(provider) {
    keys[provider] = { ...keys[provider], replacing: true, clearPending: false, input: '' }
  }
  function cancelReplace(provider) {
    keys[provider] = { ...keys[provider], replacing: false, clearPending: false, input: '' }
  }
  function markClear(provider) {
    keys[provider] = { ...keys[provider], clearPending: true, replacing: false, input: '' }
  }

  function buildKeyPayload(provider) {
    // Returns either { [field]: value } or {}. Using bracket-notation lets
    // JSON serialise an explicit null to clear the DB value.
    const state = keys[provider]
    const field = `${provider}_api_key`
    if (state.source === 'env') return {}
    if (state.clearPending) return { [field]: null }
    if (state.input && state.input.trim() !== '') return { [field]: state.input.trim() }
    return {}
  }

  async function save() {
    saving = true
    // Capture which providers are about to get a new key so we can auto-
    // test them after the PATCH succeeds (spec: "auto-runs on save if key
    // value changed").
    const changedProviders = ['anthropic', 'openai'].filter(
      p => keys[p].input && keys[p].input.trim() !== '',
    )
    try {
      const payload = {
        default_provider: draft.default_provider,
        model: draft.model || undefined,
        fast_model: draft.fast_model || undefined,
        default_iterations: Number(draft.default_iterations),
        similarity_threshold: Number(draft.similarity_threshold),
        ollama_base_url: draft.ollama_base_url || undefined,
        ...buildKeyPayload('anthropic'),
        ...buildKeyPayload('openai'),
      }
      const updated = await updateConfig(payload, configSecret || undefined)
      config.set(updated)
      syncDraft(updated)
      notify('success', 'Settings saved')
      // Fire-and-forget — the test result shows up inline below the field.
      for (const p of changedProviders) runTest(p, null)
    } catch (err) {
      notify('error', `Failed to save settings: ${err.message}`)
    } finally {
      saving = false
    }
  }

  function reset() {
    if ($config) syncDraft($config)
  }
</script>

<div class="max-w-2xl mx-auto space-y-6">
  <h1 class="text-2xl font-semibold text-slate-900">Settings</h1>

  {#if loading}
    <div class="flex justify-center py-16">
      <div class="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
    </div>
  {:else}
    <!-- Health status -->
    <div class="bg-white rounded-xl border border-slate-200 p-5">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-sm font-semibold text-slate-700">Status</h2>
        {#if health}
          <span class="flex items-center gap-1.5 text-xs font-medium {health.status === 'healthy' ? 'text-green-700' : 'text-red-700'}">
            <span class="w-2 h-2 rounded-full {health.status === 'healthy' ? 'bg-green-500' : 'bg-red-500'}"></span>
            {health.status ?? 'unknown'}
          </span>
        {:else}
          <span class="text-xs text-slate-400">Backend unreachable</span>
        {/if}
      </div>
      {#if health}
        <dl class="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
          <dt class="text-slate-500">Version</dt>
          <dd class="font-mono text-slate-700">{health.version ?? '—'}</dd>
          <dt class="text-slate-500">Provider</dt>
          <dd class="text-slate-700">{health.provider ?? '—'}</dd>
          <dt class="text-slate-500">Model</dt>
          <dd class="font-mono text-slate-700 truncate">{health.model ?? '—'}</dd>
        </dl>
      {/if}
    </div>

    <!-- Editable configuration -->
    <div class="bg-white rounded-xl border border-slate-200 p-5">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-slate-700">Configuration</h2>
        <span class="text-xs text-slate-400">Changes are active until backend restart</span>
      </div>

      <form on:submit|preventDefault={save} class="space-y-4">
        <!-- Provider -->
        <div class="grid grid-cols-3 items-center gap-4">
          <label for="cfg-provider" class="text-sm text-slate-600 text-right">Provider</label>
          <select
            id="cfg-provider"
            bind:value={draft.default_provider}
            class="col-span-2 border border-slate-300 rounded-md px-3 py-1.5 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-400">
            <option value="anthropic">anthropic</option>
            <option value="openai">openai</option>
            <option value="ollama">ollama</option>
          </select>
        </div>

        <!-- Main model -->
        <div class="grid grid-cols-3 items-center gap-4">
          <label for="cfg-model" class="text-sm text-slate-600 text-right">Main model</label>
          <input
            id="cfg-model"
            type="text"
            bind:value={draft.model}
            placeholder="e.g. claude-sonnet-4-20250514"
            class="col-span-2 border border-slate-300 rounded-md px-3 py-1.5 text-sm font-mono text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-400" />
        </div>

        <!-- Fast model -->
        <div class="grid grid-cols-3 items-center gap-4">
          <label for="cfg-fast-model" class="text-sm text-slate-600 text-right">Fast model
            <span class="block text-xs text-slate-400 font-normal">extraction &amp; enrichment</span>
          </label>
          <input
            id="cfg-fast-model"
            type="text"
            bind:value={draft.fast_model}
            placeholder="e.g. claude-haiku-4-5-20251001"
            class="col-span-2 border border-slate-300 rounded-md px-3 py-1.5 text-sm font-mono text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-400" />
        </div>

        <!-- Default iterations -->
        <div class="grid grid-cols-3 items-center gap-4">
          <label for="cfg-iters" class="text-sm text-slate-600 text-right">Default iterations</label>
          <input
            id="cfg-iters"
            type="number"
            min="1"
            max="15"
            bind:value={draft.default_iterations}
            class="col-span-2 w-24 border border-slate-300 rounded-md px-3 py-1.5 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-400" />
        </div>

        <!-- Similarity threshold -->
        <div class="grid grid-cols-3 items-center gap-4">
          <label for="cfg-sim" class="text-sm text-slate-600 text-right">Similarity threshold
            <span class="block text-xs text-slate-400 font-normal">dedup cutoff 0–1</span>
          </label>
          <input
            id="cfg-sim"
            type="number"
            min="0"
            max="1"
            step="0.01"
            bind:value={draft.similarity_threshold}
            class="col-span-2 w-24 border border-slate-300 rounded-md px-3 py-1.5 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-400" />
        </div>

        <!-- Ollama URL (always shown, only effective when provider = ollama) -->
        <div class="grid grid-cols-3 items-center gap-4">
          <label for="cfg-ollama" class="text-sm text-slate-600 text-right">Ollama URL</label>
          <input
            id="cfg-ollama"
            type="url"
            bind:value={draft.ollama_base_url}
            placeholder="http://host.docker.internal:11434"
            class="col-span-2 border border-slate-300 rounded-md px-3 py-1.5 text-sm font-mono text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-400" />
        </div>

        <!-- API keys — per provider. Env-sourced keys are locked; DB-sourced
             keys show a masked placeholder with a Replace button. -->
        {#each [['anthropic', 'Anthropic', 'ANTHROPIC_API_KEY'], ['openai', 'OpenAI', 'OPENAI_API_KEY']] as [prov, label, envName]}
          <div class="grid grid-cols-3 items-center gap-4">
            <label for={`cfg-${prov}-key`} class="text-sm text-slate-600 text-right">
              {label} API key
              <span class="block text-xs text-slate-400 font-normal">
                {#if keys[prov].source === 'env'}
                  managed via env
                {:else if keys[prov].clearPending}
                  will be cleared on save
                {:else if keys[prov].set && !keys[prov].replacing}
                  stored (encrypted)
                {:else}
                  paste to save
                {/if}
              </span>
            </label>

            <div class="col-span-2 flex items-center gap-2">
              {#if keys[prov].source === 'env'}
                <input
                  id={`cfg-${prov}-key`}
                  type="password"
                  value="••••••••"
                  disabled
                  aria-describedby={`cfg-${prov}-key-lock`}
                  class="flex-1 border border-slate-300 rounded-md px-3 py-1.5 text-sm font-mono bg-slate-100 text-slate-400 cursor-not-allowed"
                />
                <span id={`cfg-${prov}-key-lock`} class="text-xs text-slate-400" title={`Managed by ${envName} environment variable`}>🔒 env</span>
              {:else if keys[prov].set && !keys[prov].replacing && !keys[prov].clearPending}
                <input
                  id={`cfg-${prov}-key`}
                  type="password"
                  value="••••••••"
                  disabled
                  class="flex-1 border border-slate-300 rounded-md px-3 py-1.5 text-sm font-mono bg-slate-50 text-slate-400"
                />
                <button type="button" on:click={() => startReplace(prov)}
                  class="text-xs font-medium text-indigo-600 hover:text-indigo-800">Replace</button>
                <button type="button" on:click={() => markClear(prov)}
                  class="text-xs font-medium text-slate-500 hover:text-red-600">Clear</button>
              {:else if keys[prov].clearPending}
                <input
                  id={`cfg-${prov}-key`}
                  type="password"
                  value=""
                  disabled
                  class="flex-1 border border-red-300 rounded-md px-3 py-1.5 text-sm font-mono bg-red-50 text-red-500"
                />
                <button type="button" on:click={() => cancelReplace(prov)}
                  class="text-xs font-medium text-slate-500 hover:text-slate-700">Undo</button>
              {:else}
                <input
                  id={`cfg-${prov}-key`}
                  type="password"
                  bind:value={keys[prov].input}
                  placeholder={prov === 'anthropic' ? 'sk-ant-…' : 'sk-…'}
                  autocomplete="off"
                  class="flex-1 border border-slate-300 rounded-md px-3 py-1.5 text-sm font-mono text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-400"
                />
                {#if keys[prov].set}
                  <button type="button" on:click={() => cancelReplace(prov)}
                    class="text-xs font-medium text-slate-500 hover:text-slate-700">Cancel</button>
                {/if}
              {/if}

              {#if keys[prov].set || (keys[prov].input && keys[prov].input.trim() !== '')}
                <button type="button" on:click={() => testButtonClick(prov)}
                  disabled={keys[prov].testing}
                  aria-label={`Test ${label} connection`}
                  class="text-xs font-medium text-slate-500 hover:text-indigo-600 disabled:opacity-50">
                  {keys[prov].testing ? 'Testing…' : 'Test'}
                </button>
              {/if}
            </div>

            {#if keys[prov].testResult}
              <div class="col-start-2 col-span-2 text-xs">
                {#if keys[prov].testResult.ok}
                  <span class="text-green-700">✓ Connected ({keys[prov].testResult.latency_ms} ms)</span>
                {:else}
                  <span class="text-red-700">✗ {keys[prov].testResult.message || keys[prov].testResult.error || 'Connection failed'}</span>
                {/if}
              </div>
            {/if}
          </div>
        {/each}

        <!-- Config secret (only shown / required when backend has CONFIG_SECRET set) -->
        {#if configSecretRequired}
        <div class="grid grid-cols-3 items-center gap-4">
          <label for="cfg-secret" class="text-sm text-slate-600 text-right">Config secret
            <span class="block text-xs text-slate-400 font-normal">required — CONFIG_SECRET is set</span>
          </label>
          <input
            id="cfg-secret"
            type="password"
            bind:value={configSecret}
            placeholder="enter CONFIG_SECRET value"
            class="col-span-2 border border-slate-300 rounded-md px-3 py-1.5 text-sm font-mono text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-400" />
        </div>
        {/if}

        <!-- Actions -->
        <div class="flex items-center justify-end gap-3 pt-2">
          <button
            type="button"
            on:click={reset}
            class="px-3 py-1.5 text-xs font-medium text-slate-600 bg-slate-100 rounded-md hover:bg-slate-200 transition-colors">
            Reset
          </button>
          <button
            type="submit"
            disabled={saving}
            class="px-4 py-1.5 text-xs font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:opacity-50 transition-colors">
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>
    </div>

    <!-- Env var reference -->
    <div class="bg-white rounded-xl border border-slate-200 p-5">
      <h2 class="text-sm font-semibold text-slate-700 mb-3">Environment Variables</h2>
      <div class="space-y-2">
        {#each [
          ['ANTHROPIC_API_KEY', 'Anthropic API key for Claude models'],
          ['OPENAI_API_KEY', 'OpenAI API key for GPT models'],
          ['OLLAMA_BASE_URL', 'Ollama server URL (default: http://host.docker.internal:11434)'],
          ['DEFAULT_PROVIDER', 'anthropic | openai | ollama'],
          ['DEFAULT_MODEL', 'Main model identifier (e.g. claude-sonnet-4-20250514)'],
          ['FAST_MODEL', 'Fast model for extraction & enrichment (default: claude-haiku-4-5-20251001)'],
          ['DEFAULT_ITERATIONS', '1–15 (default: 3)'],
          ['DB_PATH', 'SQLite path (default: ./data/paranoid.db)'],
          ['SIMILARITY_THRESHOLD', 'Dedup cosine threshold (default: 0.85)'],
          ['CONFIG_SECRET', 'If set, also stretched into the Fernet key that encrypts API keys stored in the config DB. Rotating invalidates all stored keys.'],
          ['ALLOWED_ORIGINS', 'Concrete origins (no *) allowed to issue mutating requests. Default: http://localhost:8000,http://127.0.0.1:8000. Empty disables CSRF.'],
        ] as [key, desc]}
          <div class="flex items-start gap-3">
            <code class="flex-shrink-0 font-mono text-xs bg-slate-50 border border-slate-200 px-2 py-0.5 rounded text-slate-700">{key}</code>
            <span class="text-xs text-slate-500">{desc}</span>
          </div>
        {/each}
      </div>
    </div>

    <!-- MCP / Code context -->
    <div>
      <h2 class="text-sm font-semibold text-slate-700 mb-3">Code Context (context-link)</h2>
      <McpConfig />
    </div>
  {/if}
</div>
