<script>
  import { onMount } from 'svelte'
  import { getConfig, updateConfig, getHealth } from '../lib/api.js'
  import { config, notify } from '../lib/stores.js'
  import McpConfig from '../components/McpConfig.svelte'

  let health = null
  let loading = true
  let saving = false
  // Not persisted — user re-enters if needed. Only sent when CONFIG_SECRET is set on backend.
  let configSecret = ''
  let configSecretRequired = false

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
  }

  async function save() {
    saving = true
    try {
      const updated = await updateConfig(
        {
          default_provider: draft.default_provider,
          model: draft.model || undefined,
          fast_model: draft.fast_model || undefined,
          default_iterations: Number(draft.default_iterations),
          similarity_threshold: Number(draft.similarity_threshold),
          ollama_base_url: draft.ollama_base_url || undefined,
        },
        configSecret || undefined,
      )
      config.set(updated)
      syncDraft(updated)
      notify('success', 'Settings saved (active until backend restart)')
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
          ['CONFIG_SECRET', 'If set, PATCH /config requires X-Config-Secret header (default: empty = no auth)'],
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
