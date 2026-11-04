<script>
  import { push } from 'svelte-spa-router'
  import { currentUser, authLoading, notify } from '../lib/stores.js'
  import { listAllUsers, register } from '../lib/api.js'
  import { relativeTime } from '../lib/utils.js'

  let users = []
  let loading = true
  let fetched = false

  // Create user: the way accounts are made with PARANOID_REGISTRATION=admin_only.
  // Not Register.svelte, which signs in as the new user and would end this session.
  let showCreate = false
  let creating = false
  let draft = { username: '', email: '', password: '', display_name: '' }

  async function createUser() {
    creating = true
    try {
      const { display_name, ...rest } = draft
      const user = await register({ ...rest, display_name: display_name.trim() || undefined })
      users = [...users, user]
      notify('success', `Created user @${user.username}`)
      draft = { username: '', email: '', password: '', display_name: '' }
      showCreate = false
    } catch (err) {
      notify('error', `Failed to create user: ${err.message}`)
    } finally {
      creating = false
    }
  }

  // Wait for auth to resolve before checking — $currentUser is null while
  // authLoading is true, so checking too early causes a false redirect.
  $: if (!$authLoading) {
    if (!$currentUser?.is_admin) {
      push('/')
    } else if (!fetched) {
      fetched = true
      fetchUsers()
    }
  }

  async function fetchUsers() {
    try {
      users = await listAllUsers()
    } catch (err) {
      notify('error', `Failed to load users: ${err.message}`)
    } finally {
      loading = false
    }
  }
</script>

<div class="max-w-[1120px] mx-auto space-y-5">
  <div class="flex items-center gap-3">
    <h1 class="text-xl font-semibold text-c-text">Users</h1>
    <span class="font-mono text-[11px] px-2 py-0.5 rounded-chip border chip-violet">ADMIN</span>
    {#if !loading}
      <span class="font-mono text-[11px] text-c-faint ml-auto">
        {users.length} user{users.length !== 1 ? 's' : ''}
      </span>
      <button type="button" class="btn-ghost text-xs px-3 py-1.5" on:click={() => { showCreate = !showCreate }}>
        {showCreate ? 'Cancel' : 'Create user'}
      </button>
    {/if}
  </div>

  {#if showCreate}
    <form class="card p-5 grid grid-cols-1 sm:grid-cols-2 gap-4" on:submit|preventDefault={createUser}>
      <div>
        <label for="new-username" class="block text-xs font-medium text-c-muted mb-1">Username</label>
        <input id="new-username" class="field w-full" bind:value={draft.username} required
          minlength="3" maxlength="50" pattern="[a-zA-Z0-9_\-]+" autocomplete="off" />
      </div>
      <div>
        <label for="new-display" class="block text-xs font-medium text-c-muted mb-1">Display name <span class="text-c-faint">optional</span></label>
        <input id="new-display" class="field w-full" bind:value={draft.display_name} maxlength="100" autocomplete="off" />
      </div>
      <div>
        <label for="new-email" class="block text-xs font-medium text-c-muted mb-1">Email</label>
        <input id="new-email" type="email" class="field w-full" bind:value={draft.email} required autocomplete="off" />
      </div>
      <div>
        <label for="new-password" class="block text-xs font-medium text-c-muted mb-1">Initial password <span class="text-c-faint">min 8; they can change it</span></label>
        <input id="new-password" type="password" class="field w-full" bind:value={draft.password} required minlength="8" autocomplete="new-password" />
      </div>
      <div class="sm:col-span-2 flex justify-end">
        <button type="submit" class="btn-primary text-sm px-4 disabled:opacity-50" disabled={creating}>
          {creating ? 'Creating…' : 'Create'}
        </button>
      </div>
    </form>
  {/if}

  {#if loading}
    <div class="flex justify-center py-16">
      <div class="w-6 h-6 border-2 border-c-accent border-t-transparent rounded-full animate-spin-slow"></div>
    </div>

  {:else}
    <div class="card overflow-hidden">
      {#if users.length === 0}
        <div class="px-5 py-12 text-center text-sm text-c-faint">No users registered.</div>
      {:else}
        <table class="w-full">
          <thead>
            <tr class="border-b border-c-border bg-c-well/30">
              <th class="text-left text-xs font-semibold text-c-muted uppercase tracking-wide px-5 py-3">User</th>
              <th class="text-left text-xs font-semibold text-c-muted uppercase tracking-wide px-5 py-3 hidden sm:table-cell">Email</th>
              <th class="text-left text-xs font-semibold text-c-muted uppercase tracking-wide px-5 py-3">Role</th>
              <th class="text-left text-xs font-semibold text-c-muted uppercase tracking-wide px-5 py-3 hidden lg:table-cell">Last login</th>
              <th class="text-left text-xs font-semibold text-c-muted uppercase tracking-wide px-5 py-3 hidden lg:table-cell">Joined</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-c-divider">
            {#each users as user (user.id)}
              <tr class="hover:bg-c-well/50 transition-colors">
                <td class="px-5 py-3">
                  <div>
                    <p class="text-sm font-medium text-c-text2">
                      {user.display_name || user.username}
                      {#if user.id === $currentUser?.id}
                        <span class="font-mono text-[10px] text-c-faint ml-1">(you)</span>
                      {/if}
                    </p>
                    <p class="font-mono text-[11px] text-c-faint">@{user.username}</p>
                  </div>
                </td>
                <td class="px-5 py-3 hidden sm:table-cell">
                  <span class="font-mono text-xs text-c-muted">{user.email}</span>
                </td>
                <td class="px-5 py-3">
                  <div class="flex items-center gap-1.5 flex-wrap">
                    {#if user.is_admin}
                      <span class="font-mono text-[11px] px-2 py-0.5 rounded-chip border chip-violet">admin</span>
                    {:else}
                      <span class="font-mono text-[11px] px-2 py-0.5 rounded-chip border chip-gray">member</span>
                    {/if}
                    {#if !user.is_active}
                      <span class="font-mono text-[11px] px-2 py-0.5 rounded-chip border chip-red">inactive</span>
                    {/if}
                  </div>
                </td>
                <td class="px-5 py-3 hidden lg:table-cell">
                  <span class="font-mono text-xs text-c-faint">
                    {user.last_login_at ? relativeTime(user.last_login_at) : 'never'}
                  </span>
                </td>
                <td class="px-5 py-3 hidden lg:table-cell">
                  <span class="font-mono text-xs text-c-faint">{relativeTime(user.created_at)}</span>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>
  {/if}
</div>
