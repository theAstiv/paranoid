<script>
  import { onMount } from 'svelte'
  import { getConfig, getHealth } from '../lib/api.js'
  import { config, notify } from '../lib/stores.js'
  import McpConfig from '../components/McpConfig.svelte'

  let health = null
  let loading = true

  onMount(async () => {
    try {
      const [cfg, h] = await Promise.all([
        getConfig(),
        getHealth().catch(() => null),
      ])
      config.set(cfg)
      health = h
    } catch (err) {
      notify('error', `Failed to load config: ${err.message}`)
    } finally {
      loading = false
    }
  })
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

    <!-- Config -->
    {#if $config}
      <div class="bg-white rounded-xl border border-slate-200 p-5">
        <h2 class="text-sm font-semibold text-slate-700 mb-3">Configuration</h2>
        <dl class="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
          <dt class="text-slate-500">Default provider</dt>
          <dd class="text-slate-700">{$config.default_provider ?? '—'}</dd>
          <dt class="text-slate-500">Default model</dt>
          <dd class="font-mono text-slate-700 truncate">{$config.model ?? '—'}</dd>
          <dt class="text-slate-500">Default iterations</dt>
          <dd class="text-slate-700">{$config.default_iterations ?? '—'}</dd>
          <dt class="text-slate-500">Iteration range</dt>
          <dd class="text-slate-700">{$config.min_iteration_count ?? '—'} – {$config.max_iteration_count ?? '—'}</dd>
          <dt class="text-slate-500">Ollama URL</dt>
          <dd class="font-mono text-slate-700 truncate text-xs">{$config.ollama_base_url ?? '—'}</dd>
          <dt class="text-slate-500">Similarity threshold</dt>
          <dd class="font-mono text-slate-700">{$config.similarity_threshold ?? '—'}</dd>
          <dt class="text-slate-500">Log level</dt>
          <dd class="text-slate-700">{$config.log_level ?? '—'}</dd>
        </dl>
        <p class="text-xs text-slate-400 mt-3">Configuration is set via environment variables. Restart the backend to apply changes.</p>
      </div>
    {/if}

    <!-- Env var reference -->
    <div class="bg-white rounded-xl border border-slate-200 p-5">
      <h2 class="text-sm font-semibold text-slate-700 mb-3">Environment Variables</h2>
      <div class="space-y-2">
        {#each [
          ['ANTHROPIC_API_KEY', 'Anthropic API key for Claude models'],
          ['OPENAI_API_KEY', 'OpenAI API key for GPT models'],
          ['OLLAMA_BASE_URL', 'Ollama server URL (default: http://host.docker.internal:11434)'],
          ['DEFAULT_PROVIDER', 'anthropic | openai | ollama'],
          ['DEFAULT_MODEL', 'Model identifier (e.g. claude-sonnet-4-20250514)'],
          ['DEFAULT_ITERATIONS', '1–15 (default: 3)'],
          ['DB_PATH', 'SQLite path (default: ./data/paranoid.db)'],
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
