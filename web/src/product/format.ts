// 界面展示与输入统一按此时区解释，与导出和每日提醒一致；不随设备时区变化。
export const DISPLAY_TIME_ZONE = 'Asia/Shanghai'
export const DISPLAY_TIME_ZONE_HINT = '以下时间均按上海时间（Asia/Shanghai）填写和显示。'

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

type WallTime = [year: number, month: number, day: number, hour: number, minute: number, second: number]

// 某一 UTC 时刻在展示时区的墙上时间。
function displayZoneWallTime(utcMs: number): WallTime {
  const parts = zonePartsFormat.formatToParts(new Date(utcMs))
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((item) => item.type === type)?.value)
  return [part('year'), part('month'), part('day'), part('hour'), part('minute'), part('second')]
}

function wallTimeAsUtc([year, month, day, hour, minute, second]: WallTime): number {
  return Date.UTC(year, month - 1, day, hour, minute, second)
}

// 某一 UTC 时刻在展示时区的偏移（毫秒），由 Intl 计算，不写死 +08:00。
function displayZoneOffset(utcMs: number): number {
  return wallTimeAsUtc(displayZoneWallTime(utcMs)) - (utcMs - (utcMs % 1000))
}

const LOCAL_DATE_TIME = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/
// 下限避开 Date.UTC 对 0–99 年的特殊处理；上限是 datetime-local 的四位年份。
const MIN_INPUT_YEAR = 1970
const MAX_INPUT_YEAR = 9999

// 把 `datetime-local` 的值（展示时区的墙上时间）转为 ISO 时间。
// 空值、字段越界、不存在的日期、展示时区里不存在的时刻（夏令时跳过的时段）都返回 null，不做静默修正。
export function displayZoneInputToIso(value: string): string | null {
  const match = LOCAL_DATE_TIME.exec(value.trim())
  if (match === null) return null
  const wall = match.slice(1).map((item) => Number(item ?? 0)) as WallTime
  const [year, month, day, hour, minute, second] = wall
  if (
    year < MIN_INPUT_YEAR ||
    year > MAX_INPUT_YEAR ||
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > 31 ||
    hour > 23 ||
    minute > 59 ||
    second > 59
  ) {
    return null
  }
  const wallMs = wallTimeAsUtc(wall)
  const utcMs = wallMs - displayZoneOffset(wallMs - displayZoneOffset(wallMs))
  // 回转核对：换算出的时刻必须原样读回输入的墙上时间。
  const roundTrip = displayZoneWallTime(utcMs)
  if (roundTrip.some((item, index) => item !== wall[index])) return null
  return new Date(utcMs).toISOString()
}

export function lifecycleText(value: string): string {
  return value.replaceAll('_', ' ')
}
