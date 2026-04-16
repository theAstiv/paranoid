<script>
  import { createEventDispatcher } from 'svelte'
  import { link, push } from 'svelte-spa-router'
  import DreadBadge from './DreadBadge.svelte'

  /** @type {object} */
  export let threat = {}
  /** @type {boolean} */
  export let readonly = false

  const dispatch = createEventDispatcher()

  const STRIDE_COLORS = {
    Spoofing: 'bg-purple-100 text-purple-700',
    Tampering: 'bg-red-100 text-red-700',
    Repudiation: 'bg-orange-100 text-orange-700',
    'Information Disclosure': 'bg-yellow-100 text-yellow-700',
    'Denial of Service': 'bg-rose-100 text-rose-700',
    'Elevation of Privilege': 'bg-violet-100 text-violet-700',
  }

  const MAESTRO_COLOR = 'bg-teal-100 text-teal-700'

  const STATUS_COLORS = {
    pending: 'bg-yellow-100 text-yellow-700',
    approved: 'bg-green-100 text-green-700',
    rejected: 'bg-red-100 text-red-700',
    mitigated: 'bg-blue-100 text-blue-700',
  }

  const IMPACT_COLORS = {
    Low: 'bg-slate-100 text-slate-600',
    Medium: 'bg-yellow-100 text-yellow-700',
    High: 'bg-orange-100 text-orange-700',
    Critical: 'bg-red-100 text-red-700',
  }

  $: category = threat.stride_category ?? threat.maestro_category ?? ''
  $: categoryColor = threat.stride_category
    ? (STRIDE_COLORS[threat.stride_category] ?? 'bg-indigo-100 text-indigo-700')
    : MAESTRO_COLOR
  $: mitigations = typeof threat.mitigations === 'string'
    ? JSON.parse(threat.mitigations)
    : (threat.mitigations ?? [])
</script>

<div class="bg-white rounded-xl border border-slate-200 p-5 space-y-3">
  <!-- Header -->
  <div class="flex items-start justify-between gap-2">
    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-2 flex-wrap mb-1">
        <span class="text-xs px-2 py-0.5 rounded-full font-medium {categoryColor}">{category}</span>
        {#if threat.status}
          <span class="text-xs px-2 py-0.5 rounded-full font-medium {STATUS_COLORS[threat.status] ?? 'bg-slate-100 text-slate-600'}">
            {threat.status}
          </span>
        {/if}
        <DreadBadge {threat} />
      </div>
      <h3 class="font-semibold text-slate-900 text-sm">{threat.name}</h3>
    </div>
  </div>

  <!-- Description -->
  <p class="text-sm text-slate-600 leading-relaxed">{threat.description}</p>

  <!-- Target + Impact / Likelihood -->
  <div class="flex flex-wrap gap-2 text-xs">
    {#if threat.target}
      <span class="text-slate-500">Target: <span class="font-medium text-slate-700">{threat.target}</span></span>
    {/if}
    {#if threat.impact}
      <!-- impact is a free-form string from the LLM — match case-insensitively -->
      {@const impactKey = Object.keys(IMPACT_COLORS).find(k => k.toLowerCase() === threat.impact?.toLowerCase())}
      <span class="px-1.5 py-0.5 rounded {IMPACT_COLORS[impactKey] ?? 'bg-slate-100 text-slate-600'}">{threat.impact}</span>
    {/if}
    {#if threat.likelihood}
      <span class="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">{threat.likelihood}</span>
    {/if}
  </div>

  <!-- Mitigations -->
  {#if mitigations.length > 0}
    <ul class="text-xs text-slate-600 space-y-0.5 list-disc list-inside">
      {#each mitigations as m}
        <li>{m}</li>
      {/each}
    </ul>
  {/if}

  <!-- Actions -->
  {#if !readonly}
    <div class="flex items-center gap-2 pt-1 border-t border-slate-100">
      {#if threat.status !== 'approved'}
        <button
          type="button"
          on:click={() => dispatch('approve', threat)}
          class="flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-white bg-green-600 rounded-md hover:bg-green-700 transition-colors">
          <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>
          Approve
        </button>
      {/if}
      {#if threat.status !== 'rejected'}
        <button
          type="button"
          on:click={() => dispatch('reject', threat)}
          class="flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-slate-600 bg-slate-100 rounded-md hover:bg-slate-200 transition-colors">
          <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
          Reject
        </button>
      {/if}
      {#if threat.status === 'approved' && threat.id}
        <a href="/threats/{threat.id}/attack-tree" use:link
          class="ml-auto text-xs text-indigo-600 hover:underline">
          Attack tree →
        </a>
      {/if}
    </div>
  {/if}
</div>
