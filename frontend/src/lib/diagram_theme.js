// Mermaid theme variables mirroring the c-* palette in tailwind.config.js.
// tailwind.config.js defines c-* as hex literals, not CSS custom properties,
// so there is nothing to read from getComputedStyle() — these values are
// duplicated by hand. If tailwind.config.js's c-* block changes, update here.
export const diagramThemeVariables = {
  background: '#0A0E16',
  primaryColor: '#111722',
  primaryTextColor: '#E7EDF5',
  primaryBorderColor: '#2BD4C0',
  secondaryColor: '#0F1521',
  secondaryTextColor: '#C6D0DE',
  secondaryBorderColor: '#1E2738',
  tertiaryColor: '#0C1119',
  tertiaryTextColor: '#B8C2D0',
  tertiaryBorderColor: '#1A2333',
  lineColor: '#4D9CFF',
  textColor: '#E7EDF5',
  mainBkg: '#111722',
  nodeBorder: '#2BD4C0',
  clusterBkg: '#0F1521',
  clusterBorder: '#1A2333',
  edgeLabelBackground: '#0A0E16',
  fontFamily: 'IBM Plex Sans, system-ui, sans-serif',
}

export const diagramInitConfig = {
  startOnLoad: false,
  securityLevel: 'strict',
  theme: 'base',
  themeVariables: diagramThemeVariables,
  // @mermaid-js/layout-elk 0.2.3 is pinned to mermaid's ^11.x peer range
  // (the installed 11.17.2 satisfies it) — registered once in DiagramView
  // via mermaid.registerLayoutLoaders() before this config is used.
  layout: 'elk',
}
