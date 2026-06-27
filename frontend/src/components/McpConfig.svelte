<script>
  // v1: informational panel only — no backend API to persist MCP config
</script>

<div class="card p-5 space-y-4">
  <div class="flex items-center gap-2">
    <svg class="w-4 h-4 text-c-accent" viewBox="0 0 20 20" fill="currentColor">
      <path fill-rule="evenodd" d="M12.316 3.051a1 1 0 01.633 1.265l-4 12a1 1 0 11-1.898-.632l4-12a1 1 0 011.265-.633zM5.707 6.293a1 1 0 010 1.414L3.414 10l2.293 2.293a1 1 0 11-1.414 1.414l-3-3a1 1 0 010-1.414l3-3a1 1 0 011.414 0zm8.586 0a1 1 0 011.414 0l3 3a1 1 0 010 1.414l-3 3a1 1 0 11-1.414-1.414L16.586 10l-2.293-2.293a1 1 0 010-1.414z" clip-rule="evenodd"/>
    </svg>
    <h3 class="text-sm font-semibold text-c-text">Code Context via context-link</h3>
  </div>
  <p class="text-sm text-c-muted">
    The pipeline can analyze your codebase to produce more targeted threats. Code context is provided via the <strong class="text-c-text2">context-link</strong> MCP server, which indexes your repository and exposes it over the Model Context Protocol.
  </p>

  <div class="space-y-2">
    <p class="font-mono text-[10px] font-semibold text-c-faint uppercase tracking-wide">Using the CLI</p>
    <pre class="text-[12px] font-mono bg-c-well border border-c-border rounded-panel p-3 overflow-auto text-c-text2">python -m cli.main run \
  --description "Your system description" \
  --code /path/to/your/repo \
  --provider anthropic</pre>
  </div>

  <div class="space-y-2">
    <p class="font-mono text-[10px] font-semibold text-c-faint uppercase tracking-wide">Environment variable</p>
    <pre class="text-[12px] font-mono bg-c-well border border-c-border rounded-panel p-3 text-c-text2">CONTEXT_LINK_BINARY=/path/to/context-link</pre>
    <p class="text-xs text-c-muted">
      The binary is pre-built at <code class="font-mono bg-c-well border border-c-border px-1 py-0.5 rounded text-c-accent text-[11px]">bin/context-link</code> inside the Docker image. For local development, build it from <code class="font-mono bg-c-well border border-c-border px-1 py-0.5 rounded text-c-accent text-[11px]">context-link/</code> with <code class="font-mono bg-c-well border border-c-border px-1 py-0.5 rounded text-c-accent text-[11px]">go build</code>.
    </p>
  </div>
</div>
