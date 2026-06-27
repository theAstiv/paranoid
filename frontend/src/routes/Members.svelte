<script>
  import { currentProject, currentUser, notify } from '../lib/stores.js'
  import {
    listProjectMembers,
    updateProjectMember,
    removeProjectMember,
    createProjectInvitation,
    listProjectInvitations,
    declineInvitation,
  } from '../lib/api.js'
  import { initials, relativeTime } from '../lib/utils.js'

  let members = []
  let invitations = []
  let loading = true
  let inviteEmail = ''
  let inviteRole = 'viewer'
  let inviting = false

  $: projectId = $currentProject?.id
  // member_role comes from the SQL alias in list_projects_for_user
  $: canManage = $currentProject?.member_role === 'owner' || $currentUser?.is_admin

  // Re-load whenever the active project changes (sidebar switch)
  $: if (projectId) loadAll()

  async function loadAll() {
    loading = true
    try {
      const [m, inv] = await Promise.all([
        listProjectMembers(projectId),
        canManage ? listProjectInvitations(projectId) : Promise.resolve([]),
      ])
      members = m
      invitations = inv.filter(i => i.status === 'pending')
    } catch (err) {
      notify('error', `Failed to load members: ${err.message}`)
    } finally {
      loading = false
    }
  }

  async function handleInvite() {
    if (!inviteEmail.trim()) return
    inviting = true
    try {
      const inv = await createProjectInvitation(projectId, {
        invited_email: inviteEmail.trim(),
        role: inviteRole,
      })
      invitations = [inv, ...invitations]
      inviteEmail = ''
      notify('success', `Invitation sent to ${inv.invited_email}`)
    } catch (err) {
      notify('error', `Invite failed: ${err.message}`)
    } finally {
      inviting = false
    }
  }

  async function handleRoleChange(member, newRole) {
    if (newRole === member.role) return
    if (newRole === 'owner' && !confirm(`Promote ${member.display_name || member.username} to owner? Owners can add/remove members and archive the project.`)) return
    try {
      const updated = await updateProjectMember(projectId, member.user_id, { role: newRole })
      members = members.map(m => m.user_id === member.user_id ? { ...m, role: updated.role } : m)
    } catch (err) {
      notify('error', `Role update failed: ${err.message}`)
    }
  }

  async function handleRemove(member) {
    if (!confirm(`Remove ${member.display_name || member.username} from this project?`)) return
    try {
      await removeProjectMember(projectId, member.user_id)
      members = members.filter(m => m.user_id !== member.user_id)
      notify('success', 'Member removed.')
    } catch (err) {
      notify('error', `Remove failed: ${err.message}`)
    }
  }

  async function handleRevoke(inv) {
    try {
      await declineInvitation(inv.id)
      invitations = invitations.filter(i => i.id !== inv.id)
      notify('success', 'Invitation revoked.')
    } catch (err) {
      notify('error', `Revoke failed: ${err.message}`)
    }
  }

  const ROLE_CHIP = {
    owner: 'chip-accent',
    editor: 'chip-blue',
    viewer: 'chip-gray',
  }
</script>

<div class="max-w-[920px] mx-auto space-y-5">
  <div class="flex items-center justify-between">
    <div>
      <p class="font-mono text-[10px] tracking-[1px] text-c-faint uppercase mb-1">
        {$currentProject?.name ?? 'Project'}
      </p>
      <h1 class="text-xl font-semibold text-c-text">Members</h1>
    </div>
    {#if !loading}
      <span class="font-mono text-[11px] text-c-faint">
        {members.length} member{members.length !== 1 ? 's' : ''}
      </span>
    {/if}
  </div>

  {#if !projectId}
    <div class="card p-8 text-center text-sm text-c-muted">No project selected.</div>

  {:else if loading}
    <div class="flex justify-center py-16">
      <div class="w-6 h-6 border-2 border-c-accent border-t-transparent rounded-full animate-spin-slow"></div>
    </div>

  {:else}
    <!-- Invite form (owner / admin only) -->
    {#if canManage}
      <div class="card p-5">
        <h2 class="text-xs font-semibold text-c-muted uppercase tracking-wide mb-4">Invite member</h2>
        <div class="flex gap-3 flex-wrap sm:flex-nowrap">
          <input
            type="email"
            bind:value={inviteEmail}
            placeholder="colleague@example.com"
            class="flex-1 field text-sm min-w-0"
          />
          <select bind:value={inviteRole} class="field text-sm w-28 flex-shrink-0">
            <option value="viewer">Viewer</option>
            <option value="editor">Editor</option>
            <option value="owner">Owner</option>
          </select>
          <button
            type="button"
            on:click={handleInvite}
            disabled={inviting || !inviteEmail.trim()}
            class="btn-primary text-sm px-4 flex-shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {inviting ? 'Sending…' : 'Send invite'}
          </button>
        </div>
      </div>
    {/if}

    <!-- Current members -->
    <div class="card overflow-hidden">
      <div class="px-5 py-3 border-b border-c-border">
        <span class="text-xs font-semibold text-c-muted uppercase tracking-wide">Current members</span>
      </div>
      {#if members.length === 0}
        <div class="px-5 py-10 text-center text-sm text-c-faint">No members found.</div>
      {:else}
        <ul class="divide-y divide-c-divider">
          {#each members as member (member.user_id)}
            <li class="flex items-center gap-4 px-5 py-3">
              <!-- Avatar -->
              <div class="w-8 h-8 rounded-full bg-c-accent/20 border border-c-accent/40 flex items-center justify-center flex-shrink-0">
                <span class="font-mono text-[11px] font-semibold text-c-accent">
                  {initials(member.display_name || member.username || '?')}
                </span>
              </div>

              <!-- Identity -->
              <div class="flex-1 min-w-0">
                <p class="text-sm font-medium text-c-text2 truncate">
                  {member.display_name || member.username}
                  {#if member.user_id === $currentUser?.id}
                    <span class="font-mono text-[10px] text-c-faint ml-1">(you)</span>
                  {/if}
                </p>
                <p class="font-mono text-[11px] text-c-faint truncate">{member.email}</p>
              </div>

              <!-- Role: editable select for non-owners when canManage, else chip -->
              {#if canManage && member.role !== 'owner'}
                <select
                  value={member.role}
                  on:change={(e) => handleRoleChange(member, e.target.value)}
                  class="field text-xs py-1 w-28 flex-shrink-0"
                >
                  <option value="viewer">Viewer</option>
                  <option value="editor">Editor</option>
                  <option value="owner">Owner</option>
                </select>
              {:else}
                <span class="inline-flex font-mono text-[11px] px-2 py-0.5 rounded-chip border flex-shrink-0 {ROLE_CHIP[member.role] ?? 'chip-gray'}">
                  {member.role}
                </span>
              {/if}

              <!-- Remove (can't remove yourself or if no canManage) -->
              {#if canManage && member.user_id !== $currentUser?.id}
                <button
                  type="button"
                  on:click={() => handleRemove(member)}
                  class="p-1.5 rounded text-c-faint hover:text-c-critical hover:bg-c-critical/10 transition-colors flex-shrink-0"
                  title="Remove member"
                >
                  <svg class="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
                    <path d="M6 6l8 8M14 6l-8 8"/>
                  </svg>
                </button>
              {:else}
                <div class="w-7 flex-shrink-0"></div>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    </div>

    <!-- Pending invitations (owner / admin only) -->
    {#if canManage}
      <div class="card overflow-hidden">
        <div class="px-5 py-3 border-b border-c-border flex items-center gap-2">
          <span class="text-xs font-semibold text-c-muted uppercase tracking-wide">Pending invitations</span>
          {#if invitations.length > 0}
            <span class="font-mono text-[11px] text-c-faint">({invitations.length})</span>
          {/if}
        </div>
        {#if invitations.length === 0}
          <div class="px-5 py-8 text-center text-sm text-c-faint">No pending invitations.</div>
        {:else}
          <ul class="divide-y divide-c-divider">
            {#each invitations as inv (inv.id)}
              <li class="flex items-center gap-4 px-5 py-3">
                <div class="flex-1 min-w-0">
                  <p class="font-mono text-sm text-c-text2 truncate">{inv.invited_email}</p>
                  <p class="font-mono text-[11px] text-c-faint mt-0.5">
                    Sent {relativeTime(inv.created_at)}
                  </p>
                </div>
                <span class="inline-flex font-mono text-[11px] px-2 py-0.5 rounded-chip border flex-shrink-0 {ROLE_CHIP[inv.role] ?? 'chip-gray'}">
                  {inv.role}
                </span>
                <span class="inline-flex font-mono text-[11px] px-2 py-0.5 rounded-chip border chip-amber flex-shrink-0">
                  pending
                </span>
                <button
                  type="button"
                  on:click={() => handleRevoke(inv)}
                  class="text-xs text-c-faint hover:text-c-critical transition-colors flex-shrink-0"
                >
                  Revoke
                </button>
              </li>
            {/each}
          </ul>
        {/if}
      </div>
    {/if}
  {/if}
</div>
