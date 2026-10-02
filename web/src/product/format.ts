// 界面展示与输入统一按此时区解释，与导出和每日提醒一致；不随设备时区变化。
export const DISPLAY_TIME_ZONE = 'Asia/Shanghai'

const dateTimeFormat = new Intl.DateTimeFormat('zh-CN', {
  timeZone: DISPLAY_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

const zonePartsFormat = new Intl.DateTimeFormat('en-US', {
  timeZone: DISPLAY_TIME_ZONE,
  hourCycle: 'h23',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})

export function formatDateTime(value: string | null): string {
  if (value === null) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return dateTimeFormat.format(date)
}

// 某一 UTC 时刻在展示时区的偏移（毫秒），由 Intl 计算，不写死 +08:00。
function displayZoneOffset(utcMs: number): number {
  const parts = zonePartsFormat.formatToParts(new Date(utcMs))
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((item) => item.type === type)?.value)
  const wallAsUtc = Date.UTC(
    part('year'),
    part('month') - 1,
    part('day'),
    part('hour'),
    part('minute'),
    part('second'),
  )
  return wallAsUtc - (utcMs - (utcMs % 1000))
}

const LOCAL_DATE_TIME = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/

// 把 `datetime-local` 的值（展示时区的墙上时间）转为 ISO 时间；空值或无效值返回 null。
export function displayZoneInputToIso(value: string): string | null {
  const match = LOCAL_DATE_TIME.exec(value.trim())
  if (match === null) return null
  const [year, month, day, hour, minute, second] = match.slice(1).map((item) => Number(item ?? 0))
  const wall = Date.UTC(year, month - 1, day, hour, minute, second)
  const check = new Date(wall)
  if (check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day || hour > 23 || minute > 59) {
    return null
  }
  const firstGuess = wall - displayZoneOffset(wall)
  return new Date(wall - displayZoneOffset(firstGuess)).toISOString()
}

export function lifecycleText(value: string): string {
  return value.replaceAll('_', ' ')
}
