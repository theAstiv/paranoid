<script>
  import { DEPENDENCY_CATEGORIES, dependencyCategorySet, dependencyFlags, dependencyDisplayName } from '../lib/utils.js'

  const EVIDENCE_LIMIT = 20

  /** @type {Array<object>} dependency_scans rows from GET /models/{id}/dependencies */
  export let scans = []

  const CATEGORY_LABELS = {
    network: 'Network',
    filesystem: 'Filesystem',
    process: 'Process',
    crypto: 'Crypto',
    deserialization: 'Deserial.',
    dynamic_code: 'Dyn. Code',
    native_ffi: 'Native/FFI',
    persistence: 'Persist.',
    authentication: 'Auth',
    environment: 'Env',
    build_install: 'Build/Install',
  }

  const FLAG_CHIPS = {
    error: 'chip-red',
    drift: 'chip-orange',
    'install-hook': 'chip-amber',
  }
  function flagChip(flag) {
    return FLAG_CHIPS[flag] ?? 'chip-gray'
  }

  $: packages = scans.map(scan => {
    const analysis = scan.analysis ?? {}
    const npmSet = dependencyCategorySet(analysis.npm_profile)
    const githubSet = dependencyCategorySet(analysis.github_profile)
    const categories = new Set([...npmSet, ...githubSet])
    const evidence = evidenceFor(analysis)
    return {
      key: scan.id,
      displayName: dependencyDisplayName(scan.package, scan.version),
      analysis,
      categories,
      flags: dependencyFlags(analysis),
      evidence: evidence.slice(0, EVIDENCE_LIMIT),
      evidenceOverflow: Math.max(0, evidence.length - EVIDENCE_LIMIT),
      drift: driftSummary(analysis.drift),
    }
  })

  let expandedKey = null
  function toggle(key) {
    expandedKey = expandedKey === key ? null : key
  }

  function toggleOnKey(e, key) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      toggle(key)
    }
  }

  function evidenceFor(analysis) {
    const rows = []
    for (const [sourceKind, profile] of [
      ['npm', analysis?.npm_profile],
      ['github', analysis?.github_profile],
    ]) {
      for (const e of profile?.evidence ?? []) {
        if (e.path_class !== 'shipped') continue
        rows.push({ ...e, sourceKind })
      }
    }
    return rows
  }

  function driftSummary(drift) {
    if (!drift) return null
    const buckets = [
      ['unexplained', drift.unexplained],
      ['unverifiable', drift.unverifiable],
      ['generated_unverifiable', drift.generated_unverifiable],
      ['explained_by_sourcemap', drift.explained_by_sourcemap],
      ['explained_by_build', drift.explained_by_build],
      ['bundled_dependency', drift.bundled_dependency],
      ['matched', drift.matched],
    ].filter(([, list]) => list?.length)
    const signalFiles = Object.entries(drift.signal_files ?? {})
    return {
      status: drift.status,
      skip_reason: drift.skip_reason,
      buckets,
      signal: drift.signal,
      signalCategories: drift.signal_categories ?? [],
      signalFiles,
      nameMismatch: drift.tarball_declared_name_mismatch || null,
      unscannedReachableFiles: drift.unscanned_reachable_files ?? [],
    }
  }
</script>

{#if packages.length === 0}
  <p class="text-xs text-c-faint italic">No dependency scans for this model.</p>
{:else}
  <div class="overflow-x-auto">
    <table class="w-full text-xs border-collapse">
      <thead>
        <tr class="border-b border-c-border">
          <th class="text-left font-mono text-[10px] text-c-faint uppercase tracking-wide py-1.5 pr-3">Package</th>
          {#each DEPENDENCY_CATEGORIES as cat}
            <th class="text-center font-mono text-[9px] text-c-faint uppercase tracking-wide py-1.5 px-1" title={cat}>
              {CATEGORY_LABELS[cat]}
            </th>
          {/each}
          <th class="text-left font-mono text-[10px] text-c-faint uppercase tracking-wide py-1.5 pl-3">Flags</th>
        </tr>
      </thead>
      <tbody>
        {#each packages as pkg (pkg.key)}
          <tr
            class="border-b border-c-divider cursor-pointer hover:bg-c-panel2"
            role="button"
            tabindex="0"
            aria-expanded={expandedKey === pkg.key}
            on:click={() => toggle(pkg.key)}
            on:keydown={e => toggleOnKey(e, pkg.key)}>
            <td class="py-1.5 pr-3 font-mono text-c-text2">{pkg.displayName}</td>
            {#each DEPENDENCY_CATEGORIES as cat}
              <td class="text-center py-1.5 px-1">
                {#if pkg.categories.has(cat)}
                  <span class="inline-block w-3 h-3 rounded-sm bg-c-accent/60" title={cat}></span>
                {:else}
                  <span class="inline-block w-3 h-3 rounded-sm bg-c-well"></span>
                {/if}
              </td>
            {/each}
            <td class="py-1.5 pl-3">
              <div class="flex flex-wrap gap-1">
                {#each pkg.flags as flag}
                  <span class="font-mono text-[10px] px-1.5 py-0.5 rounded-chip border {flagChip(flag)}">{flag}</span>
                {/each}
              </div>
            </td>
          </tr>
          {#if expandedKey === pkg.key}
            <tr class="border-b border-c-divider bg-c-panel2">
              <td colspan={DEPENDENCY_CATEGORIES.length + 2} class="p-3">
                {#if pkg.analysis.error}
                  <p class="text-xs text-c-critical mb-2">Skipped: {pkg.analysis.error}</p>
                {/if}
                {#if pkg.evidence.length > 0}
                  <p class="font-mono text-[10px] font-semibold text-c-faint uppercase tracking-wide mb-1">Evidence</p>
                  <div class="space-y-1 mb-1">
                    {#each pkg.evidence as e}
                      <div class="flex items-start gap-2 text-xs">
                        <span class="font-mono text-[10px] px-1.5 py-0.5 rounded-chip border chip-blue shrink-0">{e.category}</span>
                        <span class="font-mono text-[10px] px-1.5 py-0.5 rounded-chip border chip-gray shrink-0">{e.sourceKind}</span>
                        <span class="font-mono text-c-faint shrink-0">{e.file}:{e.line}</span>
                        <span class="font-mono text-c-muted truncate">{e.snippet}</span>
                      </div>
                    {/each}
                  </div>
                  {#if pkg.evidenceOverflow > 0}
                    <p class="text-xs text-c-faint mb-3">+{pkg.evidenceOverflow} more</p>
                  {:else}
                    <div class="mb-3"></div>
                  {/if}
                {:else}
                  <p class="text-xs text-c-faint italic mb-2">No shipped-path evidence recorded.</p>
                {/if}
                {#if pkg.drift}
                  <p class="font-mono text-[10px] font-semibold text-c-faint uppercase tracking-wide mb-1">Drift ({pkg.drift.status})</p>
                  {#if pkg.drift.skip_reason}
                    <p class="text-xs text-c-faint mb-1">Skip reason: {pkg.drift.skip_reason}</p>
                  {/if}
                  {#if pkg.drift.signal}
                    {#if pkg.drift.signalCategories.length > 0}
                      <p class="text-xs text-c-critical font-medium mb-1">
                        Signal: novel {pkg.drift.signalCategories.join(', ')} not present on GitHub
                      </p>
                      {#each pkg.drift.signalFiles as [file, categories]}
                        <p class="text-xs text-c-muted">{file}: {categories.join(', ')}</p>
                      {/each}
                    {/if}
                    {#if pkg.drift.nameMismatch}
                      <p class="text-xs text-c-critical font-medium mb-1">
                        Signal: tarball package.json declares name "{pkg.drift.nameMismatch}", which does not match the registry
                      </p>
                    {/if}
                    {#if pkg.drift.unscannedReachableFiles.length > 0}
                      <p class="text-xs text-c-critical font-medium mb-1">
                        Signal: {pkg.drift.unscannedReachableFiles.length} reachable file{pkg.drift.unscannedReachableFiles.length === 1 ? '' : 's'} never scanned
                      </p>
                      {#each pkg.drift.unscannedReachableFiles as file}
                        <p class="text-xs text-c-muted">{file}</p>
                      {/each}
                    {/if}
                  {/if}
                  {#each pkg.drift.buckets as [name, list]}
                    <p class="text-xs text-c-muted">{name}: {list.length} file{list.length === 1 ? '' : 's'}</p>
                  {/each}
                {/if}
              </td>
            </tr>
          {/if}
        {/each}
      </tbody>
    </table>
  </div>
{/if}
