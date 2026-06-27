const BASE = '/api'

// Track in-flight refresh to prevent parallel refresh races
let _refreshPromise = null

/**
 * Core fetch wrapper.
 * - Attaches Authorization: Bearer header from localStorage token (if present).
 * - On 401: attempts one silent token refresh, then retries.
 * - On second 401 after refresh: clears token + redirects to /app/login.
 */
async function request(method, path, body, extraHeaders = {}, signal = undefined, _retrying = false) {
  const { getStoredToken, setStoredToken, clearStoredToken, currentUser } = await import('./stores.js')

  const token = getStoredToken()
  const headers = { ...extraHeaders }
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const opts = { method, headers }
  if (body !== undefined) opts.body = JSON.stringify(body)
  if (signal !== undefined) opts.signal = signal

  const res = await fetch(BASE + path, opts)

  // Retry 401 after refresh still failed: full auth clear
  if (res.status === 401 && _retrying) {
    clearStoredToken()
    currentUser.set(null)
    window.location.hash = '#/login'
    throw new Error('Session expired — please log in again')
  }

  // First 401: attempt refresh once, then retry
  if (res.status === 401 && !_retrying) {
    try {
      if (!_refreshPromise) {
        _refreshPromise = _doRefresh()
      }
      const newToken = await _refreshPromise
      if (newToken) {
        setStoredToken(newToken)
        return request(method, path, body, extraHeaders, signal, true)
      }
    } catch {
      // refresh failed — fall through to clear below
    } finally {
      _refreshPromise = null
    }
    // Refresh failed or returned no token: clear auth and redirect to login
    clearStoredToken()
    currentUser.set(null)
    window.location.hash = '#/login'
    throw new Error('Session expired — please log in again')
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }
  if (res.status === 204) return null
  return res.json()
}

/** Attempt a silent token refresh using the HttpOnly cookie. */
async function _doRefresh() {
  const res = await fetch(`${BASE}/auth/refresh`, { method: 'POST' })
  if (!res.ok) return null
  const data = await res.json()
  return data.access_token || null
}

// ── Auth API ──────────────────────────────────────────────────────────────────

/**
 * @param {{ username: string, email: string, password: string, display_name?: string }} body
 */
export function register(body) {
  return request('POST', '/auth/register', body)
}

/**
 * @param {{ username: string, password: string }} body
 * @returns {Promise<{ access_token: string, user: object }>}
 */
export async function login(body) {
  const { setStoredToken, currentUser } = await import('./stores.js')
  const data = await request('POST', '/auth/login', body)
  if (data?.access_token) {
    setStoredToken(data.access_token)
    currentUser.set(data.user)
  }
  return data
}

/** Log out and clear local auth state. */
export async function logout() {
  const { clearStoredToken, currentUser } = await import('./stores.js')
  try {
    await request('POST', '/auth/logout', {})
  } finally {
    clearStoredToken()
    currentUser.set(null)
  }
}

/** Fetch current user profile and update the currentUser store. */
export async function fetchMe() {
  const { currentUser, authLoading } = await import('./stores.js')
  try {
    const user = await request('GET', '/auth/me')
    currentUser.set(user)
    return user
  } catch {
    currentUser.set(null)
    return null
  } finally {
    authLoading.set(false)
  }
}

/** @param {{ name: string, expires_in_days?: number }} body */
export function createPAT(body) {
  return request('POST', '/auth/tokens', body)
}

export function listPATs() {
  return request('GET', '/auth/tokens')
}

/** @param {string} tokenId */
export function deletePAT(tokenId) {
  return request('DELETE', `/auth/tokens/${tokenId}`)
}

/** @param {{ display_name?: string, password?: string, current_password?: string }} body */
export function updateMe(body) {
  return request('PATCH', '/auth/me', body)
}

// ── Models ────────────────────────────────────────────────────────────────────

/**
 * @param {{ limit?: number, framework?: string, status?: string }} [params]
 */
export function listModels(params = {}) {
  const qs = new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v != null))
  ).toString()
  return request('GET', `/models${qs ? '?' + qs : ''}`)
}

/**
 * @param {{ title: string, description: string, framework: string, iteration_count: number }} body
 */
export function createModel(body) {
  return request('POST', '/models', body)
}

/** @param {string} id */
export function getModel(id) {
  return request('GET', `/models/${id}`)
}

/** @param {string} id @param {object} body */
export function updateModel(id, body) {
  return request('PATCH', `/models/${id}`, body)
}

/** @param {string} id */
export function deleteModel(id) {
  return request('DELETE', `/models/${id}`)
}

/** @param {string} id @param {{ status?: string }} [params] */
export function getModelThreats(id, params = {}) {
  const qs = new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v != null))
  ).toString()
  return request('GET', `/models/${id}/threats${qs ? '?' + qs : ''}`)
}

/** @param {string} id */
export function getModelAssets(id) {
  return request('GET', `/models/${id}/assets`)
}

/** @param {string} id */
export function getModelFlows(id) {
  return request('GET', `/models/${id}/flows`)
}

/** @param {string} id */
export function getModelTrustBoundaries(id) {
  return request('GET', `/models/${id}/trust-boundaries`)
}

/** @param {string} id */
export function getModelStats(id) {
  return request('GET', `/models/${id}/stats`)
}

// ── Pipeline SSE ──────────────────────────────────────────────────────────────

/**
 * POSTs to `path` and streams the SSE response through the callbacks.
 * Used by both /run and /extract — both emit the same event format.
 * `onDone` fires exactly once, regardless of whether the stream ended via a
 * 'complete' event, reader EOF, or an error.
 *
 * @param {string} path  – relative to BASE, e.g. `/models/abc/run`
 * @param {RequestInit} init  – fetch init (method, body, headers)
 * @param {(event: object) => void} onEvent
 * @param {(err: Error) => void} onError
 * @param {() => void} onDone
 * @returns {() => void} abort function
 */
function subscribeSSE(path, init, onEvent, onError, onDone) {
  const controller = new AbortController()
  let doneFired = false
  const fireDone = () => { if (!doneFired) { doneFired = true; onDone() } }

  async function _readStream(res) {
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const parts = buf.split('\n\n')
        buf = parts.pop()
        for (const part of parts) {
          const dataLine = part.split('\n').find(l => l.startsWith('data:'))
          if (!dataLine) continue
          try {
            const parsed = JSON.parse(dataLine.slice(5).trim())
            onEvent(parsed)
            if (parsed.step === 'complete') {
              fireDone()
              return
            }
          } catch (parseErr) {
            console.warn('subscribeSSE: malformed SSE JSON', parseErr)
          }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') onError(err)
    } finally {
      fireDone()
    }
  }

  ;(async () => {
    const { getStoredToken, setStoredToken } = await import('./stores.js')
    let token = getStoredToken()
    let authHeaders = token ? { 'Authorization': `Bearer ${token}` } : {}

    let res
    try {
      res = await fetch(`${BASE}${path}`, {
        ...init,
        headers: { ...(init.headers || {}), ...authHeaders },
        signal: controller.signal,
      })
    } catch (err) {
      if (err.name !== 'AbortError') onError(err)
      fireDone()
      return
    }

    // On 401: attempt a single token refresh and retry the SSE connection
    if (res.status === 401) {
      try {
        if (!_refreshPromise) _refreshPromise = _doRefresh()
        const newToken = await _refreshPromise
        _refreshPromise = null
        if (newToken) {
          setStoredToken(newToken)
          authHeaders = { 'Authorization': `Bearer ${newToken}` }
          try {
            res = await fetch(`${BASE}${path}`, {
              ...init,
              headers: { ...(init.headers || {}), ...authHeaders },
              signal: controller.signal,
            })
          } catch (retryErr) {
            if (retryErr.name !== 'AbortError') onError(retryErr)
            fireDone()
            return
          }
        }
      } catch {
        _refreshPromise = null
      }
    }

    if (!res.ok) {
      const detail = await res.json().catch(() => ({ detail: res.statusText }))
      onError(new Error(detail.detail || res.statusText))
      fireDone()
      return
    }

    await _readStream(res)
  })()

  return () => controller.abort()
}

/**
 * Stream pipeline SSE events.
 * Uses fetch + ReadableStream because EventSource does not support POST.
 *
 * @param {string} modelId
 * @param {FormData} formData  – assumptions (JSON str), has_ai_components, diagram (optional)
 * @param {(event: object) => void} onEvent
 * @param {(err: Error) => void} onError
 * @param {() => void} onDone
 * @returns {() => void}  abort function
 */
export function subscribeToRun(modelId, formData, onEvent, onError, onDone) {
  return subscribeSSE(
    `/models/${modelId}/run`,
    { method: 'POST', body: formData },
    onEvent, onError, onDone,
  )
}

// ── Threats ───────────────────────────────────────────────────────────────────

/** @param {string} id */
export function getThreat(id) {
  return request('GET', `/threats/${id}`)
}

/** @param {string} id @param {object} body flat PATCH fields */
export function updateThreat(id, body) {
  return request('PATCH', `/threats/${id}`, body)
}

/** @param {string} id */
export function deleteThreat(id) {
  return request('DELETE', `/threats/${id}`)
}

/** @param {string} id */
export function generateAttackTree(id) {
  return request('POST', `/threats/${id}/attack-tree`)
}

/** @param {string} id */
export function listAttackTrees(id) {
  return request('GET', `/threats/${id}/attack-trees`)
}

/** @param {string} id */
export function generateTestCases(id) {
  return request('POST', `/threats/${id}/test-cases`)
}

/** @param {string} id */
export function listTestCases(id) {
  return request('GET', `/threats/${id}/test-cases`)
}

// ── Assets CRUD ───────────────────────────────────────────────────────────────

/** @param {string} modelId @param {{ name: string, type?: string, description?: string }} body */
export function createAsset(modelId, body) {
  return request('POST', `/models/${modelId}/assets`, body)
}

/** @param {string} modelId @param {string} assetId @param {object} body */
export function updateAsset(modelId, assetId, body) {
  return request('PATCH', `/models/${modelId}/assets/${assetId}`, body)
}

/** @param {string} modelId @param {string} assetId */
export function deleteAsset(modelId, assetId) {
  return request('DELETE', `/models/${modelId}/assets/${assetId}`)
}

// ── Flows CRUD ────────────────────────────────────────────────────────────────

/** @param {string} modelId @param {{ source_entity: string, target_entity: string, flow_description?: string }} body */
export function createFlow(modelId, body) {
  return request('POST', `/models/${modelId}/flows`, body)
}

/** @param {string} modelId @param {string} flowId @param {object} body */
export function updateFlow(modelId, flowId, body) {
  return request('PATCH', `/models/${modelId}/flows/${flowId}`, body)
}

/** @param {string} modelId @param {string} flowId */
export function deleteFlow(modelId, flowId) {
  return request('DELETE', `/models/${modelId}/flows/${flowId}`)
}

// ── Trust Boundaries CRUD ─────────────────────────────────────────────────────

/** @param {string} modelId @param {{ source_entity: string, target_entity: string, purpose?: string }} body */
export function createTrustBoundary(modelId, body) {
  return request('POST', `/models/${modelId}/trust-boundaries`, body)
}

/** @param {string} modelId @param {string} boundaryId @param {object} body */
export function updateTrustBoundary(modelId, boundaryId, body) {
  return request('PATCH', `/models/${modelId}/trust-boundaries/${boundaryId}`, body)
}

/** @param {string} modelId @param {string} boundaryId */
export function deleteTrustBoundary(modelId, boundaryId) {
  return request('DELETE', `/models/${modelId}/trust-boundaries/${boundaryId}`)
}

// ── Pre-flight & context extraction ──────────────────────────────────────────

/**
 * Analyze the model description for completeness gaps.
 * Returns { gaps: [{ field, severity, message }], is_sufficient: bool }
 * @param {string} id
 */
export function analyzeDescription(id) {
  return request('POST', `/models/${id}/analyze`)
}

/**
 * Run description + assumptions gap analysis without a saved model.
 * Designed for the wizard — call before the user commits to a full run.
 *
 * Returns {
 *   description: { gaps, is_sufficient },
 *   assumptions: { gaps, is_sufficient }
 * }
 *
 * @param {{ description: string, assumptions: string[], framework: string, hasAi: boolean, signal?: AbortSignal }} opts
 */
export function analyzeBundle({ description, assumptions = [], framework = 'STRIDE', hasAi = false, signal }) {
  return request(
    'POST',
    '/analyze/',
    {
      description,
      assumptions,
      framework: framework.toUpperCase() === 'HYBRID' ? 'STRIDE' : framework,
      has_ai_components: hasAi,
    },
    {},
    signal,
  )
}

/**
 * Run extraction-only pipeline (summarize + assets + flows), streaming SSE.
 *
 * @param {string} modelId
 * @param {(event: object) => void} onEvent
 * @param {(err: Error) => void} onError
 * @param {() => void} onDone
 * @returns {() => void} abort function
 */
export function subscribeToExtract(modelId, onEvent, onError, onDone) {
  return subscribeSSE(
    `/models/${modelId}/extract`,
    { method: 'POST' },
    onEvent, onError, onDone,
  )
}

// ── Export ────────────────────────────────────────────────────────────────────

/**
 * Returns the download URL for an export.
 * Caller uses window.open(url) to trigger the file download.
 *
 * @param {string} modelId
 * @param {'markdown'|'pdf'|'json'|'sarif'} format
 * @param {string} [statusFilter]
 * @returns {string}
 */
export function exportUrl(modelId, format, statusFilter) {
  const params = new URLSearchParams({ format })
  if (statusFilter) params.set('status_filter', statusFilter)
  return `${BASE}/export/${modelId}?${params.toString()}`
}

// ── Code Sources ─────────────────────────────────────────────────────────────

export function listCodeSources() {
  return request('GET', '/sources')
}

/** @param {{ name: string, git_url: string, ref?: string|null, pat?: string|null }} body */
export function createCodeSource(body) {
  return request('POST', '/sources', body)
}

/** @param {string} id */
export function deleteCodeSource(id) {
  return request('DELETE', `/sources/${id}`)
}

/** @param {string} id */
export function reindexSource(id) {
  return request('POST', `/sources/${id}/reindex`)
}

/**
 * Stream SSE progress events for a code source (GET endpoint).
 * The stream closes naturally when the source reaches a terminal state.
 * Keepalive pings (arrive as `{}` with no `status` field) are filtered
 * before reaching `onEvent`.
 *
 * Delegates to subscribeSSE so BASE, error handling, and abort logic
 * are defined in exactly one place.
 *
 * @param {string} sourceId
 * @param {(event: object) => void} onEvent
 * @param {(err: Error) => void} onError
 * @param {() => void} onDone  fired once when the stream ends
 * @returns {() => void} abort function
 */
export function subscribeToSourceEvents(sourceId, onEvent, onError, onDone) {
  return subscribeSSE(
    `/sources/${sourceId}/events`,
    { method: 'GET' },
    (evt) => { if (evt && evt.status) onEvent(evt) },
    onError,
    onDone,
  )
}

// ── Projects (Phase 2) ───────────────────────────────────────────────────────

export function listProjects() {
  return request('GET', '/projects')
}

/** @param {{ name: string, description?: string }} body */
export function createProject(body) {
  return request('POST', '/projects', body)
}

/** @param {string} id */
export function getProject(id) {
  return request('GET', `/projects/${id}`)
}

/** @param {string} id @param {{ name?: string, description?: string }} body */
export function updateProject(id, body) {
  return request('PATCH', `/projects/${id}`, body)
}

/** @param {string} id */
export function archiveProject(id) {
  return request('DELETE', `/projects/${id}`)
}

// ── Project members ───────────────────────────────────────────────────────────

/** @param {string} projectId */
export function listProjectMembers(projectId) {
  return request('GET', `/projects/${projectId}/members`)
}

/** @param {string} projectId @param {{ user_id: string, role: string }} body */
export function addProjectMember(projectId, body) {
  return request('POST', `/projects/${projectId}/members`, body)
}

/** @param {string} projectId @param {string} userId @param {{ role: string }} body */
export function updateProjectMember(projectId, userId, body) {
  return request('PATCH', `/projects/${projectId}/members/${userId}`, body)
}

/** @param {string} projectId @param {string} userId */
export function removeProjectMember(projectId, userId) {
  return request('DELETE', `/projects/${projectId}/members/${userId}`)
}

// ── Project invitations ───────────────────────────────────────────────────────

/** @param {string} projectId @param {{ invited_email: string, role: string }} body */
export function createProjectInvitation(projectId, body) {
  return request('POST', `/projects/${projectId}/invitations`, body)
}

/** @param {string} projectId */
export function listProjectInvitations(projectId) {
  return request('GET', `/projects/${projectId}/invitations`)
}

/** @param {string} invitationId */
export function acceptInvitation(invitationId) {
  return request('POST', `/invitations/${invitationId}/accept`, {})
}

/** @param {string} invitationId — declines/revokes a pending invitation */
export function declineInvitation(invitationId) {
  return request('POST', `/invitations/${invitationId}/decline`, {})
}

// ── Admin: users ──────────────────────────────────────────────────────────────

/** Admin only. Returns all registered users. */
export function listAllUsers() {
  return request('GET', '/users')
}

// ── Notifications (Phase 5 stubs) ─────────────────────────────────────────────

/** Returns user's notification list. Stubbed until Phase 5 backend ships. */
export function listNotifications() {
  return Promise.resolve([])
}

/** Marks all notifications read. Stubbed until Phase 5 backend ships. */
export function markAllNotificationsRead() {
  return Promise.resolve()
}

// ── Config & Health ───────────────────────────────────────────────────────────

export function getConfig() {
  return request('GET', '/config')
}

/**
 * Patch runtime settings. Non-key fields are in-memory (reset on restart);
 * API keys are persisted encrypted and survive restarts.
 *
 * For key fields (`anthropic_api_key`, `openai_api_key`):
 *   omit  → no change
 *   null  → clear
 *   "abc" → set
 *   ""    → 400 (use null to clear)
 *
 * Returns the parsed response body including the recomputed `first_run`.
 *
 * @param {object} body
 * @param {string} [secret] Value for X-Config-Secret header (required when CONFIG_SECRET env var is set on the backend)
 */
export function updateConfig(body, secret) {
  const headers = secret ? { 'X-Config-Secret': secret } : {}
  return request('PATCH', '/config', body, headers)
}

/**
 * Liveness probe for a provider. Body key overrides env/DB precedence.
 * Always resolves with { ok, latency_ms, provider, error, message } unless
 * the backend rate-limits (throws Error with retry-after detail).
 *
 * @param {{ provider: 'anthropic'|'openai'|'ollama', api_key?: string, model?: string, ollama_base_url?: string }} body
 */
export function testProvider(body) {
  return request('POST', '/config/test-provider', body)
}

export function getHealth() {
  return fetch('/health')
    .then(r => { if (!r.ok) throw new Error(r.statusText); return r.json() })
    .catch(() => ({ status: 'unreachable' }))
}
