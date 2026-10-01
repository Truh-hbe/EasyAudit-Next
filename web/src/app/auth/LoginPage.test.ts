import { describe, expect, it } from 'vitest'

import { ApiError } from '../../api/client'
import { loginErrorMessage } from './LoginPage'

describe('LoginPage loginErrorMessage', () => {
  it('formats 429 error with Retry-After: 900 into minutes', () => {
    const errorWithSeconds = new ApiError(429, 'Too many login attempts', 900)
    const message = loginErrorMessage(errorWithSeconds)
    expect(message).toContain('登录尝试过于频繁')
    expect(message).toContain('约 15 分钟')
    expect(message).toBe('登录尝试过于频繁，请约 15 分钟后再试。')

    const errorWithHeader = new ApiError(
      429,
      'Too many login attempts',
      new Headers({ 'Retry-After': '900' }),
    )
    expect(loginErrorMessage(errorWithHeader)).toBe('登录尝试过于频繁，请约 15 分钟后再试。')
  })

  it('formats 429 error without Retry-After without specific time', () => {
    const errorWithoutHeader = new ApiError(429, 'Too many login attempts')
    const message = loginErrorMessage(errorWithoutHeader)
    expect(message).toContain('登录尝试过于频繁')
    expect(message).not.toContain('分钟')
    expect(message).toBe('登录尝试过于频繁，请稍后再试。')
  })

  it('preserves 401 credential error message', () => {
    const error401 = new ApiError(401, 'Invalid login name or password')
    expect(loginErrorMessage(error401)).toBe('登录名或密码无效')
  })

  it('falls back to generic error message for other errors', () => {
    expect(loginErrorMessage(new ApiError(500, 'Server error'))).toBe('暂时无法完成登录，请重试')
    expect(loginErrorMessage(new Error('Network failure'))).toBe('暂时无法完成登录，请重试')
    expect(loginErrorMessage('unknown error')).toBe('暂时无法完成登录，请重试')
  })
})
