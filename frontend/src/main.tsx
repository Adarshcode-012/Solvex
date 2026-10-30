import React from 'react'
import ReactDOM from 'react-dom/client'
import { Toaster } from 'react-hot-toast'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
    <Toaster
      position="bottom-right"
      toastOptions={{
        style: {
          background: '#161821',
          color: '#e2e4f0',
          border: '1px solid #252738',
          fontFamily: 'Inter, sans-serif',
          fontSize: '13px',
        },
        error: {
          iconTheme: { primary: '#f87171', secondary: '#161821' },
        },
        success: {
          iconTheme: { primary: '#34d399', secondary: '#161821' },
        },
      }}
    />
  </React.StrictMode>
)
