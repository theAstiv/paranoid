import { describe, it, expect } from 'vitest'
import { diagramThemeVariables, diagramInitConfig } from './diagram_theme.js'
import tailwindConfig from '../../tailwind.config.js'

// diagramThemeVariables duplicates hex values from tailwind.config.js's c-*
// palette by hand (no CSS custom properties exist to read them from at
// runtime — see the comment in both files). This test reads the actual
// palette, not a second hardcoded copy, so a value drifting out of sync is
// caught here instead of silently rendering diagrams in the wrong colors.
const cPalette = tailwindConfig.theme.extend.colors.c

// Maps each mermaid themeVariables key to the c-* token it must mirror.
const EXPECTED_SOURCE = {
  background: 'bg',
  primaryColor: 'panel',
  primaryTextColor: 'text',
  primaryBorderColor: 'accent',
  secondaryColor: 'panel2',
  secondaryTextColor: 'text2',
  secondaryBorderColor: 'border',
  tertiaryColor: 'well',
  tertiaryTextColor: 'text3',
  tertiaryBorderColor: 'border-soft',
  lineColor: 'blue',
  textColor: 'text',
  mainBkg: 'panel',
  nodeBorder: 'accent',
  clusterBkg: 'panel2',
  clusterBorder: 'border-soft',
  edgeLabelBackground: 'bg',
}

describe('diagram_theme', () => {
  it('defines every themeVariables key mermaid.initialize expects for theme: base', () => {
    for (const key of Object.keys(EXPECTED_SOURCE)) {
      expect(diagramThemeVariables).toHaveProperty(key)
    }
  })

  it('every color mirrors its mapped c-* token in tailwind.config.js', () => {
    for (const [themeKey, cToken] of Object.entries(EXPECTED_SOURCE)) {
      expect(cPalette).toHaveProperty(cToken) // the mapping itself stays valid if a token is renamed
      expect(diagramThemeVariables[themeKey]).toBe(cPalette[cToken])
    }
  })

  it('builds a mermaid.initialize config with strict security and no auto-start', () => {
    expect(diagramInitConfig).toMatchObject({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: 'base',
      themeVariables: diagramThemeVariables,
    })
  })
})
