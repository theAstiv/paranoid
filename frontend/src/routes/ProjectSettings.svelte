<script>
  import { currentProject, currentUser, notify } from '../lib/stores.js'
  import { getProject, updateProject } from '../lib/api.js'

  let loading = true
  let saving = false

  let draft = {
    default_provider: '',
    default_model: '',
    default_iterations: '',
    default_temperature: '',
  }

  $: projectId = $currentProject?.id
  $: canManage = $currentProject?.member_role === 'owner' || $currentUser?.is_admin

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
      }
    } catch (err) {
      notify('error', `Failed to load project settings: ${err.message}`)
    } finally {
      loading = false
    }
  }

  async function save() {
    saving = true
    try {
      const body = {
        default_provider: draft.default_provider || null,
        default_model: draft.default_model || null,
        default_iterations: draft.default_iterations === '' ? null : Number(draft.default_iterations),
        default_temperature: draft.default_temperature === '' ? null : Number(draft.default_temperature),
      }
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
          </select>
        </div>

        <div class="grid grid-cols-3 items-center gap-4">
          <label for="proj-model" class="{LABEL_CLASS}">Model</label>
          <input id="proj-model" type="text" bind:value={draft.default_model}
            placeholder="e.g. claude-sonnet-4-20250514"
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
            <span class="{SUBLABEL_CLASS}">0–2, higher = more creative</span>
          </label>
          <input id="proj-temp" type="number" min="0" max="2" step="0.1" bind:value={draft.default_temperature}
            class="col-span-2 w-24 {FIELD_CLASS}" />
        </div>

        <div class="flex justify-end pt-2">
          <button type="submit" disabled={saving}
            class="btn-primary text-sm px-4 disabled:opacity-50 disabled:cursor-not-allowed">
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>
    </div>
  {/if}
</div>
