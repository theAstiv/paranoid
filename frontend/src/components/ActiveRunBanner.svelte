<script>
  import { activeRunMessage } from '../lib/run_watch.js'

  /** @type {'run' | 'extract'} */
  export let kind = 'run'
</script>

<div role="status" class="card px-5 py-4 flex items-center gap-3 border-c-blue/30 bg-c-blue/5">
  <div class="w-4 h-4 border-2 border-c-blue border-t-transparent rounded-full animate-spin-slow flex-shrink-0"></div>
  <div>
    <p class="text-sm font-medium text-c-blue">{activeRunMessage(kind)}</p>
    <p class="text-xs text-c-muted mt-0.5">This page reloads when it finishes.</p>
  </div>
</div>
