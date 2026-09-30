import React, { Suspense, useEffect, useState } from 'react'
import QueryBlock from './components/QueryBlock'
import Geo from './pages/Geo'

// MongoDB leaf logo SVG (official mark)
function MongoDBLogo({ size = 32 }) {
  return (
    <svg aria-hidden="true" width={size} height={size} viewBox="0 0 256 549" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M175.622 61.108C152.612 33.807 132.797 5.315 128.69.239c-.5-.32-1.0-.239-1.0-.239s-.5-.081-1.0.239C122.583 5.315 102.768 33.807 79.758 61.108 24.914 128.23 0 188.949 0 245.85c0 68.687 31.064 130.1 79.875 171.037l1.872 1.253c1.522 16.09 4.254 51.884 3.551 75.43 0 0 4.596 3.112 9.94 3.928 5.343.816 11.435.816 11.435.816l-1.114-15.274c8.828 1.952 17.9 3.025 27.22 3.025 9.323 0 18.393-1.073 27.22-3.025l-1.114 15.274s6.093 0 11.435-.816c5.343-.816 9.94-3.928 9.94-3.928-.703-23.546 2.029-59.34 3.55-75.43l1.873-1.253C233.936 375.95 265 314.537 265 245.85c0-56.901-24.914-117.62-89.378-184.742z" fill="#00ED64"/>
      <path d="M134.03 468.678s0-175.178.816-175.255c4.474-.504 8.947-1.253 13.338-2.248-.041 0-14.154 177.503-14.154 177.503z" fill="#00684A"/>
      <path d="M128.69 493.092c-4.596-17.18-5.734-34.441-5.734-34.441s-4.148 2.818-4.148 6.745c0 3.928.816 27.696.816 27.696h9.066z" fill="#00684A"/>
    </svg>
  )
}

function ApiErrorToast() {
  const [toast, setToast] = useState(null)

  useEffect(() => {
    let timer
    let lastKey = ''
    let lastAt = 0
    const onError = (e) => {
      const key = `${e.detail?.path || ''}:${e.detail?.message || ''}`
      const now = Date.now()
      if (key === lastKey && now - lastAt < 8000) return
      lastKey = key
      lastAt = now
      setToast(e.detail)
      clearTimeout(timer)
      timer = setTimeout(() => setToast(null), 6000)
    }
    window.addEventListener('api-error', onError)
    return () => { window.removeEventListener('api-error', onError); clearTimeout(timer) }
  }, [])

  if (!toast) return null
  return (
    <div style={{
      position: 'fixed', bottom: 24, right: 24, zIndex: 1000, maxWidth: 420,
      display: 'flex', alignItems: 'flex-start', gap: 10, padding: '13px 16px',
      background: 'rgba(255,105,96,.12)', border: '1px solid rgba(255,105,96,.4)', borderRadius: 12,
      backdropFilter: 'blur(12px)',
      boxShadow: '0 8px 32px rgba(0,0,0,.45)', fontSize: 13, color: '#ff9b94',
    }}>
      <span style={{ flexShrink: 0 }}>⚠️</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 700, marginBottom: 2, color: '#ffb3ae' }}>Erro na chamada à API</div>
        <div style={{ wordBreak: 'break-word' }}>
          <code style={{ background: 'transparent', border: 'none', padding: 0, fontSize: 12 }}>{toast.path}</code>
          {' — '}{toast.message}
        </div>
      </div>
      <button aria-label="Fechar aviso" onClick={() => setToast(null)} style={{
        background: 'none', border: 'none', cursor: 'pointer', color: '#ff9b94',
        fontSize: 16, lineHeight: 1, padding: 0, flexShrink: 0,
      }}>×</button>
    </div>
  )
}

export default function App() {
  const [preflight, setPreflight] = useState(null)
  const [lastQuery, setLastQuery] = useState(null)

  useEffect(() => {
    fetch('/api/preflight').then(r => r.json()).then(setPreflight).catch(() => setPreflight({ ready: false }))
  }, [])

  useEffect(() => {
    const remember = (event) => setLastQuery(event.detail)
    window.addEventListener('api-query-executed', remember)
    return () => window.removeEventListener('api-query-executed', remember)
  }, [])

  return (
    <div data-pov-shell style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <a className="pov-skip-link" href="#conteudo-principal">Pular para o conteúdo</a>
      <header className="app-header" style={{
        position: 'sticky', top: 0, zIndex: 50,
        background: 'rgba(0,30,43,.92)', backdropFilter: 'blur(16px)',
        padding: '0 28px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        height: 58, flexShrink: 0,
        borderBottom: '1px solid var(--border-subtle)',
      }}>
        <div className="app-header-brand" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <MongoDBLogo size={26} />
          <div style={{ borderLeft: '1px solid rgba(255,255,255,.12)', paddingLeft: 12 }}>
            <div style={{ color: '#fafafa', fontWeight: 700, fontSize: 14.5, lineHeight: 1.15, letterSpacing: '-.01em' }}>MongoDB Atlas</div>
            <div style={{
              color: 'var(--accent)', fontSize: 10, marginTop: 1,
              fontFamily: 'var(--font-mono)', fontWeight: 600,
              textTransform: 'uppercase', letterSpacing: '.12em',
            }}>Geo Showcase</div>
          </div>
        </div>

        <div className="app-header-status" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className={`badge ${preflight?.ready ? 'badge-green' : 'badge-yellow'}`}
            title={preflight?.ready ? 'Pré-voo concluído' : 'Preparação incompleta — veja /preflight'}>
            {preflight?.ready ? '● Pronto' : '● Pré-voo pendente'}
          </span>
          <span className="badge badge-gray">Risco geográfico</span>
        </div>
      </header>

      <div className="app-shell-body" style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <main id="conteudo-principal" tabIndex={-1} className="app-main" style={{ flex: 1, overflowY: 'auto', padding: '32px 36px', background: 'var(--bg-primary)' }}>
          <div style={{ maxWidth: 980, margin: '0 auto' }} className="fade-in">
            <div style={{ marginBottom: 20 }}>
              <h1 style={{
                fontSize: 30, fontWeight: 800, color: 'var(--text-primary)',
                letterSpacing: '-.03em', lineHeight: 1.1,
              }}>Risco geográfico</h1>
              <p style={{ color: 'var(--text-secondary)', fontSize: 13.5, marginTop: 6 }}>
                Investigação retrospectiva (impossible travel) e os cinco operadores/estágios de
                consulta geoespacial do MongoDB, lado a lado, sobre o mesmo dataset.
              </p>
            </div>
            <Suspense fallback={<div className="card">Carregando módulo…</div>}>
              <Geo />
            </Suspense>
            {lastQuery && (
              <div style={{ marginTop: 12 }}>
                <QueryBlock
                  label={`Ver query / chamada executada · ${lastQuery.path}`}
                  query={typeof lastQuery.technical === 'string'
                    ? lastQuery.technical
                    : JSON.stringify(lastQuery.technical, null, 2)}
                />
              </div>
            )}
          </div>
        </main>
      </div>
      <ApiErrorToast />
    </div>
  )
}
