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
  import Members from './routes/Members.svelte'
  import AdminUsers from './routes/AdminUsers.svelte'
  import {
    config, notification, notify, currentUser, authLoading,
    currentProject, projects, notifications, notifUnread, menuOpen,
  } from './lib/stores.js'
  import { getConfig, fetchMe, logout, listProjects, createProject, listNotifications, markAllNotificationsRead } from './lib/api.js'
  import { initials, relativeTime } from './lib/utils.js'

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
    '/members': Members,
    '/admin/users': AdminUsers,
  }

  // Routes that render standalone (no sidebar/topbar chrome)
  const STANDALONE_ROUTES = new Set(['/login', '/register'])
  $: isStandalone = STANDALONE_ROUTES.has($location)

  // Active-route helper for nav items
  /** @param {string} path */
  function isActive(path) {
    if (path === '/') return $location === '/'
    return $location.startsWith(path)
  }

  // Nav model count (approx from store)
  let modelCount = 0

  // Backend health
  let backendOk = true

  async function checkHealth() {
    try {
      const r = await fetch('/health')
      backendOk = r.ok
    } catch { backendOk = false }
  }

  async function handleLogout() {
    menuOpen.set(null)
    try { await logout() } catch { /* ignore */ }
    push('/login')
  }

  function toggleMenu(name) {
    menuOpen.update(m => m === name ? null : name)
  }

  function closeMenu() {
    menuOpen.set(null)
  }

  async function handleMarkAllRead() {
    try {
      await markAllNotificationsRead()
      notifications.update(ns => ns.map(n => ({ ...n, is_read: true })))
    } catch { /* ignore */ }
  }

  // Project name for display
  $: projectName = $currentProject?.name ?? 'Default Project'

  // Whether current user can manage (owner or admin)
  $: canManageProject = $currentProject?.member_role === 'owner' || $currentUser?.is_admin

  // New project inline form state
  let showNewProjectForm = false
  let newProjectName = ''
  let creatingProject = false

  // Reset inline form when the project dropdown closes
  $: if ($menuOpen !== 'project') {
    showNewProjectForm = false
    newProjectName = ''
  }

  async function handleCreateProject() {
    if (!newProjectName.trim()) return
    creatingProject = true
    try {
      const proj = await createProject({ name: newProjectName.trim() })
      projects.update(ps => [proj, ...ps])
      currentProject.set(proj)
      newProjectName = ''
      showNewProjectForm = false
      closeMenu()
    } catch (err) {
      notify('error', `Failed to create project: ${err.message}`)
    } finally {
      creatingProject = false
    }
  }


  // Breadcrumb screen name
  const SCREEN_LABELS = {
    '/': 'Threat Models',
    '/models/new': 'New Model',
    '/library': 'Library',
    '/sources': 'Code Sources',
    '/members': 'Members',
    '/admin/users': 'Users',
    '/settings': 'Settings',
  }
  $: screenLabel = (() => {
    for (const [prefix, label] of Object.entries(SCREEN_LABELS)) {
      if (prefix === '/' ? $location === '/' : $location.startsWith(prefix)) return label
    }
    return ''
  })()

  // Boot sequence
  onMount(async () => {
    await fetchMe()

    try {
      const cfg = await getConfig()
      config.set(cfg)
      if (cfg.first_run && get(location) !== '/settings') push('/settings')
    } catch (err) {
      console.warn('Config bootstrap failed — first-run redirect skipped.', err)
    }

    checkHealth()
    setInterval(checkHealth, 30000)

    // Load project + notification stubs (Phase 2/5 will fill these)
    try {
      const [proj, notifs] = await Promise.all([listProjects(), listNotifications()])
      projects.set(proj)
      notifications.set(notifs)
      if (proj.length > 0 && !get(currentProject)) currentProject.set(proj[0])
    } catch { /* non-fatal */ }
  })
</script>

<!-- Full-bleed backdrop: closes any open overlay -->
{#if $menuOpen}
  <!-- svelte-ignore a11y-click-events-have-key-events -->
  <!-- svelte-ignore a11y-no-static-element-interactions -->
  <div class="fixed inset-0 z-40" on:click={closeMenu}></div>
{/if}

{#if isStandalone}
  <!-- Standalone layout: Login / Register render without chrome -->
  <Router {routes} />
{:else}
  <!-- App shell: sidebar + topbar + content -->
  <div class="flex min-h-screen bg-c-bg text-c-text">

    <!-- ── Sidebar ──────────────────────────────────────────────────────── -->
    <aside class="fixed inset-y-0 left-0 z-30 flex flex-col w-[264px] bg-c-sidebar border-r border-c-border-soft">

      <!-- Brand -->
      <div class="flex items-center gap-2.5 px-5 h-[54px] border-b border-c-divider flex-shrink-0">
        <!-- Shield icon with teal gradient -->
        <svg class="w-7 h-7 flex-shrink-0" viewBox="0 0 28 28" fill="none">
          <defs>
            <linearGradient id="shield-grad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stop-color="#2BD4C0"/>
              <stop offset="100%" stop-color="#1B9C8E"/>
            </linearGradient>
          </defs>
          <path d="M14 3L4 7v7c0 6.1 4.3 11.7 10 13 5.7-1.3 10-6.9 10-13V7L14 3z"
            fill="url(#shield-grad)" stroke="none"/>
          <path d="M9.5 14l3 3 6-6" stroke="#0A0E16" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <div class="flex items-baseline gap-1.5">
          <span class="font-mono font-semibold text-c-text text-[15px]">paranoid</span>
          <span class="font-mono text-[11px] text-c-faint tracking-wider">v1.5</span>
        </div>
      </div>

      <!-- Project switcher -->
      <div class="px-3 pt-3 pb-2 flex-shrink-0">
        <button
          on:click={() => toggleMenu('project')}
          class="w-full flex items-center gap-2.5 px-3 py-2 rounded-panel hover:bg-c-panel transition-colors"
          aria-label="Switch project"
        >
          <!-- Project tile -->
          <div class="w-7 h-7 rounded-[6px] bg-c-accent flex items-center justify-center flex-shrink-0">
            <span class="font-mono font-semibold text-[12px] text-[#04141A]">
              {projectName.charAt(0).toUpperCase()}
            </span>
          </div>
          <div class="flex-1 min-w-0 text-left">
            <p class="font-mono text-[10px] text-c-faint uppercase tracking-[0.08em] leading-none mb-0.5">
              {$currentProject?.org ?? 'personal'}
            </p>
            <p class="text-[13px] font-semibold text-c-text truncate">{projectName}</p>
          </div>
          <svg class="w-3.5 h-3.5 text-c-faint flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M10 3a1 1 0 01.707.293l3 3a1 1 0 01-1.414 1.414L10 5.414 7.707 7.707a1 1 0 01-1.414-1.414l3-3A1 1 0 0110 3zm-3.707 9.293a1 1 0 011.414 0L10 14.586l2.293-2.293a1 1 0 011.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clip-rule="evenodd"/>
          </svg>
        </button>

        <!-- Project switcher dropdown -->
        {#if $menuOpen === 'project'}
          <div class="absolute left-3 mt-1 w-[240px] bg-c-panel border border-c-border rounded-card shadow-xl z-50 animate-pop-in py-1.5"
            on:click|stopPropagation>
            <p class="font-mono text-[10px] text-c-faint uppercase tracking-[0.08em] px-3 pb-1.5 pt-0.5">Switch project</p>
            <!-- Current project -->
            <button class="w-full flex items-center gap-2.5 px-3 py-2 bg-c-accent/10 text-left">
              <div class="w-6 h-6 rounded-chip bg-c-accent flex items-center justify-center flex-shrink-0">
                <span class="font-mono text-[11px] font-semibold text-[#04141A]">{projectName.charAt(0)}</span>
              </div>
              <div class="flex-1 min-w-0">
                <p class="text-[13px] font-semibold text-c-accent truncate">{projectName}</p>
                <p class="text-[11px] text-c-faint">{$currentProject?.org ?? 'personal'}</p>
              </div>
            </button>
            {#each $projects.filter(p => p.id !== $currentProject?.id) as p}
              <button
                class="w-full flex items-center gap-2.5 px-3 py-2 hover:bg-c-panel2 text-left transition-colors"
                on:click={() => { currentProject.set(p); closeMenu() }}
              >
                <div class="w-6 h-6 rounded-chip bg-c-border flex items-center justify-center flex-shrink-0">
                  <span class="font-mono text-[11px] font-semibold text-c-text2">{p.name.charAt(0)}</span>
                </div>
                <div class="flex-1 min-w-0">
                  <p class="text-[13px] font-semibold text-c-text2 truncate">{p.name}</p>
                  <p class="text-[11px] text-c-faint">{p.org ?? 'personal'}</p>
                </div>
              </button>
            {/each}
            <div class="border-t border-c-divider mt-1 pt-1">
              {#if showNewProjectForm}
                <div class="px-3 py-2 space-y-2" on:click|stopPropagation>
                  <input
                    type="text"
                    bind:value={newProjectName}
                    placeholder="Project name"
                    class="field text-sm w-full"
                    autofocus
                    on:keydown={(e) => { if (e.key === 'Enter') handleCreateProject(); if (e.key === 'Escape') { showNewProjectForm = false; newProjectName = '' } }}
                  />
                  <div class="flex gap-2">
                    <button
                      type="button"
                      on:click={handleCreateProject}
                      disabled={creatingProject || !newProjectName.trim()}
                      class="flex-1 btn-primary text-xs py-1.5 disabled:opacity-50"
                    >
                      {creatingProject ? 'Creating…' : 'Create'}
                    </button>
                    <button
                      type="button"
                      on:click={() => { showNewProjectForm = false; newProjectName = '' }}
                      class="btn-ghost text-xs py-1.5 px-3"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              {:else}
                <button
                  class="w-full flex items-center gap-2 px-3 py-2 text-[13px] text-c-muted hover:text-c-text hover:bg-c-panel2 text-left transition-colors"
                  on:click|stopPropagation={() => { showNewProjectForm = true }}
                >
                  <svg class="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M10 5v10M5 10h10"/>
                  </svg>
                  New project
                </button>
              {/if}
            </div>
          </div>
        {/if}
      </div>

      <!-- Nav groups -->
      <nav class="flex-1 overflow-y-auto px-3 pb-3 space-y-5">

        <!-- Project group -->
        <div>
          <p class="font-mono text-[10px] text-c-faint uppercase tracking-[0.08em] px-2 mb-1.5">Project</p>
          <ul class="space-y-0.5">
            <li>
              <a href="#/" use:link
                class="flex items-center gap-2.5 px-2.5 py-2 rounded-panel text-[13px] transition-colors
                  {isActive('/') && !isActive('/models') && !isActive('/sources') && !isActive('/settings')
                    ? 'bg-c-accent/10 text-c-accent font-medium'
                    : 'text-c-text3 hover:bg-c-panel hover:text-c-text'}"
              >
                <!-- Grid icon -->
                <svg class="w-4 h-4 flex-shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8">
                  <rect x="3" y="3" width="6" height="6" rx="1"/>
                  <rect x="11" y="3" width="6" height="6" rx="1"/>
                  <rect x="3" y="11" width="6" height="6" rx="1"/>
                  <rect x="11" y="11" width="6" height="6" rx="1"/>
                </svg>
                Threat Models
              </a>
            </li>
            <li>
              <a href="#/sources" use:link
                class="flex items-center gap-2.5 px-2.5 py-2 rounded-panel text-[13px] transition-colors
                  {isActive('/sources')
                    ? 'bg-c-accent/10 text-c-accent font-medium'
                    : 'text-c-text3 hover:bg-c-panel hover:text-c-text'}"
              >
                <!-- Nodes / code icon -->
                <svg class="w-4 h-4 flex-shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8">
                  <circle cx="5" cy="10" r="2"/>
                  <circle cx="15" cy="5" r="2"/>
                  <circle cx="15" cy="15" r="2"/>
                  <path stroke-linecap="round" d="M7 10h4M7 10l3-3.5M7 10l3 3.5"/>
                </svg>
                Code Sources
              </a>
            </li>
            {#if canManageProject}
              <li>
                <a href="#/members" use:link
                  class="flex items-center gap-2.5 px-2.5 py-2 rounded-panel text-[13px] transition-colors
                    {isActive('/members')
                      ? 'bg-c-accent/10 text-c-accent font-medium'
                      : 'text-c-text3 hover:bg-c-panel hover:text-c-text'}"
                >
                  <!-- People icon (stroke-native paths) -->
                  <svg class="w-4 h-4 flex-shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
                    <circle cx="8" cy="6" r="3"/>
                    <path d="M2 17c0-3.3 2.7-6 6-6s6 2.7 6 6"/>
                    <path d="M14 4a3 3 0 010 6M17 17a5 5 0 00-3-4.6"/>
                  </svg>
                  Members
                </a>
              </li>
            {/if}
            <li>
              <a href="#/settings" use:link
                class="flex items-center gap-2.5 px-2.5 py-2 rounded-panel text-[13px] transition-colors
                  {isActive('/settings')
                    ? 'bg-c-accent/10 text-c-accent font-medium'
                    : 'text-c-text3 hover:bg-c-panel hover:text-c-text'}"
              >
                <!-- Sliders icon -->
                <svg class="w-4 h-4 flex-shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8">
                  <path stroke-linecap="round" d="M4 5h12M4 10h12M4 15h12"/>
                  <circle cx="8" cy="5" r="2" fill="currentColor" stroke="none"/>
                  <circle cx="14" cy="10" r="2" fill="currentColor" stroke="none"/>
                  <circle cx="7" cy="15" r="2" fill="currentColor" stroke="none"/>
                </svg>
                Settings
              </a>
            </li>
          </ul>
        </div>

        <!-- Instance group (admin only) -->
        {#if $currentUser?.is_admin}
          <div>
            <p class="font-mono text-[10px] text-c-faint uppercase tracking-[0.08em] px-2 mb-1.5">Instance</p>
            <ul class="space-y-0.5">
              <li>
                <a href="#/admin/users" use:link
                  class="flex items-center gap-2.5 px-2.5 py-2 rounded-panel text-[13px] transition-colors
                    {isActive('/admin')
                      ? 'bg-c-accent/10 text-c-accent font-medium'
                      : 'text-c-text3 hover:bg-c-panel hover:text-c-text'}"
                >
                  <!-- People icon -->
                  <svg class="w-4 h-4 flex-shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8">
                    <path stroke-linecap="round" d="M13 6a3 3 0 11-6 0 3 3 0 016 0zM18 17c0-2.8-2.2-5-5-5H7c-2.8 0-5 2.2-5 5"/>
                  </svg>
                  Users
                  <span class="ml-auto font-mono text-[10px] chip-violet px-1.5 py-0.5 rounded-chip">ADMIN</span>
                </a>
              </li>
            </ul>
          </div>
        {/if}
      </nav>

      <!-- New Threat Model button -->
      <div class="px-3 pb-3 flex-shrink-0">
        <a href="#/models/new" use:link
          class="btn-primary w-full justify-center glow text-[13px]"
        >
          <svg class="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8">
            <path stroke-linecap="round" d="M10 4v12M4 10h12"/>
          </svg>
          New Threat Model
        </a>
      </div>

      <!-- User chip -->
      <div class="border-t border-c-divider px-3 py-2 flex-shrink-0 relative">
        <button
          on:click={() => toggleMenu('user')}
          class="w-full flex items-center gap-2.5 px-2 py-2 rounded-panel hover:bg-c-panel transition-colors"
          aria-label="User menu"
        >
          <!-- Avatar with presence dot -->
          <div class="relative flex-shrink-0">
            <div class="w-7 h-7 rounded-full bg-c-accent/20 border border-c-accent/40 flex items-center justify-center">
              <span class="font-mono text-[11px] font-semibold text-c-accent">
                {initials($currentUser?.display_name || $currentUser?.username || '?')}
              </span>
            </div>
            <span class="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 bg-c-green rounded-full border-2 border-c-sidebar animate-pulse-dot"></span>
          </div>
          <div class="flex-1 min-w-0 text-left">
            <p class="text-[13px] font-medium text-c-text truncate">
              {$currentUser?.display_name || $currentUser?.username || 'Guest'}
            </p>
            <p class="font-mono text-[11px] text-c-faint truncate">
              {$currentUser?.is_admin ? 'Instance admin' : 'Member'}
            </p>
          </div>
          <svg class="w-3.5 h-3.5 text-c-faint flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M10 3a1 1 0 01.707.293l3 3a1 1 0 01-1.414 1.414L10 5.414 7.707 7.707a1 1 0 01-1.414-1.414l3-3A1 1 0 0110 3zm-3.707 9.293a1 1 0 011.414 0L10 14.586l2.293-2.293a1 1 0 011.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clip-rule="evenodd"/>
          </svg>
        </button>

        <!-- User menu overlay (pops up above the chip) -->
        {#if $menuOpen === 'user'}
          <div
            class="absolute bottom-full left-3 right-3 mb-2 bg-c-panel border border-c-border rounded-card shadow-xl z-50 animate-pop-in overflow-hidden"
            on:click|stopPropagation
          >
            <!-- Identity header -->
            <div class="px-4 py-3 border-b border-c-divider">
              <p class="text-[13px] font-semibold text-c-text truncate">
                {$currentUser?.display_name || $currentUser?.username || 'Guest'}
              </p>
              <p class="font-mono text-[11px] text-c-faint truncate mt-0.5">
                {$currentUser?.email || ''}
              </p>
            </div>
            <div class="py-1">
              <a
                href="#/settings"
                use:link
                on:click={closeMenu}
                class="flex items-center gap-2.5 w-full px-4 py-2 text-[13px] text-c-text2 hover:bg-c-panel2 hover:text-c-text transition-colors"
              >
                <svg class="w-3.5 h-3.5 text-c-muted" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8">
                  <circle cx="10" cy="10" r="2"/>
                  <path stroke-linecap="round" d="M10 2v2M10 16v2M2 10h2M16 10h2M4.9 4.9l1.4 1.4M13.7 13.7l1.4 1.4M4.9 15.1l1.4-1.4M13.7 6.3l1.4-1.4"/>
                </svg>
                Account &amp; tokens
              </a>
            </div>
            <div class="border-t border-c-divider py-1">
              <button
                on:click={handleLogout}
                class="flex items-center gap-2.5 w-full px-4 py-2 text-[13px] text-c-critical hover:bg-c-critical/10 transition-colors text-left"
              >
                <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8">
                  <path stroke-linecap="round" d="M13 3h4v14h-4M8 7l-4 3 4 3M4 10h9"/>
                </svg>
                Sign out
              </button>
            </div>
          </div>
        {/if}
      </div>
    </aside>

    <!-- ── Main column (offset by sidebar) ──────────────────────────────── -->
    <div class="flex-1 flex flex-col ml-[264px] min-h-screen">

      <!-- Topbar -->
      <header class="sticky top-0 z-20 flex items-center justify-between h-[54px] px-6 bg-c-bg/70 backdrop-blur-md border-b border-c-divider">
        <!-- Breadcrumb -->
        <div class="flex items-center gap-1.5 font-mono text-[12px] text-c-muted">
          <button
            on:click={() => push('/')}
            class="hover:text-c-text transition-colors truncate max-w-[120px]"
          >{projectName}</button>
          {#if screenLabel}
            <span class="text-c-faint">/</span>
            <span class="text-c-text2">{screenLabel}</span>
          {/if}
        </div>

        <!-- Right: backend status + notification bell -->
        <div class="flex items-center gap-4">
          <!-- Backend status -->
          <div class="hidden sm:flex items-center gap-1.5 font-mono text-[11px] {backendOk ? 'text-c-muted' : 'text-c-critical'}">
            <span class="w-1.5 h-1.5 rounded-full flex-shrink-0
              {backendOk ? 'bg-c-green animate-pulse-dot' : 'bg-c-critical'}">
            </span>
            {backendOk ? 'backend healthy' : 'backend unreachable'}
          </div>

          <!-- Notification bell -->
          <div class="relative">
            <button
              on:click={() => toggleMenu('notif')}
              aria-label="Notifications"
              class="relative w-[34px] h-[34px] flex items-center justify-center rounded-panel text-c-muted hover:text-c-text hover:bg-c-panel border border-c-border transition-colors"
            >
              <svg class="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8">
                <path stroke-linecap="round" d="M10 2a6 6 0 00-6 6v3.5L3 13h14l-1-1.5V8a6 6 0 00-6-6zM8 13v1a2 2 0 004 0v-1"/>
              </svg>
              {#if $notifUnread > 0}
                <span class="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-c-critical text-[10px] font-mono font-semibold text-white flex items-center justify-center">
                  {$notifUnread > 9 ? '9+' : $notifUnread}
                </span>
              {/if}
            </button>

            <!-- Notifications panel -->
            {#if $menuOpen === 'notif'}
              <div
                class="absolute right-0 mt-2 w-80 bg-c-panel border border-c-border rounded-card shadow-xl z-50 animate-pop-in overflow-hidden"
                on:click|stopPropagation
              >
                <div class="flex items-center justify-between px-4 py-3 border-b border-c-divider">
                  <span class="text-[13px] font-semibold text-c-text">Notifications</span>
                  {#if $notifUnread > 0}
                    <button
                      on:click={handleMarkAllRead}
                      class="font-mono text-[11px] text-c-accent hover:underline"
                    >Mark all read</button>
                  {/if}
                </div>
                {#if $notifications.length === 0}
                  <div class="px-4 py-6 text-center text-[13px] text-c-muted">
                    No notifications
                  </div>
                {:else}
                  <ul class="max-h-80 overflow-y-auto">
                    {#each $notifications as n}
                      <li class="flex items-start gap-3 px-4 py-3 border-b border-c-divider last:border-0
                        {n.is_read ? '' : 'bg-c-accent/5'}">
                        <div class="w-7 h-7 rounded-chip bg-c-panel2 border border-c-border flex items-center justify-center flex-shrink-0 mt-0.5">
                          <svg class="w-3.5 h-3.5 text-c-muted" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8">
                            <path stroke-linecap="round" d="M10 2a6 6 0 00-6 6v3.5L3 13h14l-1-1.5V8a6 6 0 00-6-6z"/>
                          </svg>
                        </div>
                        <div class="flex-1 min-w-0">
                          <p class="text-[13px] text-c-text2 leading-snug">{n.title}</p>
                          <p class="font-mono text-[11px] text-c-faint mt-0.5">{relativeTime(n.created_at)}</p>
                        </div>
                        {#if !n.is_read}
                          <span class="w-1.5 h-1.5 rounded-full bg-c-accent flex-shrink-0 mt-1.5"></span>
                        {/if}
                      </li>
                    {/each}
                  </ul>
                {/if}
              </div>
            {/if}
          </div>
        </div>
      </header>

      <!-- Notification banner -->
      {#if $notification}
        <div class="fixed top-[54px] inset-x-0 z-20 flex justify-center pointer-events-none px-4 pt-3">
          <div class="pointer-events-auto flex items-center gap-3 px-4 py-2.5 rounded-panel shadow-lg text-sm font-medium border
            {$notification.type === 'success'
              ? 'bg-c-green/10 text-c-green border-c-green/30'
              : 'bg-c-critical/10 text-c-critical border-c-critical/30'}">
            {#if $notification.type === 'success'}
              <svg class="w-4 h-4 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
              </svg>
            {:else}
              <svg class="w-4 h-4 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
              </svg>
            {/if}
            {$notification.message}
            <button on:click={() => $notification = null} class="ml-1 opacity-60 hover:opacity-100">
              <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/>
              </svg>
            </button>
          </div>
        </div>
      {/if}

      <!-- Page content -->
      <main class="flex-1">
        <Router {routes} />
      </main>
    </div>
  </div>
{/if}
