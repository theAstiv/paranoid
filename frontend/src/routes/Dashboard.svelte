<script>
  import { link } from 'svelte-spa-router'
  import { currentProject, currentUser, notify } from '../lib/stores.js'
  import { getProjectDashboard } from '../lib/api.js'
  import { dreadChip, dreadColor, dreadLabel, initials, relativeTime } from '../lib/utils.js'

  let loading = true
  let stats = null
  let severity = null
  let activity = []
  let assignedToYou = []

  $: projectId = $currentProject?.id
  $: if (projectId) loadDashboard()

  async function loadDashboard() {
    loading = true
    try {
      const data = await getProjectDashboard(projectId)
      stats = data.stats
      severity = data.severity
      activity = data.activity
      assignedToYou = data.assigned_to_you
    } catch (err) {
      notify('error', `Failed to load dashboard: ${err.message}`)
    } finally {
      loading = false
    }
  }

  $: severityTotal = severity
    ? severity.critical + severity.high + severity.medium + severity.low
    : 0

  function pct(count) {
    return severityTotal > 0 ? (count / severityTotal) * 100 : 0
  }

  const SEVERITY_BAR_COLOR = {
    critical: 'bg-c-critical',
    high: 'bg-c-high',
    medium: 'bg-c-medium',
    low: 'bg-c-low',
  }

  const STAT_CARDS = [
    { key: 'model_count', label: 'Threat models', color: 'text-c-accent', icon: 'grid' },
    { key: 'open_threats', label: 'Open threats', color: 'text-c-critical', icon: 'alert' },
    { key: 'pending_review', label: 'Pending review', color: 'text-c-high', icon: 'clock' },
    { key: 'member_count', label: 'Members', color: 'text-c-accent', icon: 'people' },
  ]

  function activityLine(entry) {
    const actor = entry.display_name || entry.username || 'Someone'
    const target = entry.details?.title || entry.entity_type
    return { actor, text: `${entry.action.replace(/_/g, ' ')} ${target}` }
  }
</script>

<div class="max-w-[1120px] mx-auto space-y-5">
  <!-- Header -->
  <div class="flex items-center justify-between gap-3">
    <div>
      <h1 class="text-xl font-semibold text-c-text">{$currentProject?.name ?? 'Project'}</h1>
      {#if !loading && stats}
        <p class="font-mono text-[11px] text-c-faint mt-1">
          {$currentProject?.member_role ?? 'member'} · {stats.member_count} member{stats.member_count !== 1 ? 's' : ''}
          {#if stats.last_run_at} · last run {relativeTime(stats.last_run_at)}{/if}
        </p>
      {/if}
    </div>
    <a href="#/models/new" use:link class="btn-primary text-sm px-4 flex-shrink-0">New Model</a>
  </div>

  {#if !projectId}
    <div class="card p-8 text-center text-sm text-c-muted">No project selected.</div>
  {:else if loading}
    <div class="flex justify-center py-16">
      <div class="w-6 h-6 border-2 border-c-accent border-t-transparent rounded-full animate-spin-slow"></div>
    </div>
  {:else}
    <!-- Stat grid -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
      {#each STAT_CARDS as sc}
        <div class="card p-4">
          <p class="text-[11px] text-c-faint uppercase tracking-wide mb-2">{sc.label}</p>
          <p class="font-mono text-[26px] font-semibold {sc.color}">{stats?.[sc.key] ?? 0}</p>
        </div>
      {/each}
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-5 items-start">
      <!-- Left column -->
      <div class="space-y-5">
        <!-- Severity panel -->
        <div class="card p-5">
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-xs font-semibold text-c-muted uppercase tracking-wide">Open threats by severity</h2>
            <span class="font-mono text-[11px] text-c-faint">{severityTotal} total</span>
          </div>
          {#if severityTotal > 0}
            <div class="flex h-[10px] rounded-full overflow-hidden bg-c-panel2 mb-3">
              {#each ['critical', 'high', 'medium', 'low'] as sev}
                {#if severity[sev] > 0}
                  <div
                    class="{SEVERITY_BAR_COLOR[sev]}"
                    style="width: {pct(severity[sev])}%"
                    title="{sev}: {severity[sev]}"
                  ></div>
                {/if}
              {/each}
            </div>
            <div class="flex flex-wrap gap-x-5 gap-y-1 font-mono text-[11px] text-c-muted">
              <span><span class="text-c-critical">●</span> Critical {severity.critical}</span>
              <span><span class="text-c-high">●</span> High {severity.high}</span>
              <span><span class="text-c-medium">●</span> Medium {severity.medium}</span>
              <span><span class="text-c-low">●</span> Low {severity.low}</span>
            </div>
          {:else}
            <p class="text-sm text-c-faint">No open threats.</p>
          {/if}
        </div>

        <!-- Activity feed -->
        <div class="card overflow-hidden">
          <div class="px-5 py-3 border-b border-c-border">
            <span class="text-xs font-semibold text-c-muted uppercase tracking-wide">Recent activity</span>
          </div>
          {#if activity.length === 0}
            <div class="px-5 py-8 text-center text-sm text-c-faint">No activity yet.</div>
          {:else}
            <ul class="divide-y divide-c-divider">
              {#each activity as entry (entry.id)}
                {@const line = activityLine(entry)}
                <li class="flex items-center gap-3 px-5 py-3">
                  <div class="w-[26px] h-[26px] rounded-full bg-c-accent/20 border border-c-accent/40 flex items-center justify-center flex-shrink-0">
                    <span class="font-mono text-[10px] font-semibold text-c-accent">{initials(line.actor)}</span>
                  </div>
                  <p class="flex-1 min-w-0 text-[13px] text-c-text2 truncate">
                    <span class="font-medium text-c-text">{line.actor}</span> {line.text}
                  </p>
                  <span class="font-mono text-[11px] text-c-faint flex-shrink-0">{relativeTime(entry.created_at)}</span>
                </li>
              {/each}
            </ul>
          {/if}
        </div>
      </div>

      <!-- Assigned to you -->
      <div class="card overflow-hidden">
        <div class="px-5 py-3 border-b border-c-border flex items-center gap-2">
          <span class="text-xs font-semibold text-c-muted uppercase tracking-wide">Assigned to you</span>
          {#if assignedToYou.length > 0}
            <span class="font-mono text-[11px] text-c-faint">({assignedToYou.length})</span>
          {/if}
        </div>
        {#if assignedToYou.length === 0}
          <div class="px-5 py-8 text-center text-sm text-c-faint">Nothing assigned to you.</div>
        {:else}
          <ul class="divide-y divide-c-divider">
            {#each assignedToYou as t (t.id)}
              <li>
                <a href="#/models/{t.model_id}/review" use:link class="flex flex-col gap-1.5 px-5 py-3 hover:bg-c-panel2 transition-colors">
                  <div class="flex items-center gap-2">
                    <span class="font-mono text-xs font-semibold {dreadColor(t.dread_score ?? 0)}">
                      {t.dread_score != null ? t.dread_score.toFixed(1) : '—'}
                    </span>
                    <span class="inline-flex font-mono text-[10px] px-1.5 py-0.5 rounded-chip border {dreadChip(t.dread_score ?? 0)}">
                      {dreadLabel(t.dread_score ?? 0)}
                    </span>
                    {#if t.stride_category || t.maestro_category}
                      <span class="font-mono text-[10px] px-1.5 py-0.5 rounded-chip chip-gray truncate">
                        {t.stride_category || t.maestro_category}
                      </span>
                    {/if}
                  </div>
                  <p class="text-[13px] text-c-text2 truncate">{t.name}</p>
                  <p class="font-mono text-[11px] text-c-faint truncate">{t.model_title}</p>
                </a>
              </li>
            {/each}
          </ul>
        {/if}
      </div>
    </div>
  {/if}
</div>
