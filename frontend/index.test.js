import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

// Resolved from this file's own location (not process.cwd()) so the test
// doesn't depend on vitest being invoked from the frontend/ directory.
const here = dirname(fileURLToPath(import.meta.url))

// U2 (week4-plan.md): fonts must be self-hosted so the UI works under a CSP
// without font-src pointing at fonts.gstatic.com, and fully offline.
describe('font loading', () => {
  it('index.html has no external font URL', () => {
    const html = readFileSync(resolve(here, 'index.html'), 'utf-8')
    expect(html).not.toMatch(/fonts\.googleapis\.com/)
    expect(html).not.toMatch(/fonts\.gstatic\.com/)
  })

  it('main.js imports all self-hosted IBM Plex weights the UI uses', () => {
    const main = readFileSync(resolve(here, 'src/main.js'), 'utf-8')
    for (const weight of ['400', '500', '600', '700']) {
      expect(main).toMatch(new RegExp(`@fontsource/ibm-plex-sans/latin-${weight}\\.css`))
    }
    for (const weight of ['400', '500', '600']) {
      expect(main).toMatch(new RegExp(`@fontsource/ibm-plex-mono/latin-${weight}\\.css`))
    }
  })
})
