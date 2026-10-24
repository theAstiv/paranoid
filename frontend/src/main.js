// Self-hosted (latin subset only) so the UI renders correctly under a CSP
// without `font-src https://fonts.gstatic.com` and works fully offline.
import '@fontsource/ibm-plex-sans/latin-400.css'
import '@fontsource/ibm-plex-sans/latin-500.css'
import '@fontsource/ibm-plex-sans/latin-600.css'
import '@fontsource/ibm-plex-sans/latin-700.css'
// A real italic face for the muted empty-state captions (Tailwind `italic`);
// without it the browser slants the upright font.
import '@fontsource/ibm-plex-sans/latin-400-italic.css'
import '@fontsource/ibm-plex-mono/latin-400.css'
import '@fontsource/ibm-plex-mono/latin-500.css'
import '@fontsource/ibm-plex-mono/latin-600.css'
import './app.css'
import App from './App.svelte'
import { mount } from 'svelte'
import { createChunkErrorHandler } from './lib/chunk_reload.js'

// A stale tab after a deploy reloads once to pick up the new chunk names;
// see lib/chunk_reload.js for why only once.
window.addEventListener('vite:preloadError', createChunkErrorHandler())

const app = mount(App, {
  target: document.getElementById('app'),
})

export default app
