import React, { useState } from 'react'
import { useApi } from '../hooks/useApi'
import QueryBlock from './QueryBlock'

// Painel 03 — a prova do índice e a busca com geo, que viviam só na API.
// Nada aqui é texto livre: termo, raio e cliente são seleções que existem no
// dataset gerado por scripts/seed_geo.py, para nenhuma escolha devolver tela
// vazia por erro de digitação.
const TERMOS = ['', 'padaria', 'farmácia', 'posto', 'restaurante', 'barbearia']
const RAIOS_BUSCA_KM = [5, 25, 50]
const RAIOS_EXPLAIN_KM = [50, 500, 2000]

const fmt = (n) => (n == null ? '—' : Number(n).toLocaleString('pt-BR'))

export default function PainelIndiceBusca({ municipios, clientes }) {
  const { call } = useApi()
  const [centroIdx, setCentroIdx] = useState(0)
  const centro = municipios[centroIdx]?.centro || null

  // ── A · explain: mesmo filtro, dois índices ──
  const [cliente, setCliente] = useState('')
  const [raioExplain, setRaioExplain] = useState(2000)
  const [explain, setExplain] = useState(null)
  const [ocupadoExplain, setOcupadoExplain] = useState(false)
  const clienteAlvo = cliente || clientes[0] || ''

  const rodarExplain = async () => {
    if (!centro || !clienteAlvo) return
    setOcupadoExplain(true)
    try {
      const d = await call('/geo/explain-compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ clienteId: clienteAlvo, raioKm: raioExplain, centro }),
      })
      if (d) setExplain(d)
    } finally { setOcupadoExplain(false) }
  }

  // ── B · $search: texto + raio + facetas ──
  const [termo, setTermo] = useState('padaria')
  const [raioBusca, setRaioBusca] = useState(25)
  const [busca, setBusca] = useState(null)
  const [ocupadoBusca, setOcupadoBusca] = useState(false)

  const rodarBusca = async () => {
    if (!centro) return
    setOcupadoBusca(true)
    try {
      const d = await call('/geo/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ termo, centro, raioKm: raioBusca, limite: 10 }),
      })
      if (d) setBusca(d)
    } finally { setOcupadoBusca(false) }
  }

  const [composto, puro] = explain?.planos || []
  const razao = composto?.totalKeysExamined && puro?.totalKeysExamined
    ? Math.round(puro.totalKeysExamined / Math.max(composto.totalKeysExamined, 1))
    : null
  const facetas = busca?.meta?.facet || {}

  return (
    <section className="card">
      <div className="kicker" style={{ marginBottom: 8, color: '#b45af2' }}>03 · Índice certo e busca com geo</div>
      <h2 style={{ fontSize: 18, marginBottom: 6 }}>
        O plano medido no cluster, e texto + raio + facetas numa consulta só
      </h2>
      <p style={{ color: 'var(--text-secondary)', fontSize: 13, marginBottom: 14 }}>
        Os números abaixo vêm do <code>explain("executionStats")</code> e do <code>$search</code> executados agora,
        não de um texto escrito antes da demo.
      </p>

      <div className="geo-controles">
        <label>centro
          <select value={centroIdx} onChange={e => setCentroIdx(Number(e.target.value))}>
            {municipios.map((m, i) => <option key={i} value={i}>{m.municipio}/{m.uf}</option>)}
          </select>
        </label>
      </div>

      <div className="row" style={{ marginTop: 12, alignItems: 'stretch', flexWrap: 'wrap' }}>
        <div className="col card" style={{ minWidth: 'min(300px, 100%)', flex: '1 1 340px' }}>
          <strong style={{ fontSize: 14 }}>A · Mesmo <code>$geoWithin</code>, dois índices</strong>
          <p style={{ color: 'var(--text-secondary)', fontSize: 12.5, margin: '6px 0 10px' }}>
            Filtro de cliente + status + raio. O índice composto põe a igualdade antes do geo; o 2dsphere puro só
            conhece a geometria.
          </p>
          <div className="geo-controles">
            <label>cliente
              <select value={clienteAlvo} onChange={e => setCliente(e.target.value)}>
                {clientes.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
            <label>raio
              <select value={raioExplain} onChange={e => setRaioExplain(Number(e.target.value))}>
                {RAIOS_EXPLAIN_KM.map(v => <option key={v} value={v}>{v} km</option>)}
              </select>
            </label>
            <button className="btn btn-sm btn-primary" onClick={rodarExplain}
              disabled={ocupadoExplain || !centro || !clienteAlvo}>
              {ocupadoExplain ? <><span className="spinner" /> Medindo…</> : 'Comparar planos'}
            </button>
          </div>
          {explain && (
            <>
              <div className="geo-tabela-wrap" tabIndex={0} role="region" aria-label="Planos de execução medidos">
                <table className="geo-tabela">
                  <thead>
                    <tr><th>índice · estágios</th><th>chaves examinadas</th><th>devolvidos</th><th>ms</th></tr>
                  </thead>
                  <tbody>
                    {explain.planos.map(p => (
                      <tr key={p.hint}>
                        <td>
                          <code>{p.indice_usado || p.hint}</code>
                          <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{(p.estagios || []).join(' → ')}</div>
                        </td>
                        <td style={{ fontWeight: 700 }}>{fmt(p.totalKeysExamined)}</td>
                        <td>{fmt(p.nReturned)}</td>
                        <td>{fmt(p.executionTimeMillis)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {razao != null && razao > 1 && (
                <p className="geo-nota-seletividade">
                  Mesmo resultado ({fmt(composto.nReturned)} documentos): o 2dsphere puro examinou {fmt(razao)}× mais
                  chaves. Medido agora, sujeito a cache; o que se transfere é a regra (igualdade antes do geo), não o
                  número.
                </p>
              )}
              <QueryBlock label="Comandos executados (um explain por índice)" query={explain.query} />
            </>
          )}
        </div>

        <div className="col card" style={{ minWidth: 'min(300px, 100%)', flex: '1 1 340px' }}>
          <strong style={{ fontSize: 14 }}>B · Atlas Search: texto + raio + facetas</strong>
          <p style={{ color: 'var(--text-secondary)', fontSize: 12.5, margin: '6px 0 10px' }}>
            Um <code>compound</code> com texto fuzzy (analisador português), <code>near</code> somando score por
            proximidade e <code>geoWithin</code> em círculo;
            as facetas saem do <code>$searchMeta</code> com o mesmo operador. O <code>filter</code> do
            <code> $vectorSearch</code> não aceita predicado geo; aqui ele é de primeira classe.
          </p>
          <div className="geo-controles">
            <label>termo
              <select value={termo} onChange={e => setTermo(e.target.value)}>
                {TERMOS.map(t => <option key={t} value={t}>{t || '— só o raio —'}</option>)}
              </select>
            </label>
            <label>raio
              <select value={raioBusca} onChange={e => setRaioBusca(Number(e.target.value))}>
                {RAIOS_BUSCA_KM.map(v => <option key={v} value={v}>{v} km</option>)}
              </select>
            </label>
            <button className="btn btn-sm btn-primary" onClick={rodarBusca} disabled={ocupadoBusca || !centro}>
              {ocupadoBusca ? <><span className="spinner" /> Buscando…</> : 'Buscar'}
            </button>
          </div>
          {busca?.estado === 'nao_configurado' && (
            <div className="banner banner-warning">
              <span>⚠️</span><div>Índice de busca ausente: {busca.mensagem}</div>
            </div>
          )}
          {busca?.estado === 'ok' && (
            <>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', margin: '4px 0 8px' }}>
                <span className="badge badge-gray">ordem: {busca.ordenacao}</span>
                {busca.meta?.count?.lowerBound != null && (
                  <span className="badge badge-gray">{fmt(busca.meta.count.lowerBound)} compras no filtro</span>
                )}
                {['categoria', 'uf'].flatMap(f => (facetas[f]?.buckets || []).slice(0, 4).map(b => (
                  <span key={`${f}-${b._id}`} className="badge badge-purple">{f}: {b._id} · {fmt(b.count)}</span>
                )))}
              </div>
              {busca.resultados.length === 0 ? (
                <p style={{ color: 'var(--text-secondary)', fontSize: 12 }}>Nenhum estabelecimento neste raio.</p>
              ) : (
                <ul style={{ fontSize: 12.5, paddingLeft: 16, margin: 0, lineHeight: 1.7 }}>
                  {busca.resultados.map(r => (
                    <li key={r.endToEndId}>
                      <strong>{r.estabelecimento?.nome}</strong> · {r.municipio}/{r.uf} · {fmt(r.km_do_centro)} km
                      {termo && <> · score {r.score}</>}
                    </li>
                  ))}
                </ul>
              )}
              <p className="geo-nota-seletividade">
                Um resultado por terminal; a distância vem de haversine em MQL, para conferir o raio sem confiar no
                operador. Em polígonos, o Search usa borda cartesiana e o <code>$geoWithin</code> nativo, geodésica: perto
                da borda os dois podem divergir.
              </p>
              <QueryBlock label="Pipeline $search executado" query={JSON.stringify(busca.pipeline, null, 2)} />
              <QueryBlock label="Facetas ($searchMeta)" query={JSON.stringify(busca.pipeline_meta, null, 2)} />
            </>
          )}
        </div>
      </div>
    </section>
  )
}
