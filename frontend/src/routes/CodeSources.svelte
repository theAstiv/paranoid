<script>
  import { onMount, onDestroy } from 'svelte'
  import { link } from 'svelte-spa-router'
  import {
    listCodeSources,
    createCodeSource,
    deleteCodeSource,
    reindexSource,
    subscribeToSourceEvents,
  } from '../lib/api.js'
  import { notify } from '../lib/stores.js'

  let sources = []
  let loading = true
  let showAdd = false

  let newName = ''
  let newUrl = ''
  let newRef = ''
  let newPat = ''
  let adding = false

  let aborts = {}
  let lastMsg = {}

  const TERMINAL = new Set(['ready', 'failed'])

  onMount(load)
  onDestroy(() => Object.values(aborts).forEach(f => f()))

  async function load() {
    loading = true
    try {
      sources = await listCodeSources()
      for (const src of sources) {
        if (!TERMINAL.has(src.last_index_status) && !aborts[src.id]) {
          attachSSE(src.id)
        }
      }
    } catch (err) {
      notify('error', `Failed to load code sources: ${err.message}`)
    } finally {
      loading = false
    }
  }

  function attachSSE(id) {
    aborts[id] = subscribeToSourceEvents(
      id,
      (evt) => {
        if (evt.message) lastMsg = { ...lastMsg, [id]: evt.message }
        sources = sources.map(s => s.id === id
          ? { ...s, last_index_status: evt.status, last_index_error: evt.error ?? s.last_index_error }
          : s)
      },
      (err) => console.warn('SSE error for source', id, err),
      () => { const { [id]: _, ...rest } = aborts; aborts = rest },
    )
  }

  async function handleAdd() {
    if (!newName.trim() || !newUrl.trim()) return
    adding = true
    try {
      const src = await createCodeSource({
        name: newName.trim(),
        git_url: newUrl.trim(),
        ref: newRef.trim() || null,
        pat: newPat || null,
      })
      sources = [...sources, src]
      if (!TERMINAL.has(src.last_index_status)) attachSSE(src.id)
      newName = ''; newUrl = ''; newRef = ''; newPat = ''
      showAdd = false
    } catch (err) {
      notify('error', `Failed to add source: ${err.message}`)
    } finally {
      adding = false
    }
  }

  async function handleDelete(id) {
    if (!confirm('Delete this code source and its cloned files?')) return
    try {
      await deleteCodeSource(id)
      if (aborts[id]) { aborts[id](); const { [id]: _, ...rest } = aborts; aborts = rest }
      const { [id]: __, ...msgRest } = lastMsg; lastMsg = msgRest
      sources = sources.filter(s => s.id !== id)
      notify('success', 'Source deleted.')
    } catch (err) {
      notify('error', `Delete failed: ${err.message}`)
    }
  }

  async function handleReindex(id) {
    sources = sources.map(s => s.id === id ? { ...s, last_index_status: 'queued' } : s)
    try {
      const updated = await reindexSource(id)
      sources = sources.map(s => s.id === id ? updated : s)
      if (!aborts[id]) attachSSE(id)
    } catch (err) {
      notify('error', `Reindex failed: ${err.message}`)
      try { sources = await listCodeSources() } catch { /* ignore */ }
    }
  }

  function statusChip(status) {
    switch (status) {
      case 'ready':    return 'chip-green'
      case 'failed':   return 'chip-red'
      case 'cloning':  return 'chip-blue'
      case 'indexing': return 'chip-amber'
      default:         return 'chip-gray'
    }
  }

  function isActive(status) {
    return status !== null && !TERMINAL.has(status)
  }

  const FIELD_CLASS = 'block w-full field text-sm'
</script>

<div class="space-y-5">
  <div class="flex items-center justify-between">
    <div>
      <h1 class="text-xl font-semibold text-c-text">Code Sources</h1>
      <p class="text-sm text-c-muted mt-1">Git repositories cloned and indexed for code context during threat modeling.</p>
    </div>
    <button on:click={() => { showAdd = !showAdd }}
      class="btn-primary text-sm px-3 py-1.5">
      {showAdd ? 'Cancel' : 'Add source'}
    </button>
  </div>

  {#if showAdd}
    <div class="card p-5 space-y-4">
      <h2 class="text-xs font-semibold text-c-muted uppercase tracking-wide">Add repository</h2>
      <div class="grid grid-cols-2 gap-4">
        <div class="col-span-2">
          <label class="block text-xs font-medium text-c-muted mb-1" for="src-url">
            Git URL <span class="text-c-critical">*</span>
          </label>
          <input id="src-url" type="url" bind:value={newUrl}
            placeholder="https://github.com/owner/repo.git"
            class="{FIELD_CLASS} font-mono" />
          <p class="mt-1 text-xs text-c-faint">
            Allowed: github.com, gitlab.com, bitbucket.org. Set
            <code class="font-mono text-c-accent bg-c-well border border-c-border px-1 rounded">ADDITIONAL_GIT_HOSTS</code>
            for private hosts.
          </p>
        </div>
        <div>
          <label class="block text-xs font-medium text-c-muted mb-1" for="src-name">
            Name <span class="text-c-critical">*</span>
          </label>
          <input id="src-name" type="text" bind:value={newName}
            placeholder="e.g. Payment Service" class="{FIELD_CLASS}" />
        </div>
        <div>
          <label class="block text-xs font-medium text-c-muted mb-1" for="src-ref">
            Branch / tag / commit <span class="text-c-faint font-normal">(optional)</span>
          </label>
          <input id="src-ref" type="text" bind:value={newRef}
            placeholder="main" class="{FIELD_CLASS} font-mono" />
        </div>
        <div class="col-span-2">
          <label class="block text-xs font-medium text-c-muted mb-1" for="src-pat">
            Personal access token <span class="text-c-faint font-normal">(optional — private repos only)</span>
          </label>
          <input id="src-pat" type="password" bind:value={newPat}
            placeholder="ghp_••••••••" class="{FIELD_CLASS} font-mono" />
          <p class="mt-1 text-xs text-c-faint">Stored encrypted at rest. Leave blank for public repos.</p>
        </div>
      </div>
      <div class="flex justify-end gap-2 pt-2 border-t border-c-border">
        <button type="button" on:click={() => { showAdd = false }}
          class="btn-ghost text-sm px-3 py-1.5">Cancel</button>
        <button type="button" on:click={handleAdd}
          disabled={adding || !newName.trim() || !newUrl.trim()}
          class="btn-primary text-sm px-3 py-1.5 disabled:opacity-50 disabled:cursor-not-allowed">
          {adding ? 'Adding…' : 'Add & clone'}
        </button>
      </div>
    </div>
  {/if}

  {#if loading}
    <div class="text-sm text-c-faint py-12 text-center">Loading…</div>
  {:else if sources.length === 0}
    <div class="card px-6 py-12 text-center space-y-2">
      <svg class="w-10 h-10 text-c-border mx-auto" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M3 7a2 2 0 012-2h14a2 2 0 012 2v1M3 7v10a2 2 0 002 2h14a2 2 0 002-2V7M3 7h18M8 21v-4a1 1 0 011-1h6a1 1 0 011 1v4"/>
      </svg>
      <p class="text-sm text-c-muted">No code sources yet.</p>
      <p class="text-xs text-c-faint">Add a Git repository to enable code context during threat modeling.</p>
    </div>
  {:else}
    <div class="space-y-3">
      {#each sources as src (src.id)}
        <div class="card p-4">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-sm font-semibold text-c-text2">{src.name}</span>
                <span class="inline-flex items-center gap-1 font-mono text-[11px] px-2 py-0.5 rounded-chip border {statusChip(src.last_index_status)}">
                  {#if isActive(src.last_index_status)}
                    <svg class="w-3 h-3 animate-spin-slow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
                      <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
                    </svg>
                  {/if}
                  {src.last_index_status ?? 'unknown'}
                </span>
                {#if src.has_pat}
                  <span class="inline-flex items-center gap-1 font-mono text-[11px] text-c-faint">
                    <svg class="w-3 h-3" viewBox="0 0 20 20" fill="currentColor">
                      <path fill-rule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clip-rule="evenodd"/>
                    </svg>
                    PAT
                  </span>
                {/if}
              </div>
              <p class="font-mono text-xs text-c-faint mt-0.5 truncate">
                {src.git_url}{src.ref ? ` @ ${src.ref}` : ''}
              </p>
              {#if isActive(src.last_index_status) && lastMsg[src.id]}
                <p class="text-xs text-c-muted mt-1 italic">{lastMsg[src.id]}</p>
              {/if}
              {#if src.last_index_status === 'failed' && src.last_index_error}
                <p class="text-xs text-c-critical mt-1">{src.last_index_error}</p>
              {/if}
            </div>
            <div class="flex items-center gap-1 flex-shrink-0">
              {#if TERMINAL.has(src.last_index_status)}
                <button on:click={() => handleReindex(src.id)} title="Re-clone and re-index"
                  class="p-1.5 rounded text-c-faint hover:text-c-accent hover:bg-c-accent/10 transition-colors">
                  <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/>
                  </svg>
                </button>
              {/if}
              <button on:click={() => handleDelete(src.id)} title="Delete source"
                class="p-1.5 rounded text-c-faint hover:text-c-critical hover:bg-c-critical/10 transition-colors">
                <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="3 6 5 6 21 6"/>
                  <path d="M19 6l-1 14H6L5 6"/>
                  <path d="M10 11v6M14 11v6"/>
                  <path d="M9 6V4h6v2"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
