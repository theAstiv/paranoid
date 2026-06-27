<script>
  import { onMount, tick } from 'svelte'
  import { getConfig, updateConfig, getHealth, testProvider } from '../lib/api.js'
  import { config, notify } from '../lib/stores.js'
  import McpConfig from '../components/McpConfig.svelte'

  $: firstRun = $config?.first_run === true
  let providerSelect
  let autoFocusedOnce = false

  $: if (!loading && firstRun && !autoFocusedOnce) {
    autoFocusedOnce = true
    tick().then(() => providerSelect?.focus())
  }

  let health = null
  let loading = true
  let saving = false
  let configSecret = ''
  let configSecretRequired = false

  let keys = {
    anthropic: { set: false, source: null, input: '', replacing: false, clearPending: false, testing: false, testResult: null },
    openai:    { set: false, source: null, input: '', replacing: false, clearPending: false, testing: false, testResult: null },
  }

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
      const [cfg, h] = await Promise.all([getConfig(), getHealth().catch(() => null)])
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
      anthropic: { set: cfg.anthropic_api_key_set ?? false, source: cfg.anthropic_api_key_source ?? null, input: '', replacing: false, clearPending: false, testing: false, testResult: null },
      openai:    { set: cfg.openai_api_key_set ?? false, source: cfg.openai_api_key_source ?? null, input: '', replacing: false, clearPending: false, testing: false, testResult: null },
    }
  }

  async function runTest(provider, apiKey) {
    keys[provider] = { ...keys[provider], testing: true, testResult: null }
    try {
      const payload = { provider }
      if (apiKey) payload.api_key = apiKey
      if (provider === 'anthropic' && draft.model) payload.model = draft.model
      if (provider === 'ollama' && draft.ollama_base_url) payload.ollama_base_url = draft.ollama_base_url
      const result = await testProvider(payload)
      keys[provider] = { ...keys[provider], testing: false, testResult: result }
    } catch (err) {
      keys[provider] = { ...keys[provider], testing: false, testResult: { ok: false, error: 'request_failed', message: err.message, latency_ms: 0 } }
    }
  }

  function testButtonClick(provider) {
    runTest(provider, keys[provider].input?.trim() || null)
  }

  function startReplace(provider) { keys[provider] = { ...keys[provider], replacing: true, clearPending: false, input: '' } }
  function cancelReplace(provider) { keys[provider] = { ...keys[provider], replacing: false, clearPending: false, input: '' } }
  function markClear(provider) { keys[provider] = { ...keys[provider], clearPending: true, replacing: false, input: '' } }

  function buildKeyPayload(provider) {
    const state = keys[provider]
    const field = `${provider}_api_key`
    if (state.source === 'env') return {}
    if (state.clearPending) return { [field]: null }
    if (state.input && state.input.trim() !== '') return { [field]: state.input.trim() }
    return {}
  }

  async function save() {
    saving = true
    const changedProviders = ['anthropic', 'openai'].filter(p => keys[p].input && keys[p].input.trim() !== '')
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

  const FIELD_CLASS = 'field w-full'
  const LABEL_CLASS = 'text-sm text-c-muted text-right'
  const SUBLABEL_CLASS = 'block text-xs text-c-faint font-normal'
</script>

<div class="max-w-[760px] mx-auto space-y-5">
  <h1 class="text-xl font-semibold text-c-text">Settings</h1>

  {#if firstRun && !loading}
    <div role="status" aria-live="polite"
      class="card border-c-high/40 bg-c-high/5 p-4 text-sm">
      <p class="font-semibold text-c-high">Welcome — let's get you connected.</p>
      <p class="mt-1 text-c-muted">
        Paranoid needs at least one provider configured before it can generate threat models.
        Pick a provider below and paste an API key — or switch to Ollama if you run models locally.
        Your key is encrypted before it touches disk.
      </p>
    </div>
  {/if}

  {#if loading}
    <div class="flex justify-center py-16">
      <div class="w-6 h-6 border-2 border-c-accent border-t-transparent rounded-full animate-spin-slow"></div>
    </div>
  {:else}
    <!-- Health status -->
    <div class="card p-5">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-xs font-semibold text-c-muted uppercase tracking-wide">Status</h2>
        {#if health}
          <span class="flex items-center gap-1.5 font-mono text-xs font-medium {health.status === 'healthy' ? 'text-c-green' : 'text-c-critical'}">
            <span class="w-2 h-2 rounded-full {health.status === 'healthy' ? 'bg-c-green animate-pulse-dot' : 'bg-c-critical'}"></span>
            {health.status ?? 'unknown'}
          </span>
        {:else}
          <span class="font-mono text-xs text-c-faint">Backend unreachable</span>
        {/if}
      </div>
      {#if health}
        <dl class="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
          <dt class="text-c-muted">Version</dt>
          <dd class="font-mono text-c-text2">{health.version ?? '—'}</dd>
          <dt class="text-c-muted">Provider</dt>
          <dd class="text-c-text2">{health.provider ?? '—'}</dd>
          <dt class="text-c-muted">Model</dt>
          <dd class="font-mono text-c-text2 truncate">{health.model ?? '—'}</dd>
        </dl>
      {/if}
    </div>

    <!-- Configuration -->
    <div class="card p-5">
      <div class="flex items-center justify-between mb-5">
        <h2 class="text-xs font-semibold text-c-muted uppercase tracking-wide">Configuration</h2>
        <span class="text-xs text-c-faint">Changes take effect immediately</span>
      </div>

      <form on:submit|preventDefault={save} class="space-y-4">
        <div class="grid grid-cols-3 items-center gap-4">
          <label for="cfg-provider" class="{LABEL_CLASS}">Provider</label>
          <select id="cfg-provider" bind:this={providerSelect} bind:value={draft.default_provider}
            class="col-span-2 field">
            <option value="anthropic">anthropic</option>
            <option value="openai">openai</option>
            <option value="ollama">ollama</option>
          </select>
        </div>

        <div class="grid grid-cols-3 items-center gap-4">
          <label for="cfg-model" class="{LABEL_CLASS}">Main model</label>
          <input id="cfg-model" type="text" bind:value={draft.model}
            placeholder="e.g. claude-sonnet-4-20250514"
            class="col-span-2 {FIELD_CLASS} font-mono" />
        </div>

        <div class="grid grid-cols-3 items-center gap-4">
          <label for="cfg-fast-model" class="{LABEL_CLASS}">
            Fast model
            <span class="{SUBLABEL_CLASS}">extraction &amp; enrichment</span>
          </label>
          <input id="cfg-fast-model" type="text" bind:value={draft.fast_model}
            placeholder="e.g. claude-haiku-4-5-20251001"
            class="col-span-2 {FIELD_CLASS} font-mono" />
        </div>

        <div class="grid grid-cols-3 items-center gap-4">
          <label for="cfg-iters" class="{LABEL_CLASS}">Default iterations</label>
          <input id="cfg-iters" type="number" min="1" max="15" bind:value={draft.default_iterations}
            class="col-span-2 w-24 {FIELD_CLASS}" />
        </div>

        <div class="grid grid-cols-3 items-center gap-4">
          <label for="cfg-sim" class="{LABEL_CLASS}">
            Similarity threshold
            <span class="{SUBLABEL_CLASS}">dedup cutoff 0–1</span>
          </label>
          <input id="cfg-sim" type="number" min="0" max="1" step="0.01" bind:value={draft.similarity_threshold}
            class="col-span-2 w-24 {FIELD_CLASS}" />
        </div>

        <div class="grid grid-cols-3 items-center gap-4">
          <label for="cfg-ollama" class="{LABEL_CLASS}">Ollama URL</label>
          <input id="cfg-ollama" type="url" bind:value={draft.ollama_base_url}
            placeholder="http://host.docker.internal:11434"
            class="col-span-2 {FIELD_CLASS} font-mono" />
        </div>

        <!-- API keys -->
        {#each [['anthropic', 'Anthropic', 'ANTHROPIC_API_KEY'], ['openai', 'OpenAI', 'OPENAI_API_KEY']] as [prov, label, envName]}
          <div class="grid grid-cols-3 items-start gap-4">
            <label for={`cfg-${prov}-key`} class="{LABEL_CLASS} pt-2">
              {label} key
              <span class="{SUBLABEL_CLASS}">
                {#if keys[prov].source === 'env'}managed via env
                {:else if keys[prov].clearPending}will be cleared on save
                {:else if keys[prov].set && !keys[prov].replacing}stored (encrypted)
                {:else}paste to save{/if}
              </span>
            </label>

            <div class="col-span-2 space-y-1.5">
              <div class="flex items-center gap-2">
                {#if keys[prov].source === 'env'}
                  <input id={`cfg-${prov}-key`} type="password" value="••••••••" disabled
                    class="flex-1 field opacity-50 cursor-not-allowed" />
                  <span class="font-mono text-[11px] text-c-faint" title={`Managed by ${envName} env var`}>🔒 env</span>
                {:else if keys[prov].set && !keys[prov].replacing && !keys[prov].clearPending}
                  <input id={`cfg-${prov}-key`} type="password" value="••••••••" disabled
                    class="flex-1 field opacity-50" />
                  <button type="button" on:click={() => startReplace(prov)}
                    class="text-xs font-medium text-c-accent hover:underline">Replace</button>
                  <button type="button" on:click={() => markClear(prov)}
                    class="text-xs font-medium text-c-muted hover:text-c-critical transition-colors">Clear</button>
                {:else if keys[prov].clearPending}
                  <input id={`cfg-${prov}-key`} type="password" value="" disabled
                    class="flex-1 bg-c-input border border-c-critical/40 rounded-panel px-3 py-1.5 text-sm font-mono text-c-critical opacity-70" />
                  <button type="button" on:click={() => cancelReplace(prov)}
                    class="text-xs font-medium text-c-muted hover:text-c-text2 transition-colors">Undo</button>
                {:else}
                  <input id={`cfg-${prov}-key`} type="password" bind:value={keys[prov].input}
                    placeholder={prov === 'anthropic' ? 'sk-ant-…' : 'sk-…'}
                    autocomplete="off"
                    class="flex-1 {FIELD_CLASS} font-mono" />
                  {#if keys[prov].set}
                    <button type="button" on:click={() => cancelReplace(prov)}
                      class="text-xs font-medium text-c-muted hover:text-c-text2 transition-colors">Cancel</button>
                  {/if}
                {/if}

                {#if keys[prov].set || (keys[prov].input && keys[prov].input.trim() !== '')}
                  <button type="button" on:click={() => testButtonClick(prov)}
                    disabled={keys[prov].testing}
                    class="text-xs font-medium text-c-muted hover:text-c-accent transition-colors disabled:opacity-50">
                    {keys[prov].testing ? 'Testing…' : 'Test'}
                  </button>
                {/if}
              </div>

              {#if keys[prov].testResult}
                <div class="font-mono text-[11px]">
                  {#if keys[prov].testResult.ok}
                    <span class="text-c-green">✓ Connected ({keys[prov].testResult.latency_ms} ms)</span>
                  {:else}
                    <span class="text-c-critical">✗ {keys[prov].testResult.message || keys[prov].testResult.error || 'Connection failed'}</span>
                  {/if}
                </div>
              {/if}
            </div>
          </div>
        {/each}

        {#if configSecretRequired}
          <div class="grid grid-cols-3 items-center gap-4">
            <label for="cfg-secret" class="{LABEL_CLASS}">
              Config secret
              <span class="{SUBLABEL_CLASS}">required — CONFIG_SECRET is set</span>
            </label>
            <input id="cfg-secret" type="password" bind:value={configSecret}
              placeholder="enter CONFIG_SECRET value"
              class="col-span-2 {FIELD_CLASS} font-mono" />
          </div>
        {/if}

        <div class="flex items-center justify-end gap-3 pt-2 border-t border-c-border">
          <button type="button" on:click={reset}
            class="btn-ghost text-xs px-3 py-1.5">Reset</button>
          <button type="submit" disabled={saving}
            class="btn-primary text-xs px-4 py-1.5 disabled:opacity-50">
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>
    </div>

    <!-- Env var reference -->
    <div class="card p-5">
      <h2 class="text-xs font-semibold text-c-muted uppercase tracking-wide mb-4">Environment Variables</h2>
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
          ['CONFIG_SECRET', 'If set, also stretched into the Fernet key that encrypts API keys. Rotating invalidates all stored keys.'],
          ['ALLOWED_ORIGINS', 'Concrete origins (no *) allowed to issue mutating requests. Empty disables CSRF.'],
        ] as [key, desc]}
          <div class="flex items-start gap-3">
            <code class="flex-shrink-0 font-mono text-[11px] bg-c-well border border-c-border px-2 py-0.5 rounded text-c-accent">{key}</code>
            <span class="text-xs text-c-muted">{desc}</span>
          </div>
        {/each}
      </div>
    </div>

    <!-- MCP / Code context -->
    <div>
      <h2 class="text-xs font-semibold text-c-muted uppercase tracking-wide mb-3">Code Context (context-link)</h2>
      <McpConfig />
    </div>
  {/if}
</div>
