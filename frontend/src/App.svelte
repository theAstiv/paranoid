<script>
  import { onMount } from 'svelte'
  import { get } from 'svelte/store'
  import Router, { push, location } from 'svelte-spa-router'
  import { link } from 'svelte-spa-router'
  import Home from './routes/Home.svelte'
  import NewModel from './routes/NewModel.svelte'
  import Results from './routes/Results.svelte'
  import Review from './routes/Review.svelte'
  import AttackTree from './routes/AttackTree.svelte'
  import TestCases from './routes/TestCases.svelte'
  import Library from './routes/Library.svelte'
  import Settings from './routes/Settings.svelte'
  import ReviewContext from './routes/ReviewContext.svelte'
  import CodeSources from './routes/CodeSources.svelte'
  import Login from './routes/Login.svelte'
  import Register from './routes/Register.svelte'
  import { config, notification, currentUser, authLoading } from './lib/stores.js'
  import { getConfig, fetchMe, logout } from './lib/api.js'

  const routes = {
    '/': Home,
    '/login': Login,
    '/register': Register,
    '/models/new': NewModel,
    '/models/:id': Results,
    '/models/:id/review': Review,
    '/models/:id/context': ReviewContext,
    '/library': Library,
    '/settings': Settings,
    '/threats/:id/attack-tree': AttackTree,
    '/threats/:id/test-cases': TestCases,
    '/sources': CodeSources,
  }

  let showUserMenu = false

  async function handleLogout() {
    showUserMenu = false
    try { await logout() } catch { /* ignore */ }
    push('/login')
  }

  // Boot sequence: restore session silently, then check first-run config.
  onMount(async () => {
    // Attempt to restore the session from stored token / HttpOnly cookie.
    // fetchMe() sets currentUser and authLoading stores.
    await fetchMe()

    try {
      const cfg = await getConfig()
      config.set(cfg)
      if (cfg.first_run && get(location) !== '/settings') {
        push('/settings')
      }
    } catch (err) {
      console.warn('Config bootstrap failed — first-run redirect skipped.', err)
    }
  })
</script>

<div class="min-h-screen bg-slate-50 text-slate-900">
  <!-- Nav bar -->
  <nav class="bg-white border-b border-slate-200 sticky top-0 z-10">
    <div class="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
      <a href="/" use:link class="flex items-center gap-2 font-semibold text-indigo-600 hover:text-indigo-700">
        <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        </svg>
        Paranoid
      </a>
      <div class="flex items-center gap-6">
        <a href="/" use:link class="text-sm text-slate-600 hover:text-slate-900">Home</a>
        <a href="/library" use:link class="text-sm text-slate-600 hover:text-slate-900">Library</a>
        <a href="/sources" use:link class="text-sm text-slate-600 hover:text-slate-900">Sources</a>
        <a href="/settings" use:link class="text-sm text-slate-600 hover:text-slate-900">Settings</a>
        <a href="/models/new" use:link class="text-sm bg-indigo-600 text-white px-3 py-1.5 rounded-md hover:bg-indigo-700 transition-colors">
          New Model
        </a>

        <!-- User menu (shown when logged in) -->
        {#if $currentUser}
          <div class="relative">
            <button
              on:click={() => showUserMenu = !showUserMenu}
              class="flex items-center gap-1.5 text-sm text-slate-600 hover:text-slate-900"
              aria-label="User menu"
            >
              <span class="w-7 h-7 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-semibold">
                {($currentUser.display_name || $currentUser.username).charAt(0).toUpperCase()}
              </span>
              <svg class="w-3.5 h-3.5 opacity-60" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/>
              </svg>
            </button>

            {#if showUserMenu}
              <!-- svelte-ignore a11y-click-events-have-key-events -->
              <!-- svelte-ignore a11y-no-static-element-interactions -->
              <div
                class="absolute right-0 mt-2 w-48 bg-white rounded-lg shadow-lg border border-gray-200 py-1 z-50"
                on:click|stopPropagation
              >
                <div class="px-4 py-2 border-b border-gray-100">
                  <p class="text-sm font-medium text-gray-900 truncate">{$currentUser.display_name || $currentUser.username}</p>
                  <p class="text-xs text-gray-500 truncate">{$currentUser.email || ''}</p>
                </div>
                <button
                  on:click={handleLogout}
                  class="w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors"
                >
                  Sign out
                </button>
              </div>

              <!-- Click-away overlay -->
              <!-- svelte-ignore a11y-click-events-have-key-events -->
              <!-- svelte-ignore a11y-no-static-element-interactions -->
              <div class="fixed inset-0 z-40" on:click={() => showUserMenu = false}></div>
            {/if}
          </div>
        {:else if !$authLoading}
          <a href="#/login" class="text-sm text-slate-600 hover:text-slate-900">Sign in</a>
        {/if}
      </div>
    </div>
  </nav>

  <!-- Notification banner -->
  {#if $notification}
    <div class="fixed top-16 inset-x-0 z-20 flex justify-center pointer-events-none">
      <div class="pointer-events-auto flex items-center gap-3 px-4 py-2.5 rounded-lg shadow-lg text-sm font-medium
        {$notification.type === 'success' ? 'bg-green-100 text-green-800 border border-green-200' : 'bg-red-100 text-red-800 border border-red-200'}">
        {#if $notification.type === 'success'}
          <svg class="w-4 h-4 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>
        {:else}
          <svg class="w-4 h-4 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
        {/if}
        {$notification.message}
        <button on:click={() => $notification = null} class="ml-1 opacity-60 hover:opacity-100">
          <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
        </button>
      </div>
    </div>
  {/if}

  <!-- Main content -->
  <main class="max-w-6xl mx-auto px-4 py-8">
    <Router {routes} />
  </main>
</div>
