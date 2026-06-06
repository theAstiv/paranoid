import './app.css'
import App from './App.svelte'

// After a deploy the content-hashed chunk filenames change. If a user has an
// old tab open, the browser may try to dynamically import a chunk that no longer
// exists and surface "Failed to fetch dynamically imported module". Reloading
// picks up the new index.html and new hashes — the user sees a brief flash
// instead of a hard error.
window.addEventListener('vite:preloadError', () => {
  window.location.reload()
})

const app = new App({
  target: document.getElementById('app'),
})

export default app
