<script>
  import Comments from './Comments.svelte'

  /** @type {any[]} */
  export let items = []
  /** @type {string} */
  export let modelId = ''
  /** @type {string} */
  export let entityType = ''
  /** @type {Record<string, number>} */
  export let commentCounts = {}

  let expandedId = null

  function toggle(id) {
    expandedId = expandedId === id ? null : id
  }

  function handleChange(id, e) {
    commentCounts[id] = (commentCounts[id] || 0) + e.detail.delta
    commentCounts = commentCounts
  }

  function itemLabel(item) {
    return item.name || item.source_entity || item.id
  }
</script>

{#each items as item (item.id)}
  {#if (commentCounts[item.id] || 0) > 0 || expandedId === item.id}
    <div class="ml-1 mt-1 mb-2">
      <button type="button" on:click={() => toggle(item.id)}
        class="inline-flex items-center gap-1 text-xs text-c-faint hover:text-c-accent transition-colors">
        <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M18 10c0 3.866-3.582 7-8 7a8.841 8.841 0 01-4.083-.98L2 17l1.338-3.123C2.493 12.767 2 11.434 2 10c0-3.866 3.582-7 8-7s8 3.134 8 7zM7 9H5v2h2V9zm8 0h-2v2h2V9zm-4 0H9v2h2V9z" clip-rule="evenodd"/></svg>
        {commentCounts[item.id] || 0} on {itemLabel(item)}
      </button>
      {#if expandedId === item.id}
        <div class="mt-1">
          <Comments {modelId} {entityType} entityId={item.id} compact={true}
            on:comment-change={e => handleChange(item.id, e)} />
        </div>
      {/if}
    </div>
  {/if}
{/each}
