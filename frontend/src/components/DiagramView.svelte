<script context="module">
  // Registered once per page load, shared across every DiagramView instance —
  // mermaid.registerLayoutLoaders() is a global registration, not per-render.
  let elkRegisterPromise = null

  async function ensureElkRegistered(mermaid) {
    if (!elkRegisterPromise) {
      elkRegisterPromise = import('@mermaid-js/layout-elk').then((mod) => {
        mermaid.registerLayoutLoaders(mod.default)
      })
    }
    return elkRegisterPromise
  }
</script>

<script>
  import { sanitizeMermaid } from '../lib/mermaid_sanitize.js'
  import { diagramInitConfig, diagramThemeVariables } from '../lib/diagram_theme.js'

  /** @type {'mermaid'|'png'|'jpeg'} */
  export let kind = 'mermaid'
  /** @type {string} mermaid source text, or base64 data for png/jpeg */
  export let content = ''
  /** @type {string} */
  export let name = 'diagram'
  /** @type {string|null} required for png/jpeg */
  export let mediaType = null

  let container
  let viewport
  let renderError = null
  let showRawSource = false

  // Pan/zoom state — in-house, no new dependency.
  let scale = 1
  let translateX = 0
  let translateY = 0
  let dragging = false
  let dragStartX = 0
  let dragStartY = 0

  const MIN_SCALE = 0.25
  const MAX_SCALE = 4

  $: isMermaid = kind === 'mermaid'
  // Keyed on the content itself, not its length — two different sources of
  // the same length (or a regenerated tree of identical length) must not be
  // treated as "already rendered".
  $: renderKey = `${kind}:${name}:${content ?? ''}`

  let lastRenderedKey = null
  // Reset when the render target unmounts (e.g. switching away from the
  // mermaid branch) so the next time it remounts, the same key still triggers
  // a fresh render rather than being treated as already-rendered.
  $: if (!container && lastRenderedKey !== null) {
    lastRenderedKey = null
  }
  // Gated on `container` itself (not just content), since bind:this only
  // resolves after the DOM mounts — a plain content-only reactive statement
  // can fire before the render target exists.
  $: if (container && isMermaid && renderKey !== lastRenderedKey) {
    lastRenderedKey = renderKey
    renderMermaid(content)
  }

  // Guards against two renders racing (e.g. quickly switching the Results
  // diagram <select>): only the latest call is allowed to touch the DOM.
  let renderSeq = 0

  async function renderMermaid(source) {
    const seq = ++renderSeq
    renderError = null
    resetView()
    const cleaned = sanitizeMermaid(source)
    if (!cleaned) {
      if (seq !== renderSeq || !container) return
      renderError = 'Mermaid source is empty.'
      container.innerHTML = ''
      return
    }
    const renderId = `diagram-${Math.random().toString(36).slice(2)}`
    try {
      const mermaid = (await import('mermaid')).default
      await ensureElkRegistered(mermaid)
      if (seq !== renderSeq || !container) return
      mermaid.initialize(diagramInitConfig)
      const { svg } = await mermaid.render(renderId, cleaned)
      if (seq !== renderSeq || !container) return
      container.innerHTML = svg
      // Mermaid emits width="100%" plus a max-width style — inside this
      // absolutely-positioned, shrink-to-fit wrapper there's no containing
      // block for that percentage to resolve against, so the SVG falls back
      // to the browser's replaced-element default (300x150) instead of its
      // real size. Set explicit pixel dimensions from the viewBox so the
      // wrapper sizes to the diagram's actual content and fitToView/scale(1)
      // reflect its true dimensions.
      const svgEl = container.querySelector('svg')
      const viewBox = svgEl?.getAttribute('viewBox')?.split(/\s+/).map(Number)
      if (svgEl && viewBox?.length === 4 && viewBox[2] > 0 && viewBox[3] > 0) {
        svgEl.setAttribute('width', String(viewBox[2]))
        svgEl.setAttribute('height', String(viewBox[3]))
        svgEl.style.maxWidth = 'none'
      }
      requestAnimationFrame(fitToView)
    } catch (err) {
      // A failed ELK chunk load must not be cached — the next render attempt
      // re-imports instead of permanently failing. Resetting unconditionally
      // (not just for an ELK-specific error) costs one harmless re-import
      // (browser module cache) on a plain mermaid syntax error instead.
      elkRegisterPromise = null
      if (seq !== renderSeq || !container) return
      container.innerHTML = ''
      renderError = err?.message || 'Mermaid rendering failed.'
    }
  }

  function resetView() {
    scale = 1
    translateX = 0
    translateY = 0
  }

  function fitToView() {
    if (!viewport) return
    const target = isMermaid ? container?.querySelector('svg') : viewport.querySelector('img')
    if (!target) return
    const vpRect = viewport.getBoundingClientRect()
    const targetRect = target.getBoundingClientRect()
    // getBoundingClientRect reflects the CURRENT scale/translate transform,
    // so divide those out to get the content's natural (unscaled) size.
    const naturalWidth = targetRect.width / scale
    const naturalHeight = targetRect.height / scale
    if (naturalWidth === 0 || naturalHeight === 0) return
    const fitScale = Math.min(vpRect.width / naturalWidth, vpRect.height / naturalHeight, MAX_SCALE)
    scale = Math.max(MIN_SCALE, fitScale)
    translateX = (vpRect.width - naturalWidth * scale) / 2
    translateY = (vpRect.height - naturalHeight * scale) / 2
  }

  function onWheel(event) {
    if (!(event.ctrlKey || event.metaKey)) return // let the page scroll normally
    event.preventDefault()
    const delta = event.deltaY < 0 ? 1.1 : 1 / 1.1
    scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale * delta))
  }

  function onPointerDown(event) {
    dragging = true
    dragStartX = event.clientX - translateX
    dragStartY = event.clientY - translateY
  }

  function onPointerMove(event) {
    if (!dragging) return
    translateX = event.clientX - dragStartX
    translateY = event.clientY - dragStartY
  }

  function onPointerUp() {
    dragging = false
  }

  function exportSvg() {
    const svg = container?.querySelector('svg')
    if (!svg) return
    // Mermaid's SVG has no background rect — on a light-colored viewer
    // (most of them) the light text from our dark theme becomes unreadable.
    // Paint the same bg the in-app viewport uses so the exported file stands
    // on its own.
    const clone = svg.cloneNode(true)
    clone.style.background = diagramThemeVariables.background
    const blob = new Blob([clone.outerHTML], { type: 'image/svg+xml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${name || 'diagram'}.svg`
    a.click()
    URL.revokeObjectURL(url)
  }
</script>

<div class="space-y-2">
  <div class="flex items-center justify-end gap-2">
    <button type="button" class="btn-ghost text-xs px-2 py-1" aria-label="Zoom out" on:click={() => (scale = Math.max(MIN_SCALE, scale / 1.1))}>−</button>
    <button type="button" class="btn-ghost text-xs px-2 py-1" on:click={resetView}>Reset</button>
    <button type="button" class="btn-ghost text-xs px-2 py-1" aria-label="Fit to view" on:click={fitToView}>Fit</button>
    <button type="button" class="btn-ghost text-xs px-2 py-1" aria-label="Zoom in" on:click={() => (scale = Math.min(MAX_SCALE, scale * 1.1))}>+</button>
    {#if isMermaid}
      <button type="button" class="btn-ghost text-xs px-2 py-1" on:click={exportSvg} disabled={!!renderError}>
        Export SVG
      </button>
    {/if}
  </div>

  <div
    bind:this={viewport}
    role="application"
    aria-label="{name} diagram viewport — hold Ctrl or Cmd and scroll to zoom, drag to pan"
    class="relative overflow-hidden rounded-panel border border-c-border bg-c-well h-[480px] cursor-grab"
    on:wheel={onWheel}
    on:pointerdown={onPointerDown}
    on:pointermove={onPointerMove}
    on:pointerup={onPointerUp}
    on:pointerleave={onPointerUp}
  >
    <div
      class="absolute top-0 left-0 origin-top-left"
      style="transform: translate({translateX}px, {translateY}px) scale({scale});"
    >
      {#if isMermaid}
        <div bind:this={container} class="diagram-svg" class:hidden={renderError !== null}></div>
      {:else}
        <img src={`data:${mediaType};base64,${content}`} alt={name} draggable="false" on:load={fitToView} />
      {/if}
    </div>
  </div>

  {#if renderError}
    <div class="rounded-panel border border-c-high/40 bg-c-high/5 px-4 py-4 space-y-3">
      <p class="text-sm font-medium text-c-high">Diagram rendering failed</p>
      <p class="text-xs text-c-muted">{renderError}</p>
      <div class="flex gap-2">
        <button type="button" class="btn-ghost text-xs px-3 py-1.5" on:click={() => renderMermaid(content)}>
          Retry
        </button>
        <button type="button" class="btn-ghost text-xs px-3 py-1.5" on:click={() => (showRawSource = !showRawSource)}>
          {showRawSource ? 'Hide' : 'Show'} raw source
        </button>
      </div>
      {#if showRawSource}
        <pre class="font-mono text-xs text-c-text2 bg-c-well border border-c-border rounded-panel p-3 overflow-auto max-h-80 whitespace-pre">{content}</pre>
      {/if}
    </div>
  {/if}
</div>

<style>
  /* Mermaid's default flowchart output is square-cornered and flat; these
     soften it to match the rest of the app's rounded, shadowed cards.
     Scoped to .diagram-svg so it never touches markup outside this component. */
  .diagram-svg :global(.node rect) {
    /* rx/ry only apply to rect/ellipse — a polygon node (diamond/hexagon
       decision shapes) has no equivalent SVG attribute for rounding. */
    rx: 6px;
    ry: 6px;
  }
  .diagram-svg :global(.node rect),
  .diagram-svg :global(.node polygon) {
    filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.35));
  }
  /* Mermaid's .cluster class covers every subgraph, not specifically trust
     boundaries (it has no separate concept of one) — dashing every subgraph
     border is an acceptable broadening for uploaded architecture diagrams. */
  .diagram-svg :global(.cluster rect) {
    rx: 10px;
    ry: 10px;
    stroke-dasharray: 4 3;
  }
</style>
