import { App as AntApp, ConfigProvider, DatePicker, Descriptions, Form, Input, Select, Table, Typography } from 'antd'
import dayjs from 'dayjs'
import { createRoot } from 'react-dom/client'

import { appTheme } from '../../../src/app/theme'

// 浏览器测试专用：在真实页面里按 appTheme 渲染说明类文字，供对比度断言使用。
function Sample({ prefix }: { prefix: 'white' | 'layout' }) {
  return (
    <div
      data-contrast-probe={prefix}
      style={{ background: prefix === 'white' ? '#ffffff' : '#f5f7fb', padding: 16 }}
    >
      <Typography.Text type="secondary">{`${prefix}-secondary`}</Typography.Text>
      <Form layout="vertical">
        <Form.Item label="字段" extra={`${prefix}-extra`}>
          <Input.Password />
        </Form.Item>
      </Form>
      <Descriptions items={[{ key: 'k', label: `${prefix}-label`, children: '值' }]} bordered />
    </div>
  )
}

// 内置交互图标：清除按钮、Select/DatePicker 后缀、Table 排序/筛选图标。
function IconSample() {
  return (
    <div data-contrast-probe="icons" style={{ background: '#ffffff', padding: 16, width: 480 }}>
      <Input allowClear defaultValue="x" />
      <Input disabled defaultValue="disabled-input" />
      <Select
        allowClear
        defaultValue="a"
        options={[{ value: 'a', label: 'a' }]}
        style={{ width: 160 }}
      />
      <DatePicker allowClear defaultValue={dayjs('2026-01-01')} />
      <Table
        size="small"
        pagination={false}
        rowKey="id"
        dataSource={[]}
        columns={[
          { title: '排序', dataIndex: 'a', sorter: true },
          { title: '筛选', dataIndex: 'b', filters: [{ text: 'a', value: 'a' }] },
        ]}
      />
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
        <IconSample />
      </AntApp>
    </ConfigProvider>,
  )
}
