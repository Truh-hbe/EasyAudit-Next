import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { SessionProvider } from './app/auth/session'
import { App } from './App'
import './styles.css'

const root = document.getElementById('root')

if (root === null) {
  throw new Error('EasyAudit Product Surface root element is missing')
}

createRoot(root).render(
  <StrictMode>
    <SessionProvider>
      <App />
    </SessionProvider>
  </StrictMode>,
)
