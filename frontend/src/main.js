// Self-hosted (latin subset only) so the UI renders correctly under a CSP
// without `font-src https://fonts.gstatic.com` and works fully offline.
import '@fontsource/ibm-plex-sans/latin-400.css'
import '@fontsource/ibm-plex-sans/latin-500.css'
import '@fontsource/ibm-plex-sans/latin-600.css'
import '@fontsource/ibm-plex-sans/latin-700.css'
import '@fontsource/ibm-plex-mono/latin-400.css'
import '@fontsource/ibm-plex-mono/latin-500.css'
import '@fontsource/ibm-plex-mono/latin-600.css'
import './app.css'
import App from './App.svelte'
import { mount } from 'svelte'

// After a deploy the content-hashed chunk filenames change. If a user has an
// old tab open, the browser may try to dynamically import a chunk that no longer
// exists and surface "Failed to fetch dynamically imported module". Reloading
// picks up the new index.html and new hashes — the user sees a brief flash
// instead of a hard error.
window.addEventListener('vite:preloadError', () => {
  window.location.reload()
})

const app = mount(App, {
  target: document.getElementById('app'),
})

export default app
