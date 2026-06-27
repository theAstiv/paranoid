<script>
  import { createEventDispatcher } from 'svelte'
  import { link } from 'svelte-spa-router'
  import DreadBadge from './DreadBadge.svelte'
  import { updateThreat } from '../lib/api.js'

  /** @type {object} */
  export let threat = {}
  /** @type {boolean} */
  export let readonly = false

  const dispatch = createEventDispatcher()

  let editingDread = false
  let savingDread = false
  let dreadError = ''
  let draftDread = {}

  const DREAD_DIMS = [
    ['Damage', 'dread_damage'],
    ['Reproducibility', 'dread_reproducibility'],
    ['Exploitability', 'dread_exploitability'],
    ['Affected Users', 'dread_affected_users'],
    ['Discoverability', 'dread_discoverability'],
  ]

  function startEditDread() {
    draftDread = {
      dread_damage: threat.dread_damage ?? '',
      dread_reproducibility: threat.dread_reproducibility ?? '',
      dread_exploitability: threat.dread_exploitability ?? '',
      dread_affected_users: threat.dread_affected_users ?? '',
      dread_discoverability: threat.dread_discoverability ?? '',
    }
    dreadError = ''
    editingDread = true
  }

  async function saveDread() {
    const body = {}
    for (const [, key] of DREAD_DIMS) {
      const v = draftDread[key]
      if (v === '' || v == null) continue
      const n = Number(v)
      if (!Number.isInteger(n) || n < 1 || n > 10) {
        dreadError = 'All scores must be integers between 1 and 10.'
        return
      }
      body[key] = n
    }
    dreadError = ''
    savingDread = true
    try {
      await updateThreat(threat.id, body)
      threat = { ...threat, ...body }
      dispatch('dread-updated', threat)
      editingDread = false
    } catch (e) {
      dreadError = e.message
    } finally {
      savingDread = false
    }
  }

  const STRIDE_CHIPS = {
    Spoofing:                 'chip-violet',
    Tampering:                'chip-red',
    Repudiation:              'chip-orange',
    'Information Disclosure': 'chip-amber',
    'Denial of Service':      'chip-red',
    'Elevation of Privilege': 'chip-violet',
  }

  const IMPACT_CHIPS = {
    low:      'chip-green',
    medium:   'chip-amber',
    high:     'chip-orange',
    critical: 'chip-red',
  }

  const STATUS_CHIPS = {
    pending:   'chip-gray',
    approved:  'chip-green',
    rejected:  'chip-red',
    mitigated: 'chip-blue',
  }

  $: category = threat.stride_category ?? threat.maestro_category ?? ''
  $: categoryChip = threat.stride_category
    ? (STRIDE_CHIPS[threat.stride_category] ?? 'chip-blue')
    : 'chip-accent'
  $: mitigations = typeof threat.mitigations === 'string'
    ? JSON.parse(threat.mitigations)
    : (threat.mitigations ?? [])
</script>

<div class="card p-5 space-y-3">
  <!-- Header -->
  <div class="flex items-start justify-between gap-2">
    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-2 flex-wrap mb-1.5">
        <span class="font-mono text-[11px] px-2 py-0.5 rounded-chip border {categoryChip}">{category}</span>
        {#if threat.status}
          <span class="font-mono text-[11px] px-2 py-0.5 rounded-chip border capitalize {STATUS_CHIPS[threat.status] ?? 'chip-gray'}">
            {threat.status}
          </span>
        {/if}
        <DreadBadge {threat} />
        {#if !readonly && threat.id && !editingDread}
          <button
            type="button"
            on:click={startEditDread}
            title="Edit DREAD scores"
            class="inline-flex items-center gap-0.5 font-mono text-[10px] px-1.5 py-0.5 text-c-faint hover:text-c-accent hover:bg-c-accent/10 rounded transition-colors">
            <svg class="w-3 h-3" viewBox="0 0 20 20" fill="currentColor"><path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/></svg>
            DREAD
          </button>
        {/if}
      </div>
      <h3 class="font-semibold text-c-text text-sm">{threat.name}</h3>
    </div>
  </div>

  <!-- DREAD edit form -->
  {#if editingDread}
    <div class="bg-c-well border border-c-border rounded-panel p-3 space-y-2">
      <p class="font-mono text-[10px] font-semibold text-c-muted uppercase tracking-wide">Edit DREAD scores <span class="font-normal normal-case text-c-faint">(1–10 each)</span></p>
      <div class="grid grid-cols-2 gap-x-4 gap-y-1.5">
        {#each DREAD_DIMS as [label, key]}
          <label class="flex items-center justify-between gap-2 text-xs">
            <span class="text-c-muted">{label}</span>
            <input
              type="number"
              min="1"
              max="10"
              bind:value={draftDread[key]}
              class="w-14 bg-c-input border border-c-border-strong rounded px-1.5 py-0.5 text-xs font-mono text-c-text text-right focus:outline-none focus:border-c-accent" />
          </label>
        {/each}
      </div>
      {#if dreadError}
        <p class="text-xs text-c-critical">{dreadError}</p>
      {/if}
      <div class="flex gap-2 pt-1">
        <button
          type="button"
          on:click={saveDread}
          disabled={savingDread}
          class="btn-primary text-xs px-3 py-1 disabled:opacity-50">
          {savingDread ? 'Saving…' : 'Save'}
        </button>
        <button
          type="button"
          on:click={() => { editingDread = false; dreadError = '' }}
          class="btn-ghost text-xs px-3 py-1">
          Cancel
        </button>
      </div>
    </div>
  {/if}

  <!-- Description -->
  <p class="text-sm text-c-muted leading-relaxed">{threat.description}</p>

  <!-- Target + Impact / Likelihood -->
  <div class="flex flex-wrap gap-2 text-xs">
    {#if threat.target}
      <span class="text-c-faint">Target: <span class="font-medium text-c-text2">{threat.target}</span></span>
    {/if}
    {#if threat.impact}
      {@const impactKey = threat.impact?.toLowerCase()}
      <span class="font-mono text-[11px] px-1.5 py-0.5 rounded-chip border capitalize {IMPACT_CHIPS[impactKey] ?? 'chip-gray'}">{threat.impact}</span>
    {/if}
    {#if threat.likelihood}
      <span class="font-mono text-[11px] px-1.5 py-0.5 rounded-chip border chip-gray capitalize">{threat.likelihood}</span>
    {/if}
  </div>

  <!-- Mitigations -->
  {#if mitigations.length > 0}
    <ul class="text-xs text-c-muted space-y-0.5 list-disc list-inside">
      {#each mitigations as m}
        <li>{m}</li>
      {/each}
    </ul>
  {/if}

  <!-- Actions -->
  {#if !readonly}
    <div class="flex items-center gap-2 pt-1 border-t border-c-border">
      {#if threat.status !== 'approved'}
        <button
          type="button"
          on:click={() => dispatch('approve', threat)}
          class="flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-[#04141A] bg-c-green rounded-panel hover:bg-c-green/80 transition-colors">
          <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>
          Approve
        </button>
      {/if}
      {#if threat.status !== 'rejected'}
        <button
          type="button"
          on:click={() => dispatch('reject', threat)}
          class="flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-c-muted bg-c-well border border-c-border rounded-panel hover:border-c-critical hover:text-c-critical transition-colors">
          <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
          Reject
        </button>
      {/if}
      {#if threat.status === 'approved' && threat.id}
        <div class="ml-auto flex items-center gap-3">
          <a href="/threats/{threat.id}/attack-tree" use:link
            class="text-xs text-c-accent hover:underline">
            Attack tree →
          </a>
          <a href="/threats/{threat.id}/test-cases" use:link
            class="text-xs text-c-accent hover:underline">
            Test cases →
          </a>
        </div>
      {/if}
    </div>
  {/if}
</div>
