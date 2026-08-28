import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'

import { SessionProvider } from './app/auth/session'
import { App } from './App'
import './styles.css'
import './final-polish.css'

const root = document.getElementById('root')

if (root === null) {
  throw new Error('EasyAudit Product Surface root element is missing')
}

createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <SessionProvider>
        <App />
      </SessionProvider>
    </BrowserRouter>
  </StrictMode>,
)
