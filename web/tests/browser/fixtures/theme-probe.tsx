import { App as AntApp, ConfigProvider, Descriptions, Form, Typography } from 'antd'
import { createRoot } from 'react-dom/client'

import { appTheme } from '../../../src/app/theme'

// 浏览器测试专用：在真实页面里按 appTheme 渲染说明类文字，供对比度断言使用。
function Sample({ prefix }: { prefix: 'white' | 'layout' }) {
  return (
    <div
      data-contrast-probe
      style={{ background: prefix === 'white' ? '#ffffff' : '#f5f7fb', padding: 16 }}
    >
      <Typography.Text type="secondary">{`${prefix}-secondary`}</Typography.Text>
      <Form layout="vertical">
        <Form.Item label="字段" extra={`${prefix}-extra`}>
          <input />
        </Form.Item>
      </Form>
      <Descriptions items={[{ key: 'k', label: `${prefix}-label`, children: '值' }]} bordered />
    </div>
  )
}

export function mountThemeProbe() {
  const container = document.createElement('div')
  document.body.appendChild(container)
  createRoot(container).render(
    <ConfigProvider theme={appTheme}>
      <AntApp className="app-root">
        <Sample prefix="white" />
        <Sample prefix="layout" />
      </AntApp>
    </ConfigProvider>,
  )
}
