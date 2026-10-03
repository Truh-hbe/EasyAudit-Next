import { DatePicker } from 'antd'
import dayjs from 'dayjs'
import type { Dayjs } from 'dayjs'
import advancedFormat from 'dayjs/plugin/advancedFormat'
import customParseFormat from 'dayjs/plugin/customParseFormat'
import localeData from 'dayjs/plugin/localeData'
import utc from 'dayjs/plugin/utc'
import weekOfYear from 'dayjs/plugin/weekOfYear'
import weekYear from 'dayjs/plugin/weekYear'
import weekday from 'dayjs/plugin/weekday'

import { displayZoneNowWallTime } from '../product/format'

dayjs.extend(customParseFormat)
dayjs.extend(advancedFormat)
dayjs.extend(weekday)
dayjs.extend(localeData)
dayjs.extend(weekOfYear)
dayjs.extend(weekYear)
dayjs.extend(utc)

type GenerateConfig = Parameters<typeof DatePicker.generatePicker<Dayjs>>[0]

// 面板里的日期是“墙上时间”：用 UTC 模式的 dayjs 承载，字段（年月日时分）就是上海墙上时间本身。
// UTC 没有夏令时空洞，面板的初始化、选择、加减和比较都不会被设备时区改动；
// 不涉及任何时区换算，真正的时区解释只发生在提交时（format.ts 按 Asia/Shanghai 转换和校验）。
function wall(value: Dayjs): Dayjs {
  return dayjs.utc(
    Date.UTC(value.year(), value.month(), value.date(), value.hour(), value.minute(), value.second(), value.millisecond()),
  )
}

export function wallTimeFromFields(year: number, month: number, day: number, hour = 0, minute = 0, second = 0): Dayjs {
  return dayjs.utc(Date.UTC(year, month - 1, day, hour, minute, second))
}

const LOCALES: Record<string, string> = { zh_CN: 'zh-cn', en_US: 'en' }
const localeName = (locale: string) => LOCALES[locale] ?? locale.split('_')[0] ?? 'en'

export const wallTimeGenerateConfig: GenerateConfig = {
  getNow: () => {
    const [year, month, day, hour, minute, second] = displayZoneNowWallTime()
    return wallTimeFromFields(year, month, day, hour, minute, second)
  },
  getFixedDate: (fixed) => {
    const [year = 1970, month = 1, day = 1] = fixed.split('-').map(Number)
    return wallTimeFromFields(year, month, day)
  },
  getEndDate: (date) => wall(date).endOf('month'),
  getWeekDay: (date) => {
    const clone = wall(date).locale('en')
    return clone.weekday() + clone.localeData().firstDayOfWeek()
  },
  getYear: (date) => wall(date).year(),
  getMonth: (date) => wall(date).month(),
  getDate: (date) => wall(date).date(),
  getHour: (date) => wall(date).hour(),
  getMinute: (date) => wall(date).minute(),
  getSecond: (date) => wall(date).second(),
  getMillisecond: (date) => wall(date).millisecond(),
  addYear: (date, diff) => wall(date).add(diff, 'year'),
  addMonth: (date, diff) => wall(date).add(diff, 'month'),
  addDate: (date, diff) => wall(date).add(diff, 'day'),
  setYear: (date, year) => wall(date).year(year),
  setMonth: (date, month) => wall(date).month(month),
  setDate: (date, num) => wall(date).date(num),
  setHour: (date, hour) => wall(date).hour(hour),
  setMinute: (date, minute) => wall(date).minute(minute),
  setSecond: (date, second) => wall(date).second(second),
  setMillisecond: (date, millisecond) => wall(date).millisecond(millisecond),
  isAfter: (date1, date2) => wall(date1).isAfter(wall(date2)),
  isValidate: (date) => date.isValid(),
  locale: {
    getWeekFirstDay: (locale) => dayjs.utc().locale(localeName(locale)).localeData().firstDayOfWeek(),
    getWeekFirstDate: (locale, date) => wall(date).locale(localeName(locale)).weekday(0),
    getWeek: (locale, date) => wall(date).locale(localeName(locale)).week(),
    getShortWeekDays: (locale) => dayjs.utc().locale(localeName(locale)).localeData().weekdaysMin(),
    getShortMonths: (locale) => dayjs.utc().locale(localeName(locale)).localeData().monthsShort(),
    format: (locale, date, format) => wall(date).locale(localeName(locale)).format(format),
    // 严格解析：任何字段越界（如 02/30、12:99）都返回 null，不会被归一化成另一个时刻。
    parse: (_locale, text, formats) => {
      for (const format of formats) {
        const parsed = dayjs.utc(text, format, true)
        if (parsed.isValid()) return parsed
      }
      return null
    },
  },
}

export const WallTimePicker = DatePicker.generatePicker<Dayjs>(wallTimeGenerateConfig)
