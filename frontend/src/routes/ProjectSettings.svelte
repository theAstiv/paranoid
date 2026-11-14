<script>
  import { currentProject, currentUser, projects, notify } from '../lib/stores.js'
  import { getProject, updateProject, archiveProject, unarchiveProject } from '../lib/api.js'

  let loading = true
  let saving = false

  let draft = {
    default_provider: '',
    default_model: '',
    default_iterations: '',
    default_temperature: '',
    staleness_threshold_days: '',
  }

  $: projectId = $currentProject?.id
  $: canManage = $currentProject?.member_role === 'owner' || $currentUser?.is_admin
  $: archived = !!$currentProject?.is_archived

  // An archived project is read-only (BB-50): settings wait for unarchive.
  async function setArchived(value) {
    if (value && !confirm('Archive this project? It becomes read-only until an owner restores it.')) return
    saving = true
    try {
      const updated = value
        ? (await archiveProject(projectId), { ...$currentProject, is_archived: 1 })
        : { ...$currentProject, ...(await unarchiveProject(projectId)) }
      currentProject.set(updated)
      projects.update(list => list.map(p => (p.id === updated.id ? { ...p, is_archived: updated.is_archived } : p)))
      notify('success', value ? 'Project archived.' : 'Project restored.')
    } catch (err) {
      notify('error', `${value ? 'Archive' : 'Restore'} failed: ${err.message}`)
    } finally {
      saving = false
    }
  }

  // Re-load whenever the active project changes (sidebar switch)
  $: if (projectId) loadProject()

  async function loadProject() {
    loading = true
    try {
      const proj = await getProject(projectId)
      draft = {
        default_provider: proj.default_provider ?? '',
        default_model: proj.default_model ?? '',
        default_iterations: proj.default_iterations ?? '',
        default_temperature: proj.default_temperature ?? '',
        staleness_threshold_days: proj.staleness_threshold_days ?? 30,
      }
    } catch (err) {
      notify('error', `Failed to load project settings: ${err.message}`)
    } finally {
      loading = false
    }
  }

  // A cleared number input binds null, not '': Number(null) sent 0 (BB-132).
  const numberOrNull = v => (v === '' || v == null ? null : Number(v))

  async function save() {
    saving = true
    try {
      // null = inherit the instance default; the server clears the override.
      const body = {
        default_provider: draft.default_provider || null,
        default_model: draft.default_model || null,
        default_iterations: numberOrNull(draft.default_iterations),
        default_temperature: numberOrNull(draft.default_temperature),
      }
      // The threshold has no instance default to fall back to: blank keeps it.
      const staleness = numberOrNull(draft.staleness_threshold_days)
      if (staleness !== null) body.staleness_threshold_days = staleness
      const updated = await updateProject(projectId, body)
      currentProject.update(p => ({ ...p, ...updated }))
      notify('success', 'Project defaults saved.')
    } catch (err) {
      notify('error', `Save failed: ${err.message}`)
    } finally {
      saving = false
    }
  }

  const LABEL_CLASS = 'text-sm text-c-muted text-right'
  const SUBLABEL_CLASS = 'block text-xs text-c-faint font-normal'
  const FIELD_CLASS = 'field w-full'
</script>

<div class="max-w-[760px] mx-auto space-y-5">
  <div>
    <p class="font-mono text-[10px] tracking-[1px] text-c-faint uppercase mb-1">
      {$currentProject?.name ?? 'Project'}
    </p>
    <h1 class="text-xl font-semibold text-c-text">Project Settings</h1>
  </div>

  {#if !projectId}
    <div class="card p-8 text-center text-sm text-c-muted">No project selected.</div>

  {:else if loading}
    <div class="flex justify-center py-16">
      <div class="w-6 h-6 border-2 border-c-accent border-t-transparent rounded-full animate-spin-slow"></div>
    </div>

  {:else if !canManage}
    <div class="card p-8 text-center text-sm text-c-muted">
      Only project owners can view or change project defaults.
    </div>

  {:else}
    {#if archived}
      <div class="card p-4 border-c-medium/40 text-sm text-c-text2" data-testid="archived-banner">
        This project is archived: everything in it is read-only until it is restored.
      </div>
    {/if}

    <div class="card p-5">
      <div class="flex items-center justify-between mb-5">
        <h2 class="text-xs font-semibold text-c-muted uppercase tracking-wide">Pipeline defaults</h2>
        <span class="text-xs text-c-faint">Blank = inherit instance default</span>
      </div>

      <form on:submit|preventDefault={save} class="space-y-4">
        <div class="grid grid-cols-3 items-center gap-4">
          <label for="proj-provider" class="{LABEL_CLASS}">Provider</label>
          <select id="proj-provider" bind:value={draft.default_provider} class="col-span-2 field">
            <option value="">— inherit —</option>
            <option value="anthropic">anthropic</option>
            <option value="openai">openai</option>
            <option value="ollama">ollama</option>
            <option value="bedrock">bedrock (AWS)</option>
          </select>
        </div>

        <div class="grid grid-cols-3 items-center gap-4">
          <label for="proj-model" class="{LABEL_CLASS}">Model</label>
          <input id="proj-model" type="text" bind:value={draft.default_model}
            placeholder="e.g. claude-sonnet-5-5"
            class="col-span-2 {FIELD_CLASS} font-mono" />
        </div>

        <div class="grid grid-cols-3 items-center gap-4">
          <label for="proj-iters" class="{LABEL_CLASS}">Default iterations</label>
          <input id="proj-iters" type="number" min="1" max="15" bind:value={draft.default_iterations}
            class="col-span-2 w-24 {FIELD_CLASS}" />
        </div>

        <div class="grid grid-cols-3 items-center gap-4">
          <label for="proj-temp" class="{LABEL_CLASS}">
            Temperature
            <span class="{SUBLABEL_CLASS}">0–1, higher = more creative</span>
          </label>
          <input id="proj-temp" type="number" min="0" max="1" step="0.1" bind:value={draft.default_temperature}
            class="col-span-2 w-24 {FIELD_CLASS}" />
        </div>

        <div class="flex justify-end pt-2">
          <button type="submit" disabled={saving || archived}
            class="btn-primary text-sm px-4 disabled:opacity-50 disabled:cursor-not-allowed">
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>
    </div>

    <div class="card p-5">
      <h2 class="text-xs font-semibold text-c-muted uppercase tracking-wide mb-4">Staleness Notifications</h2>
      <div class="grid grid-cols-3 items-start gap-4">
        <label for="proj-staleness" class="{LABEL_CLASS}">
          Threshold (days)
          <span class="{SUBLABEL_CLASS}">Notify members when a completed model hasn't been updated in this many days</span>
        </label>
        <input id="proj-staleness" type="number" min="1" max="365" bind:value={draft.staleness_threshold_days}
          class="col-span-2 w-24 {FIELD_CLASS}" />
      </div>
      <div class="flex justify-end pt-3">
        <button type="button" on:click={save} disabled={saving || archived}
          class="btn-primary text-sm px-4 disabled:opacity-50 disabled:cursor-not-allowed">
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </div>

    <div class="card p-5">
      <h2 class="text-xs font-semibold text-c-muted uppercase tracking-wide mb-2">
        {archived ? 'Restore project' : 'Archive project'}
      </h2>
      <p class="text-xs text-c-faint mb-4">
        {archived
          ? 'Make the project editable again and list it for its members.'
          : "Hide the project from members' lists and make it read-only. Owners can restore it here."}
      </p>
      <div class="flex justify-end">
        <button type="button" on:click={() => setArchived(!archived)} disabled={saving}
          class="btn-ghost text-sm px-4 disabled:opacity-50 disabled:cursor-not-allowed">
          {archived ? 'Unarchive' : 'Archive'}
        </button>
      </div>
    </div>
  {/if}
</div>
