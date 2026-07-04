<script>
  import { onMount } from 'svelte'
  import { currentUser, notify } from '../lib/stores.js'
  import { listComments, createComment, updateComment, deleteComment } from '../lib/api.js'
  import { initials, relativeTime } from '../lib/utils.js'

  /** @type {string} */
  export let modelId = ''

  let comments = []
  let loading = true
  let draft = ''
  let posting = false
  let editingId = null
  let editDraft = ''
  let replyToId = null
  let replyDraft = ''

  // One level of nesting only — replies never get their own reply/edit UI
  // for grandchildren, matching the comments.parent_id self-reference model.
  $: threaded = nest(comments)

  onMount(load)

  async function load() {
    loading = true
    try {
      comments = await listComments(modelId)
    } catch (err) {
      notify('error', `Failed to load comments: ${err.message}`)
    } finally {
      loading = false
    }
  }

  function nest(flat) {
    const byId = new Map(flat.map(c => [c.id, { ...c, replies: [] }]))
    const roots = []
    for (const c of byId.values()) {
      if (c.parent_id && byId.has(c.parent_id)) {
        byId.get(c.parent_id).replies.push(c)
      } else {
        roots.push(c)
      }
    }
    return roots
  }

  function isAuthor(comment) {
    return $currentUser?.is_admin || comment.user_id === $currentUser?.id
  }

  async function post() {
    if (!draft.trim()) return
    posting = true
    try {
      const created = await createComment(modelId, { body: draft.trim() })
      comments = [...comments, created]
      draft = ''
    } catch (err) {
      notify('error', `Comment failed: ${err.message}`)
    } finally {
      posting = false
    }
  }

  async function postReply(parentId) {
    if (!replyDraft.trim()) return
    try {
      const created = await createComment(modelId, { body: replyDraft.trim(), parent_id: parentId })
      comments = [...comments, created]
      replyToId = null
      replyDraft = ''
    } catch (err) {
      notify('error', `Reply failed: ${err.message}`)
    }
  }

  function startEdit(comment) {
    editingId = comment.id
    editDraft = comment.body
  }

  async function saveEdit(comment) {
    if (!editDraft.trim()) return
    try {
      const updated = await updateComment(comment.id, { body: editDraft.trim() })
      comments = comments.map(c => c.id === comment.id ? updated : c)
      editingId = null
    } catch (err) {
      notify('error', `Edit failed: ${err.message}`)
    }
  }

  async function remove(comment) {
    if (!confirm('Delete this comment?')) return
    try {
      await deleteComment(comment.id)
      comments = comments.filter(c => c.id !== comment.id && c.parent_id !== comment.id)
    } catch (err) {
      notify('error', `Delete failed: ${err.message}`)
    }
  }
</script>

<div class="card p-5">
  <h2 class="text-xs font-semibold text-c-muted uppercase tracking-wide mb-4">
    Discussion {#if comments.length > 0}<span class="normal-case font-mono text-c-faint">({comments.length})</span>{/if}
  </h2>

  {#if loading}
    <div class="flex justify-center py-8">
      <div class="w-5 h-5 border-2 border-c-accent border-t-transparent rounded-full animate-spin-slow"></div>
    </div>
  {:else}
    {#if threaded.length === 0}
      <p class="text-sm text-c-faint py-2">No comments yet.</p>
    {:else}
      <div class="space-y-4">
        {#each threaded as comment (comment.id)}
          <div class="flex gap-3">
            <div class="w-7 h-7 rounded-full bg-c-accent/20 border border-c-accent/40 flex items-center justify-center flex-shrink-0">
              <span class="font-mono text-[10px] font-semibold text-c-accent">
                {initials(comment.display_name || comment.username || '?')}
              </span>
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="text-sm font-medium text-c-text2">{comment.display_name || comment.username || 'Unknown'}</span>
                <span class="font-mono text-[10px] text-c-faint">{relativeTime(comment.created_at)}</span>
              </div>

              {#if editingId === comment.id}
                <textarea bind:value={editDraft} rows="2" class="field text-sm w-full mt-1.5"></textarea>
                <div class="flex gap-2 mt-1.5">
                  <button type="button" on:click={() => saveEdit(comment)} class="btn-primary text-xs px-3 py-1">Save</button>
                  <button type="button" on:click={() => editingId = null} class="btn-ghost text-xs px-3 py-1">Cancel</button>
                </div>
              {:else}
                <p class="text-sm text-c-text2 mt-1 whitespace-pre-line">{comment.body}</p>
                <div class="flex items-center gap-3 mt-1">
                  <button type="button" on:click={() => { replyToId = replyToId === comment.id ? null : comment.id; replyDraft = '' }} class="text-xs text-c-faint hover:text-c-accent transition-colors">
                    Reply
                  </button>
                  {#if isAuthor(comment)}
                    <button type="button" on:click={() => startEdit(comment)} class="text-xs text-c-faint hover:text-c-accent transition-colors">Edit</button>
                    <button type="button" on:click={() => remove(comment)} class="text-xs text-c-faint hover:text-c-critical transition-colors">Delete</button>
                  {/if}
                </div>
              {/if}

              {#if replyToId === comment.id}
                <div class="flex gap-2 mt-2">
                  <textarea bind:value={replyDraft} rows="2" placeholder="Write a reply…" class="field text-sm flex-1"></textarea>
                  <button type="button" on:click={() => postReply(comment.id)} class="btn-primary text-xs px-3 self-start">Reply</button>
                </div>
              {/if}

              {#each comment.replies as reply (reply.id)}
                <div class="flex gap-3 ml-2 mt-3 pl-3 border-l border-c-divider">
                  <div class="w-6 h-6 rounded-full bg-c-accent/20 border border-c-accent/40 flex items-center justify-center flex-shrink-0">
                    <span class="font-mono text-[9px] font-semibold text-c-accent">
                      {initials(reply.display_name || reply.username || '?')}
                    </span>
                  </div>
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                      <span class="text-sm font-medium text-c-text2">{reply.display_name || reply.username || 'Unknown'}</span>
                      <span class="font-mono text-[10px] text-c-faint">{relativeTime(reply.created_at)}</span>
                    </div>

                    {#if editingId === reply.id}
                      <textarea bind:value={editDraft} rows="2" class="field text-sm w-full mt-1.5"></textarea>
                      <div class="flex gap-2 mt-1.5">
                        <button type="button" on:click={() => saveEdit(reply)} class="btn-primary text-xs px-3 py-1">Save</button>
                        <button type="button" on:click={() => editingId = null} class="btn-ghost text-xs px-3 py-1">Cancel</button>
                      </div>
                    {:else}
                      <p class="text-sm text-c-text2 mt-1 whitespace-pre-line">{reply.body}</p>
                      {#if isAuthor(reply)}
                        <div class="flex items-center gap-3 mt-1">
                          <button type="button" on:click={() => startEdit(reply)} class="text-xs text-c-faint hover:text-c-accent transition-colors">Edit</button>
                          <button type="button" on:click={() => remove(reply)} class="text-xs text-c-faint hover:text-c-critical transition-colors">Delete</button>
                        </div>
                      {/if}
                    {/if}
                  </div>
                </div>
              {/each}
            </div>
          </div>
        {/each}
      </div>
    {/if}

    <div class="flex gap-2 mt-5 pt-4 border-t border-c-border">
      <textarea bind:value={draft} rows="2" placeholder="Add a comment…" class="field text-sm flex-1"></textarea>
      <button type="button" on:click={post} disabled={posting || !draft.trim()} class="btn-primary text-sm px-4 self-start disabled:opacity-50">
        Post
      </button>
    </div>
  {/if}
</div>
