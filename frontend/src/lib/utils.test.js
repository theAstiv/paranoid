import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  dreadColor, dreadHex, dreadChip, dreadLabel, shortId, relativeTime, initials,
  dependencyCategorySet, dependencyFlags, dependencyDisplayName,
  cvssColor, cvssHex, cvssChip, cvssLabel, cvssScoreLabel,
  CVSS_METRICS, parseCvssVector, cvssVectorFromMetrics, normalizeCvssMetrics,
} from './utils.js'

describe('dreadColor', () => {
  it('returns critical color for score >= 8', () => {
    expect(dreadColor(8)).toBe('text-c-critical')
    expect(dreadColor(10)).toBe('text-c-critical')
  })
  it('returns high color for score >= 6 and < 8', () => {
    expect(dreadColor(6)).toBe('text-c-high')
    expect(dreadColor(7.9)).toBe('text-c-high')
  })
  it('returns medium color for score >= 4 and < 6', () => {
    expect(dreadColor(4)).toBe('text-c-medium')
    expect(dreadColor(5.9)).toBe('text-c-medium')
  })
  it('returns low color for score < 4', () => {
    expect(dreadColor(0)).toBe('text-c-low')
    expect(dreadColor(3.9)).toBe('text-c-low')
  })
})

describe('dreadHex', () => {
  it('maps score thresholds to hex colors', () => {
    expect(dreadHex(9)).toBe('#FB6F84')
    expect(dreadHex(6)).toBe('#FFA552')
    expect(dreadHex(4)).toBe('#F5D04E')
    expect(dreadHex(1)).toBe('#3FD0A8')
  })
})

describe('dreadChip', () => {
  it('maps score thresholds to chip classes', () => {
    expect(dreadChip(8)).toBe('chip-red')
    expect(dreadChip(6)).toBe('chip-orange')
    expect(dreadChip(4)).toBe('chip-amber')
    expect(dreadChip(0)).toBe('chip-green')
  })
})

describe('dreadLabel', () => {
  it('maps score thresholds to severity labels', () => {
    expect(dreadLabel(8)).toBe('Critical')
    expect(dreadLabel(6)).toBe('High')
    expect(dreadLabel(4)).toBe('Medium')
    expect(dreadLabel(0)).toBe('Low')
  })
})

describe('cvssColor', () => {
  it('returns critical color for score >= 9.0', () => {
    expect(cvssColor(9.0)).toBe('text-c-critical')
    expect(cvssColor(10)).toBe('text-c-critical')
  })
  it('returns high color for score >= 7.0 and < 9.0', () => {
    expect(cvssColor(7.0)).toBe('text-c-high')
    expect(cvssColor(8.9)).toBe('text-c-high')
  })
  it('returns medium color for score >= 4.0 and < 7.0', () => {
    expect(cvssColor(4.0)).toBe('text-c-medium')
    expect(cvssColor(6.9)).toBe('text-c-medium')
  })
  it('returns low color for score < 4.0', () => {
    expect(cvssColor(0)).toBe('text-c-low')
    expect(cvssColor(3.9)).toBe('text-c-low')
  })
})

describe('cvssHex', () => {
  it('maps score thresholds to hex colors', () => {
    expect(cvssHex(9.5)).toBe('#FB6F84')
    expect(cvssHex(7.5)).toBe('#FFA552')
    expect(cvssHex(5.0)).toBe('#F5D04E')
    expect(cvssHex(1.0)).toBe('#3FD0A8')
  })
})

describe('cvssChip', () => {
  it('maps score thresholds to chip classes', () => {
    expect(cvssChip(9.0)).toBe('chip-red')
    expect(cvssChip(7.0)).toBe('chip-orange')
    expect(cvssChip(4.0)).toBe('chip-amber')
    expect(cvssChip(0)).toBe('chip-green')
  })
})

describe('cvssLabel', () => {
  it('maps score thresholds to CVSS severity ratings', () => {
    expect(cvssLabel(9.5)).toBe('Critical')
    expect(cvssLabel(7.5)).toBe('High')
    expect(cvssLabel(5.0)).toBe('Medium')
    expect(cvssLabel(1.0)).toBe('Low')
    expect(cvssLabel(0)).toBe('None')
  })
})

describe('cvssScoreLabel', () => {
  it('formats a whole-number score with one decimal place', () => {
    expect(cvssScoreLabel(7)).toBe('7.0')
    expect(cvssScoreLabel(9)).toBe('9.0')
  })
  it('keeps an existing decimal score as-is', () => {
    expect(cvssScoreLabel(9.8)).toBe('9.8')
  })
})

describe('parseCvssVector', () => {
  it('parses all 8 metrics from a canonical vector string', () => {
    const metrics = parseCvssVector('AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H')
    expect(metrics).toEqual({
      attack_vector: 'N', attack_complexity: 'L', privileges_required: 'N',
      user_interaction: 'N', scope: 'U', confidentiality: 'H', integrity: 'H', availability: 'H',
    })
  })
  it('accepts the optional CVSS:3.1/ prefix', () => {
    const metrics = parseCvssVector('CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H')
    expect(metrics.attack_vector).toBe('N')
  })
  it('returns an empty object for a falsy vector', () => {
    expect(parseCvssVector(null)).toEqual({})
    expect(parseCvssVector('')).toEqual({})
  })
})

describe('cvssVectorFromMetrics', () => {
  it('renders metrics back to the canonical vector string, in fixed order', () => {
    const metrics = {
      availability: 'H', integrity: 'H', confidentiality: 'H', scope: 'U',
      user_interaction: 'N', privileges_required: 'N', attack_complexity: 'L', attack_vector: 'N',
    }
    expect(cvssVectorFromMetrics(metrics)).toBe('AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H')
  })
  it('round-trips with parseCvssVector', () => {
    const vector = 'AV:A/AC:H/PR:L/UI:R/S:C/C:L/I:N/A:H'
    expect(cvssVectorFromMetrics(parseCvssVector(vector))).toBe(vector)
  })
  it('covers every metric in CVSS_METRICS', () => {
    expect(CVSS_METRICS).toHaveLength(8)
  })
})

describe('normalizeCvssMetrics', () => {
  it('returns null for a null threat', () => {
    expect(normalizeCvssMetrics(null)).toBeNull()
  })
  it('returns null when neither shape is present', () => {
    expect(normalizeCvssMetrics({ name: 'x' })).toBeNull()
  })
  it('parses the flat cvss_vector shape', () => {
    const metrics = normalizeCvssMetrics({ cvss_vector: 'AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H' })
    expect(metrics.attack_vector).toBe('N')
  })
  it('falls back to the nested cvss object when cvss_vector is absent', () => {
    const metrics = normalizeCvssMetrics({ cvss: { attack_vector: 'L' } })
    expect(metrics.attack_vector).toBe('L')
  })
  it('prefers cvss_vector over a stale nested cvss object when both are present', () => {
    const metrics = normalizeCvssMetrics({
      cvss_vector: 'AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H',
      cvss: { attack_vector: 'P' }, // stale — would say "Physical" if it won
    })
    expect(metrics.attack_vector).toBe('N')
  })
})

describe('shortId', () => {
  it('truncates a UUID to its first 8 chars', () => {
    expect(shortId('12345678-abcd-ef00-0000-000000000000')).toBe('12345678')
  })
  it('returns full string if shorter than 8 chars', () => {
    expect(shortId('abc')).toBe('abc')
  })
  it('handles null/undefined/empty gracefully', () => {
    expect(shortId(null)).toBe('')
    expect(shortId(undefined)).toBe('')
    expect(shortId('')).toBe('')
  })
})

describe('relativeTime', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns em dash for falsy input', () => {
    expect(relativeTime(null)).toBe('—')
    expect(relativeTime(undefined)).toBe('—')
    expect(relativeTime('')).toBe('—')
  })

  it('returns "just now" for timestamps under 60s old', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-01-01T00:01:00.000Z'))
    expect(relativeTime('2026-01-01T00:00:30.000Z')).toBe('just now')
  })

  it('returns minutes ago for timestamps under an hour old', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-01-01T00:10:00.000Z'))
    expect(relativeTime('2026-01-01T00:00:00.000Z')).toBe('10m ago')
  })

  it('returns hours ago for timestamps under a day old', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-01-01T05:00:00.000Z'))
    expect(relativeTime('2026-01-01T00:00:00.000Z')).toBe('5h ago')
  })

  it('returns days ago for timestamps a day or older', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-01-04T00:00:00.000Z'))
    expect(relativeTime('2026-01-01T00:00:00.000Z')).toBe('3d ago')
  })
})

describe('initials', () => {
  it('returns "?" for falsy input', () => {
    expect(initials(null)).toBe('?')
    expect(initials(undefined)).toBe('?')
    expect(initials('')).toBe('?')
  })

  it('returns first 2 chars uppercased for a single-word name', () => {
    expect(initials('astitva')).toBe('AS')
  })

  it('returns first+last initials uppercased for multi-word names', () => {
    expect(initials('Astitva Verma')).toBe('AV')
  })

  it('collapses extra whitespace between name parts', () => {
    expect(initials('Astitva   Verma')).toBe('AV')
  })
})

describe('dependencyCategorySet', () => {
  it('returns an empty set for a missing profile', () => {
    expect(dependencyCategorySet(undefined).size).toBe(0)
  })

  it('includes categories only from shipped-path evidence', () => {
    const profile = {
      evidence: [
        { category: 'network', path_class: 'shipped' },
        { category: 'crypto', path_class: 'test' },
      ],
    }
    const set = dependencyCategorySet(profile)
    expect(set.has('network')).toBe(true)
    expect(set.has('crypto')).toBe(false)
  })

  it('adds build_install when install hooks are present, even without evidence', () => {
    const profile = { evidence: [], install_hooks: ['postinstall: node setup.js'] }
    expect(dependencyCategorySet(profile).has('build_install')).toBe(true)
  })
})

describe('dependencyFlags', () => {
  it('returns no flags for a clean analysis', () => {
    const analysis = { npm_profile: { status: 'ok' } }
    expect(dependencyFlags(analysis)).toEqual([])
  })

  it('returns an empty array for a missing analysis', () => {
    expect(dependencyFlags(undefined)).toEqual([])
  })

  it('flags a hard error', () => {
    expect(dependencyFlags({ error: 'resolution failed' })).toContain('error')
  })

  it('flags drift signal', () => {
    expect(dependencyFlags({ drift: { signal: true } })).toContain('drift')
  })

  it('flags install hooks on the npm profile', () => {
    const analysis = { npm_profile: { install_hooks: ['postinstall: node setup.js'] } }
    expect(dependencyFlags(analysis)).toContain('install-hook')
  })

  it('flags a non-ok scan status on either profile', () => {
    expect(dependencyFlags({ npm_profile: { status: 'semgrep_timeout' } })).toContain('semgrep_timeout')
    expect(dependencyFlags({ github_profile: { status: 'partial_fetch' } })).toContain('partial_fetch')
  })

  it('combines multiple flags', () => {
    const analysis = {
      drift: { signal: true },
      npm_profile: { status: 'partial_fetch', install_hooks: ['prepare: husky install'] },
    }
    expect(dependencyFlags(analysis)).toEqual(
      expect.arrayContaining(['drift', 'install-hook', 'partial_fetch'])
    )
  })

  it('flags a dependency dropped before analysis as "skipped", not "error"', () => {
    const flags = dependencyFlags({ skip_reason: 'exceeds_direct_dependency_cap' })
    expect(flags).toContain('skipped')
    expect(flags).not.toContain('error')
  })
})

describe('dependencyDisplayName', () => {
  it('joins package and version with @', () => {
    expect(dependencyDisplayName('lodash', '4.17.21')).toBe('lodash@4.17.21')
  })

  it('omits the dangling "@" when there is no version', () => {
    expect(dependencyDisplayName('left-pad', '')).toBe('left-pad')
  })

  it('collapses embedded whitespace/newlines in an unvalidated package name', () => {
    expect(dependencyDisplayName('evil\nname\n![x](http://a)', '')).toBe('evil name ![x](http://a)')
  })
})
