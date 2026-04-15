<script>
  // v1: informational panel only — no backend API to persist MCP config
</script>

<div class="bg-slate-50 rounded-xl border border-slate-200 p-5 space-y-3">
  <div class="flex items-center gap-2">
    <svg class="w-4 h-4 text-slate-500" viewBox="0 0 20 20" fill="currentColor">
      <path fill-rule="evenodd" d="M12.316 3.051a1 1 0 01.633 1.265l-4 12a1 1 0 11-1.898-.632l4-12a1 1 0 011.265-.633zM5.707 6.293a1 1 0 010 1.414L3.414 10l2.293 2.293a1 1 0 11-1.414 1.414l-3-3a1 1 0 010-1.414l3-3a1 1 0 011.414 0zm8.586 0a1 1 0 011.414 0l3 3a1 1 0 010 1.414l-3 3a1 1 0 11-1.414-1.414L16.586 10l-2.293-2.293a1 1 0 010-1.414z" clip-rule="evenodd"/>
    </svg>
    <h3 class="text-sm font-semibold text-slate-700">Code Context via context-link</h3>
  </div>
  <p class="text-sm text-slate-600">
    The pipeline can analyze your codebase to produce more targeted threats. Code context is provided via the <strong>context-link</strong> MCP server, which indexes your repository and exposes it over the Model Context Protocol.
  </p>

  <div class="space-y-2">
    <p class="text-xs font-semibold text-slate-500 uppercase tracking-wide">Using the CLI</p>
    <pre class="text-xs font-mono bg-white border border-slate-200 rounded-md p-3 overflow-auto">python -m cli.main run \
  --description "Your system description" \
  --code /path/to/your/repo \
  --provider anthropic</pre>
  </div>

  <div class="space-y-2">
    <p class="text-xs font-semibold text-slate-500 uppercase tracking-wide">Environment variable</p>
    <pre class="text-xs font-mono bg-white border border-slate-200 rounded-md p-3">CONTEXT_LINK_BINARY=/path/to/context-link</pre>
    <p class="text-xs text-slate-500">
      The binary is pre-built at <code class="font-mono bg-slate-100 px-1 py-0.5 rounded">bin/context-link</code> inside the Docker image. For local development, build it from <code class="font-mono bg-slate-100 px-1 py-0.5 rounded">context-link/</code> with <code class="font-mono bg-slate-100 px-1 py-0.5 rounded">go build</code>.
    </p>
  </div>
</div>
