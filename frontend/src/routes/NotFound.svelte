<script>
  import { link, location } from 'svelte-spa-router'
</script>

<div class="max-w-[760px] mx-auto py-16 text-center space-y-3">
  <h1 class="text-xl font-semibold text-c-text">Page not found</h1>
  <p class="text-sm text-c-muted">
    There is no page at <span class="font-mono text-c-text2">#{$location}</span>.
  </p>
  <a href="/" use:link class="btn-primary text-sm px-4 py-2 inline-block">Go to Threat Models</a>
</div>
