import { App as AntApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'

import { SessionProvider } from './app/auth/session'
import { appTheme } from './app/theme'
import { App } from './App'
import './styles.css'
import './final-polish.css'

dayjs.locale('zh-cn')

const root = document.getElementById('root')

if (root === null) {
  throw new Error('EasyAudit Product Surface root element is missing')
}

createRoot(root).render(
  <StrictMode>
    <ConfigProvider locale={zhCN} theme={appTheme}>
      <AntApp className="app-root">
        <BrowserRouter>
          <SessionProvider>
            <App />
          </SessionProvider>
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  </StrictMode>,
)
