<script>
  import { push } from 'svelte-spa-router'
  import { login } from '../lib/api.js'
  import { currentUser } from '../lib/stores.js'

  let username = ''
  let password = ''
  let error = ''
  let loading = false

  /** @param {SubmitEvent} e */
  async function handleSubmit(e) {
    e.preventDefault()
    error = ''
    loading = true
    try {
      await login({ username, password })
      push('/')
    } catch (err) {
      error = err.message || 'Login failed'
    } finally {
      loading = false
    }
  }
</script>

<div class="min-h-screen bg-gray-50 flex items-center justify-center px-4">
  <div class="w-full max-w-md">
    <div class="text-center mb-8">
      <div class="flex items-center justify-center gap-2 mb-2">
        <svg class="w-8 h-8 text-indigo-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
        </svg>
        <span class="text-2xl font-bold text-gray-900">Paranoid</span>
      </div>
      <p class="text-sm text-gray-500">Iterative threat modeling</p>
    </div>

    <div class="bg-white rounded-xl shadow-sm border border-gray-200 p-8">
      <h1 class="text-xl font-semibold text-gray-900 mb-6">Sign in</h1>

      {#if error}
        <div class="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      {/if}

      <form on:submit={handleSubmit} class="space-y-5">
        <div>
          <label for="username" class="block text-sm font-medium text-gray-700 mb-1">Username</label>
          <input
            id="username"
            type="text"
            bind:value={username}
            required
            autocomplete="username"
            class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            placeholder="admin"
          />
        </div>

        <div>
          <label for="password" class="block text-sm font-medium text-gray-700 mb-1">Password</label>
          <input
            id="password"
            type="password"
            bind:value={password}
            required
            autocomplete="current-password"
            class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          class="w-full bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-medium py-2 px-4 rounded-lg text-sm transition-colors"
        >
          {loading ? 'Signing in…' : 'Sign in'}
        </button>
      </form>

      <p class="mt-6 text-center text-sm text-gray-500">
        Don't have an account?
        <a href="#/register" class="text-indigo-600 hover:underline font-medium">Register</a>
      </p>
    </div>
  </div>
</div>
