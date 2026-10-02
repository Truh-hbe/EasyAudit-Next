import { afterEach, describe, expect, it, vi } from 'vitest'

import { wallTimeFromFields, wallTimeGenerateConfig as config } from './wallTimeGenerateConfig'

describe('wall time generateConfig is independent of the device time zone', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllEnvs()
  })

  for (const zone of ['UTC', 'America/New_York', 'Asia/Shanghai', 'Pacific/Auckland']) {
    it(`device ${zone}: DST gap times survive field operations and "now" is Shanghai wall time`, () => {
      vi.stubEnv('TZ', zone)
      const gap = wallTimeFromFields(2026, 3, 8, 2, 30)
      expect(config.getHour(gap)).toBe(2)
      expect(config.getHour(config.setHour(config.setDate(gap, 8), 2))).toBe(2)
      expect(config.getDate(config.addDate(gap, 1))).toBe(9)

      vi.useFakeTimers()
      vi.setSystemTime(new Date('2026-08-28T02:30:00Z'))
      const now = config.getNow()
      expect([config.getYear(now), config.getMonth(now), config.getDate(now), config.getHour(now), config.getMinute(now)]).toEqual([2026, 7, 28, 10, 30])
    })
  }

  it('parses strictly: out-of-range fields are rejected, never normalised', () => {
    const parse = (text: string) => config.locale.parse('zh_CN', text, ['YYYY/MM/DD HH:mm'])
    expect(parse('2026/08/28 18:00')?.format('YYYY/MM/DD HH:mm')).toBe('2026/08/28 18:00')
    for (const text of ['2026/02/30 10:00', '2026/08/28 12:99', '2026/13/01 10:00', '2026/08/28 24:00', '']) {
      expect(parse(text)).toBeNull()
    }
  })
})
