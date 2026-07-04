<script>
  import { onMount } from 'svelte'
  import { currentUser, currentProject, notify } from '../lib/stores.js'
  import { listAssignees, addAssignee, removeAssignee, listProjectMembers } from '../lib/api.js'
  import { initials } from '../lib/utils.js'

  /** @type {string} */
  export let modelId = ''
  /** @type {string} */
  export let projectId = ''

  let assignees = []
  let members = []
  let loading = true
  let open = false

  $: sameProject = $currentProject?.id === projectId
  $: canAssign = $currentUser?.is_admin
    || (sameProject && ['owner', 'editor'].includes($currentProject?.member_role))

  $: assignedIds = new Set(assignees.map(a => a.user_id))
  $: candidates = members.filter(m => !assignedIds.has(m.user_id))

  onMount(load)

  async function load() {
    loading = true
    try {
      assignees = await listAssignees(modelId)
    } catch (err) {
      notify('error', `Failed to load assignees: ${err.message}`)
    } finally {
      loading = false
    }
  }

  async function openPicker() {
    open = !open
    if (open && projectId && members.length === 0) {
      try {
        members = await listProjectMembers(projectId)
      } catch (err) {
        notify('error', `Failed to load project members: ${err.message}`)
      }
    }
  }

  async function assign(member) {
    try {
      const created = await addAssignee(modelId, { user_id: member.user_id })
      assignees = [...assignees, { ...created, username: member.username, display_name: member.display_name }]
      open = false
    } catch (err) {
      notify('error', `Assign failed: ${err.message}`)
    }
  }

  async function unassign(assignee) {
    try {
      await removeAssignee(modelId, assignee.user_id)
      assignees = assignees.filter(a => a.user_id !== assignee.user_id)
    } catch (err) {
      notify('error', `Unassign failed: ${err.message}`)
    }
  }
</script>

<div class="relative flex items-center">
  <div class="flex items-center -space-x-2">
    {#each assignees as a (a.user_id)}
      <div
        class="group relative w-7 h-7 rounded-full bg-c-accent/20 border-2 border-c-panel ring-1 ring-c-accent/40 flex items-center justify-center"
        title={a.display_name || a.username}
      >
        <span class="font-mono text-[10px] font-semibold text-c-accent">
          {initials(a.display_name || a.username || '?')}
        </span>
        {#if canAssign}
          <button
            type="button"
            on:click={() => unassign(a)}
            class="absolute -top-1 -right-1 hidden group-hover:flex w-4 h-4 rounded-full bg-c-critical items-center justify-center"
            title="Remove assignee"
          >
            <svg class="w-2.5 h-2.5 text-white" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
              <path d="M6 6l8 8M14 6l-8 8"/>
            </svg>
          </button>
        {/if}
      </div>
    {/each}
  </div>

  {#if canAssign}
    <button
      type="button"
      on:click={openPicker}
      class="ml-1.5 w-7 h-7 rounded-full border border-dashed border-c-border text-c-faint hover:text-c-accent hover:border-c-accent flex items-center justify-center flex-shrink-0"
      title="Assign a user"
    >
      <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/>
      </svg>
    </button>
  {/if}

  {#if open}
    <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
    <div class="fixed inset-0 z-10" on:click={() => open = false}></div>
    <div class="absolute left-0 top-full mt-1.5 z-20 w-56 bg-c-panel border border-c-border rounded-panel shadow-xl py-1 animate-pop-in">
      {#if candidates.length === 0}
        <p class="px-3 py-2 text-xs text-c-faint">No unassigned members.</p>
      {:else}
        {#each candidates as m (m.user_id)}
          <button
            type="button"
            on:click={() => assign(m)}
            class="w-full flex items-center gap-2 px-3 py-2 text-sm text-c-text2 hover:bg-c-well hover:text-c-text text-left transition-colors"
          >
            <span class="font-mono text-[10px] text-c-faint w-6 flex-shrink-0">{initials(m.display_name || m.username)}</span>
            <span class="truncate">{m.display_name || m.username}</span>
          </button>
        {/each}
      {/if}
    </div>
  {/if}
</div>
