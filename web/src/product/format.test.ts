import { afterEach, describe, expect, it, vi } from 'vitest'

import { displayZoneInputToIso, formatDateTime } from './format'

// 设备时区 → 旧写法 new Date('2026-08-28T18:00') 得到的 ISO，用来证明设备时区确实已切换。
const deviceZones = {
  UTC: '2026-08-28T18:00:00.000Z',
  'America/New_York': '2026-08-28T22:00:00.000Z',
  'Asia/Shanghai': '2026-08-28T10:00:00.000Z',
  'Pacific/Auckland': '2026-08-28T06:00:00.000Z',
} as const

describe('display time zone is independent of the device time zone', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  for (const [zone, deviceLocalIso] of Object.entries(deviceZones)) {
    it(`device ${zone}: input 18:00 means 18:00 in Shanghai and displays back unchanged`, () => {
      vi.stubEnv('TZ', zone)
      expect(new Date('2026-08-28T18:00').toISOString()).toBe(deviceLocalIso)

      expect(displayZoneInputToIso('2026-08-28T18:00')).toBe('2026-08-28T10:00:00.000Z')
      expect(displayZoneInputToIso('2026-01-01T00:30')).toBe('2025-12-31T16:30:00.000Z')
      expect(displayZoneInputToIso('2026-08-28T18:00:30')).toBe('2026-08-28T10:00:30.000Z')
      expect(formatDateTime('2026-08-28T10:00:00Z')).toBe('2026/08/28 18:00')
      expect(formatDateTime(displayZoneInputToIso('2026-08-28T18:00'))).toBe('2026/08/28 18:00')
    })
  }

  it('rejects empty and malformed input', () => {
    for (const value of ['', '   ', 'not-a-date', '2026-02-30T10:00', '2026-08-28T24:00', '2026-08-28']) {
      expect(displayZoneInputToIso(value)).toBeNull()
    }
  })

  it('keeps null and unparseable display values', () => {
    expect(formatDateTime(null)).toBe('—')
    expect(formatDateTime('garbage')).toBe('garbage')
  })
})
