<script>
  /**
   * ResourceList — inline CRUD panel for assets, flows, or trust boundaries.
   *
   * Props:
   *   items        — current list of records (reactive, mutated in place)
   *   fields       — field definitions: [{ key, label, type?, options? }]
   *   onCreate     — async (draft) => newRecord
   *   onUpdate     — async (id, patch) => updatedRecord
   *   onDelete     — async (id) => void
   *   emptyLabel   — text when list is empty
   */
  import { notify } from '../lib/stores.js'

  /** @type {Array<Record<string, any>>} */
  export let items = []
  /** @type {Array<{ key: string, label: string, type?: string, options?: string[] }>} */
  export let fields = []
  /** @type {(draft: object) => Promise<object>} */
  export let onCreate
  /** @type {(id: string, patch: object) => Promise<object>} */
  export let onUpdate
  /** @type {(id: string) => Promise<void>} */
  export let onDelete
  export let emptyLabel = 'No items yet.'

  let addingNew = false
  let savingNew = false
  /** @type {string|null} */
  let editingId = null
  /** @type {Record<string, any>} */
  let editDraft = {}
  let savingEdit = false
  /** @type {Record<string, any>} */
  let newDraft = {}
  /** @type {Record<string, boolean>} */
  let deletingId = {}

  export function startAdd() {
    newDraft = Object.fromEntries(fields.map(f => [f.key, f.default ?? '']))
    addingNew = true
  }

  function cancelAdd() {
    addingNew = false
    newDraft = {}
  }

  function startEdit(item) {
    editingId = item.id
    editDraft = { ...item }
  }

  function cancelEdit() {
    editingId = null
    editDraft = {}
  }

  async function submitAdd() {
    savingNew = true
    try {
      const created = await onCreate(newDraft)
      items = [...items, created]
      cancelAdd()
    } catch (err) {
      notify('error', `Failed to create: ${err.message}`)
    } finally {
      savingNew = false
    }
  }

  async function submitEdit(id) {
    savingEdit = true
    try {
      const updated = await onUpdate(id, editDraft)
      items = items.map(it => (it.id === id ? updated : it))
      cancelEdit()
    } catch (err) {
      notify('error', `Failed to update: ${err.message}`)
    } finally {
      savingEdit = false
    }
  }

  async function remove(id) {
    deletingId = { ...deletingId, [id]: true }
    try {
      await onDelete(id)
      items = items.filter(it => it.id !== id)
    } catch (err) {
      notify('error', `Failed to delete: ${err.message}`)
    } finally {
      const { [id]: _, ...rest } = deletingId
      deletingId = rest
    }
  }

  function displayValue(item, f) {
    const v = item[f.key]
    if (v == null || v === '') return '—'
    return v
  }
</script>

<div class="space-y-2">
  {#if items.length === 0 && !addingNew}
    <p class="text-xs text-slate-400 py-1">{emptyLabel}</p>
  {/if}

  {#each items as item (item.id)}
    {#if editingId === item.id}
      <!-- Inline edit form -->
      <div class="bg-slate-50 border border-indigo-200 rounded-lg p-3 space-y-2">
        {#each fields as f}
          <div>
            <label class="block text-xs font-medium text-slate-600 mb-0.5">{f.label}</label>
            {#if f.type === 'select'}
              <select
                bind:value={editDraft[f.key]}
                class="block w-full rounded border-slate-300 text-sm focus:border-indigo-500 focus:ring-indigo-500"
              >
                {#each f.options ?? [] as opt}
                  <option value={opt}>{opt}</option>
                {/each}
              </select>
            {:else if f.type === 'textarea'}
              <textarea
                bind:value={editDraft[f.key]}
                rows="2"
                class="block w-full rounded border-slate-300 text-sm focus:border-indigo-500 focus:ring-indigo-500 resize-none"
              ></textarea>
            {:else}
              <input
                type="text"
                bind:value={editDraft[f.key]}
                class="block w-full rounded border-slate-300 text-sm focus:border-indigo-500 focus:ring-indigo-500"
              />
            {/if}
          </div>
        {/each}
        <div class="flex gap-2 pt-1">
          <button
            type="button"
            on:click={() => submitEdit(item.id)}
            disabled={savingEdit}
            class="px-3 py-1 text-xs font-medium text-white bg-indigo-600 rounded hover:bg-indigo-700 disabled:opacity-50"
          >
            {savingEdit ? 'Saving…' : 'Save'}
          </button>
          <button
            type="button"
            on:click={cancelEdit}
            class="px-3 py-1 text-xs font-medium text-slate-600 bg-white border border-slate-300 rounded hover:bg-slate-50"
          >
            Cancel
          </button>
        </div>
      </div>
    {:else}
      <!-- Read row -->
      <div class="flex items-start gap-2 group py-1 border-b border-slate-50 last:border-0">
        <div class="flex-1 min-w-0">
          {#each fields as f, fi}
            {#if fi === 0}
              <span class="text-sm font-medium text-slate-800">{displayValue(item, f)}</span>
            {:else if f.type === 'badge' || f.display === 'badge'}
              <span class="ml-1.5 text-xs px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-mono">
                {displayValue(item, f)}
              </span>
            {:else}
              <span class="text-xs text-slate-500 ml-1.5">{displayValue(item, f)}</span>
            {/if}
          {/each}
        </div>
        <div class="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
          <button
            type="button"
            on:click={() => startEdit(item)}
            title="Edit"
            class="p-1 text-slate-400 hover:text-indigo-600 rounded"
          >
            <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
              <path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/>
            </svg>
          </button>
          <button
            type="button"
            on:click={() => remove(item.id)}
            disabled={deletingId[item.id]}
            title="Delete"
            class="p-1 text-slate-400 hover:text-red-500 rounded disabled:opacity-40"
          >
            <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/>
            </svg>
          </button>
        </div>
      </div>
    {/if}
  {/each}

  {#if addingNew}
    <!-- New item form -->
    <div class="bg-slate-50 border border-indigo-200 rounded-lg p-3 space-y-2 mt-1">
      {#each fields as f}
        <div>
          <label class="block text-xs font-medium text-slate-600 mb-0.5">{f.label}</label>
          {#if f.type === 'select'}
            <select
              bind:value={newDraft[f.key]}
              class="block w-full rounded border-slate-300 text-sm focus:border-indigo-500 focus:ring-indigo-500"
            >
              {#each f.options ?? [] as opt}
                <option value={opt}>{opt}</option>
              {/each}
            </select>
          {:else if f.type === 'textarea'}
            <textarea
              bind:value={newDraft[f.key]}
              rows="2"
              class="block w-full rounded border-slate-300 text-sm focus:border-indigo-500 focus:ring-indigo-500 resize-none"
            ></textarea>
          {:else}
            <input
              type="text"
              bind:value={newDraft[f.key]}
              class="block w-full rounded border-slate-300 text-sm focus:border-indigo-500 focus:ring-indigo-500"
            />
          {/if}
        </div>
      {/each}
      <div class="flex gap-2 pt-1">
        <button
          type="button"
          on:click={submitAdd}
          disabled={savingNew}
          class="px-3 py-1 text-xs font-medium text-white bg-indigo-600 rounded hover:bg-indigo-700 disabled:opacity-50"
        >
          {savingNew ? 'Adding…' : 'Add'}
        </button>
        <button
          type="button"
          on:click={cancelAdd}
          class="px-3 py-1 text-xs font-medium text-slate-600 bg-white border border-slate-300 rounded hover:bg-slate-50"
        >
          Cancel
        </button>
      </div>
    </div>
  {/if}
</div>
