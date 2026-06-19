<script>
  import { push } from 'svelte-spa-router'
  import { register, login } from '../lib/api.js'

  let username = ''
  let email = ''
  let password = ''
  let displayName = ''
  let error = ''
  let loading = false

  /** @param {SubmitEvent} e */
  async function handleSubmit(e) {
    e.preventDefault()
    error = ''
    loading = true
    try {
      await register({ username, email, password, display_name: displayName || undefined })
      await login({ username, password })
      push('/')
    } catch (err) {
      error = err.message || 'Registration failed'
    } finally {
      loading = false
    }
  }
</script>

<!-- Full-screen standalone layout (no sidebar/topbar) -->
<div class="min-h-screen bg-c-bg flex items-center justify-center px-4 py-10 relative overflow-hidden">

  <!-- Faint dotted grid background -->
  <div class="absolute inset-0 pointer-events-none"
    style="background-image: radial-gradient(circle, #1E2738 1px, transparent 1px); background-size: 38px 38px; opacity: 0.7;">
  </div>

  <!-- Teal radial glow at top -->
  <div class="absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[300px] rounded-full pointer-events-none"
    style="background: radial-gradient(ellipse at 50% 0%, rgba(43,212,192,0.12) 0%, transparent 70%);">
  </div>

  <!-- Card column -->
  <div class="relative z-10 w-full max-w-[380px] animate-pop-in">

    <!-- Brand lockup -->
    <div class="flex flex-col items-center mb-8">
      <div class="flex items-center gap-2.5 mb-3">
        <svg class="w-9 h-9" viewBox="0 0 36 36" fill="none">
          <defs>
            <linearGradient id="reg-shield" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stop-color="#2BD4C0"/>
              <stop offset="100%" stop-color="#1B9C8E"/>
            </linearGradient>
          </defs>
          <path d="M18 3L5 8.5v9c0 7.5 5.5 14.5 13 16 7.5-1.5 13-8.5 13-16v-9L18 3z"
            fill="url(#reg-shield)" stroke="none"/>
          <path d="M12 18l4 4 8-8" stroke="#0A0E16" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <span class="font-mono font-semibold text-c-text text-xl tracking-tight">paranoid</span>
      </div>
      <p class="text-[13px] text-c-muted">Iterative threat modeling</p>
    </div>

    <!-- Register card -->
    <div class="bg-c-panel2 border border-c-border rounded-[16px] p-[26px]">
      <h1 class="text-[17px] font-semibold text-c-text mb-1">Create account</h1>
      <p class="text-[13px] text-c-muted mb-6">Set up your Paranoid account</p>

      {#if error}
        <div class="mb-5 flex items-start gap-2.5 rounded-panel bg-c-critical/10 border border-c-critical/30 px-3 py-2.5">
          <svg class="w-4 h-4 text-c-critical flex-shrink-0 mt-px" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
          </svg>
          <span class="text-[13px] text-c-critical">{error}</span>
        </div>
      {/if}

      <form on:submit={handleSubmit} class="space-y-4">
        <!-- Username -->
        <div>
          <label for="reg-username" class="block text-[12px] font-medium text-c-text3 mb-1.5">
            Username
            <span class="text-c-faint font-normal ml-1">letters, numbers, _ -</span>
          </label>
          <input
            id="reg-username"
            type="text"
            bind:value={username}
            required
            autocomplete="username"
            pattern="[a-zA-Z0-9_\-]+"
            minlength="3"
            maxlength="50"
            class="field"
          />
        </div>

        <!-- Display name -->
        <div>
          <label for="reg-display" class="block text-[12px] font-medium text-c-text3 mb-1.5">
            Display name
            <span class="text-c-faint font-normal ml-1">optional</span>
          </label>
          <input
            id="reg-display"
            type="text"
            bind:value={displayName}
            maxlength="100"
            autocomplete="name"
            class="field"
          />
        </div>

        <!-- Email -->
        <div>
          <label for="reg-email" class="block text-[12px] font-medium text-c-text3 mb-1.5">Email</label>
          <div class="relative">
            <div class="absolute inset-y-0 left-3 flex items-center pointer-events-none">
              <svg class="w-4 h-4 text-c-faint" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8">
                <path stroke-linecap="round" d="M3 8l7 5 7-5M3 8v8a2 2 0 002 2h10a2 2 0 002-2V8M3 8l2-2h10l2 2"/>
              </svg>
            </div>
            <input
              id="reg-email"
              type="email"
              bind:value={email}
              required
              autocomplete="email"
              class="field pl-9"
            />
          </div>
        </div>

        <!-- Password -->
        <div>
          <label for="reg-password" class="block text-[12px] font-medium text-c-text3 mb-1.5">
            Password
            <span class="text-c-faint font-normal ml-1">min 8 characters</span>
          </label>
          <div class="relative">
            <div class="absolute inset-y-0 left-3 flex items-center pointer-events-none">
              <svg class="w-4 h-4 text-c-faint" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8">
                <rect x="4" y="9" width="12" height="9" rx="2"/>
                <path stroke-linecap="round" d="M8 9V6a4 4 0 018 0v3"/>
              </svg>
            </div>
            <input
              id="reg-password"
              type="password"
              bind:value={password}
              required
              minlength="8"
              autocomplete="new-password"
              class="field pl-9"
            />
          </div>
        </div>

        <button
          type="submit"
          disabled={loading}
          class="btn-primary w-full justify-center glow mt-2 disabled:opacity-50 disabled:cursor-not-allowed disabled:shadow-none"
        >
          {#if loading}
            <svg class="w-4 h-4 animate-spin-slow" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" d="M10 2a8 8 0 018 8"/>
            </svg>
            Creating account…
          {:else}
            Create account →
          {/if}
        </button>
      </form>

      <div class="mt-6 flex items-center justify-between text-[13px]">
        <span class="text-c-muted">Already have an account?</span>
        <a href="#/login" class="text-c-accent hover:underline font-medium">Sign in</a>
      </div>
    </div>

    <!-- Mode note pill -->
    <div class="flex justify-center mt-5">
      <span class="chip-amber font-mono text-[11px] px-2.5 py-1 rounded-pill">
        PARANOID_REQUIRE_AUTH=true · local accounts + PAT
      </span>
    </div>
  </div>
</div>
