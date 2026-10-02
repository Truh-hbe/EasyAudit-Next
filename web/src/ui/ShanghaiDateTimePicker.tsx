import { DatePicker } from 'antd'
import dayjs from 'dayjs'
import type { Dayjs } from 'dayjs'
import utc from 'dayjs/plugin/utc'
import type { FocusEvent, KeyboardEvent } from 'react'
import { useRef } from 'react'

import { DISPLAY_DATE_TIME_TEXT_FORMAT as FORMAT } from '../product/format'

dayjs.extend(utc)

const WALL_TEXT = /^(\d{4})\/(\d{2})\/(\d{2}) (\d{2}):(\d{2})$/

// 文本 → 选择器的值。用 UTC 模式的 dayjs 承载墙上时间：UTC 没有夏令时空洞，设备时区不会改动它。
// 不是真实存在的日期（如 02/30）返回 undefined，由表单校验报错。
function toPickerValue(text: string | undefined): Dayjs | undefined {
  const match = WALL_TEXT.exec(text ?? '')
  if (match === null) return undefined
  const [year, month, day, hour, minute] = match.slice(1).map(Number) as [number, number, number, number, number]
  const value = dayjs.utc(Date.UTC(year, month - 1, day, hour, minute))
  return value.year() === year && value.month() === month - 1 && value.date() === day ? value : undefined
}

export interface ShanghaiDateTimePickerProps {
  // 表单值是 `YYYY/MM/DD HH:mm` 文本（上海墙上时间）；空串表示未填写。无法解析的输入也原样保存，交给校验报错。
  value?: string
  onChange?: (text: string) => void
  id?: string
  'aria-describedby'?: string
}

// 按上海时间输入的日期时间选择器。
// 直接使用 DatePicker 有两个问题：键入的文本由设备时区的 dayjs 解析——无效日期，以及设备夏令时空洞里的时刻，
// 会被静默丢弃并回退为旧值；日期框里按 Enter 还会提交整个表单。所以把键入的原始文本作为事实来源：
// 提交（Enter、失焦）时把文本原样交给表单校验，选择器只负责展示和面板选择。
export function ShanghaiDateTimePicker({ value, onChange, id, 'aria-describedby': describedBy }: ShanghaiDateTimePickerProps) {
  // 自上次同步以来键入的原始文本；null 表示没有待提交的键入。
  const typed = useRef<string | null>(null)

  function commitTyped() {
    if (typed.current === null) return
    onChange?.(typed.current)
    typed.current = null
  }

  return (
    <div
      onInput={(event) => {
        if (event.target instanceof HTMLInputElement) typed.current = event.target.value
      }}
      onKeyDown={(event: KeyboardEvent<HTMLDivElement>) => {
        if (event.key !== 'Enter' || !(event.target instanceof HTMLInputElement)) return
        // 日期框里的 Enter 只确认日期，不提交表单。
        event.preventDefault()
        commitTyped()
      }}
      onBlur={(event: FocusEvent<HTMLDivElement>) => {
        if (event.target instanceof HTMLInputElement) commitTyped()
      }}
    >
      <DatePicker
        id={id}
        aria-describedby={describedBy}
        value={toPickerValue(value)}
        showTime={{ format: 'HH:mm' }}
        format={FORMAT}
        onChange={(picked: Dayjs | null) => {
          // 面板选择或清除：以选中的墙上时间为准，丢弃待提交的键入。
          typed.current = null
          onChange?.(picked === null ? '' : picked.format(FORMAT))
        }}
      />
    </div>
  )
}
