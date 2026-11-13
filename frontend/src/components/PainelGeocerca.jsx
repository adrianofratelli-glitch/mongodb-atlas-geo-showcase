import React, { useState } from 'react'
import { useApi } from '../hooks/useApi'
import QueryBlock from './QueryBlock'
import MapaConsulta from './MapaConsulta'
import CasoNegocio from './CasoNegocio'

// Painel 04 — a mesma geocerca respondida pelo 2dsphere nativo e pelo Atlas
// Search (ADR 0003). Tudo é seleção: categoria e termo existem no dataset de
// scripts/seed_geo.py, e o termo de cada categoria casa com nomes reais dele.
const CATEGORIAS = [
  { categoria: 'farmácia', termos: ['drogaria', 'farmácia', ''] },
  { categoria: 'alimentação', termos: ['padaria', 'pizzaria', ''] },
  { categoria: 'combustível', termos: ['posto', ''] },
  { categoria: 'vestuário', termos: ['boutique', 'magazine', ''] },
  { categoria: 'serviços', termos: ['barbearia', 'oficina', ''] },
]
const RAIOS_GEOCERCA_KM = [8, 15, 60, 600]
const MAX_NO_MAPA = 24

const fmt = (n) => (n == null ? '—' : Number(n).toLocaleString('pt-BR'))
// A conclusão sai da razão medida neste clique, nunca de uma frase fixa.
const conclusao = (razao) => {
  const x = (v) => `${v.toFixed(1).replace('.', ',')}×`
  if (razao >= 1.2) return `o nativo foi ${x(razao)} mais barato no servidor.`
  if (razao <= 1 / 1.2) return `o Search foi ${x(1 / razao)} mais barato no servidor.`
  return 'empate técnico no servidor (diferença abaixo de 20%).'
}
const fmtMs = (n) => (n == null ? '—' : `${Math.round(n).toLocaleString('pt-BR')} ms`)

function CartaoMotor({ titulo, bloco, extra }) {
  const plano = bloco?.plano || {}
  return (
    <div className="card">
      <strong style={{ fontSize: 14 }}>{titulo}</strong>
      <div className="geo-tabela-wrap" tabIndex={0} role="region" aria-label={`Medição: ${titulo}`}>
        <table className="geo-tabela">
          <tbody>
            <tr><th scope="row">terminais</th><td style={{ fontWeight: 700 }}>{fmt(bloco?.n_terminais)}</td></tr>
            <tr><th scope="row">compras</th><td>{fmt(bloco?.compras)}</td></tr>
            <tr><th scope="row">servidor (explain)</th><td style={{ fontWeight: 700 }}>{fmtMs(plano.ms_servidor)}</td></tr>
            <tr><th scope="row">parede p50 ({bloco?.ms_parede?.length || 0}×)</th><td>{fmtMs(bloco?.ms_parede_p50)}</td></tr>
            <tr><th scope="row">primeiro estágio</th><td><code>{plano.primeiro_estagio || '—'}</code></td></tr>
            {plano.indice_usado && <tr><th scope="row">índice</th><td><code>{plano.indice_usado}</code></td></tr>}
            {plano.totalKeysExamined != null && (
              <tr><th scope="row">chaves · docs examinados</th>
                <td>{fmt(plano.totalKeysExamined)} · {fmt(plano.totalDocsExamined)}</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {extra}
    </div>
  )
}

export default function PainelGeocerca({ municipios }) {
  const { call } = useApi()
  const [centroIdx, setCentroIdx] = useState(0)
  const [raio, setRaio] = useState(15)
  const [catIdx, setCatIdx] = useState(0)
  const [termo, setTermo] = useState(CATEGORIAS[0].termos[0])
  const [r, setR] = useState(null)
  const [densificar, setDensificar] = useState(false)
  const [ocupado, setOcupado] = useState(false)
  const centro = municipios[centroIdx]?.centro || null
  const cat = CATEGORIAS[catIdx]

  const rodar = async () => {
    if (!centro) return
    setOcupado(true)
    try {
      const d = await call('/geo/geocerca-comparar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ centro, raioKm: raio, categoria: cat.categoria, termo, execucoes: 3, densificar }),
      })
      if (d) setR(d)
    } finally { setOcupado(false) }
  }

  const s = r?.search
  const cmp = r?.comparacao
  // O mapa mostra uma amostra: 166 marcadores e a lista deles soterram a tela.
  // Os terminais em que os motores divergem entram primeiro: são a evidência.
  const divergentes = new Set([...(cmp?.so_nativo || []), ...(cmp?.so_search || [])])
  const todos = new Map([...(s?.terminais || []), ...(r?.nativo?.terminais || [])].map(t => [t._id, t]))
  const pontos = [...todos.values()]
    .sort((a, b) => (divergentes.has(b._id) - divergentes.has(a._id)) || a._id.localeCompare(b._id))
    .slice(0, MAX_NO_MAPA)
    .map(t => ({ endToEndId: t._id, dispositivo: { id: t._id }, municipio: t.municipio, local: t.local }))
  const rel = s?.relevancia
  const razao = r && s?.estado === 'ok' && r.nativo.plano?.ms_servidor && s.plano?.ms_servidor
    ? s.plano.ms_servidor / Math.max(r.nativo.plano.ms_servidor, 1)
    : null

  return (
    <section className="card">
      <div className="kicker" style={{ marginBottom: 8, color: '#52ddec' }}>04 · Geocerca: mesma pergunta, dois motores</div>
      <h2 style={{ fontSize: 18, marginBottom: 6 }}>
        Quais pontos estão dentro da zona? 2dsphere nativo e Atlas Search, lado a lado
      </h2>
      <CasoNegocio casos={[
        { setor: 'Logística', pergunta: 'quais pontos de coleta ou entrega caem dentro da zona atendida por esta base?' },
        { setor: 'Seguros', pergunta: 'quais estabelecimentos segurados estão dentro de uma área de risco (alagamento, granizo)?' },
        { setor: 'Varejo', pergunta: 'quantas lojas de uma categoria existem dentro do polígono de expansão, e com que movimento?' },
      ]} />
      <p style={{ color: 'var(--text-secondary)', fontSize: 13, marginBottom: 14 }}>
        A geocerca é um polígono irregular sintético em volta do centro escolhido, não um limite real. Os dois caminhos
        rodam o mesmo filtro (polígono + categoria) e o mesmo <code>$group</code>; a resposta é comparada terminal a
        terminal e a latência é medida com o mesmo trabalho dos dois lados (sem texto). O texto entra à parte, como
        <code> should</code> num <code>compound</code> do Search: ordena por relevância, e o custo dessa pontuação aparece
        separado, porque o nativo não a faz. Em geocercas grandes (≈ 600 km em Sorocaba, Campinas ou Florianópolis, neste dataset) as bordas
        divergem: o Search traça a aresta reta em lng/lat e o 2dsphere, geodésica. “Densificar bordas” põe um vértice a
        cada ~5 km e os dois voltam a concordar, ao custo de um polígono mais pesado.
      </p>

      <div className="geo-controles">
        <label>centro
          <select value={centroIdx} onChange={e => setCentroIdx(Number(e.target.value))}>
            {municipios.map((m, i) => <option key={i} value={i}>{m.municipio}/{m.uf}</option>)}
          </select>
        </label>
        <label>tamanho da geocerca
          <select value={raio} onChange={e => setRaio(Number(e.target.value))}>
            {RAIOS_GEOCERCA_KM.map(v => <option key={v} value={v}>≈ {v} km</option>)}
          </select>
        </label>
        <label>categoria
          <select value={catIdx} onChange={e => { const i = Number(e.target.value); setCatIdx(i); setTermo(CATEGORIAS[i].termos[0]) }}>
            {CATEGORIAS.map((c, i) => <option key={c.categoria} value={i}>{c.categoria}</option>)}
          </select>
        </label>
        <label>texto (só no Search)
          <select value={termo} onChange={e => setTermo(e.target.value)}>
            {cat.termos.map(t => <option key={t} value={t}>{t || '— sem texto —'}</option>)}
          </select>
        </label>
        <label style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          <input type="checkbox" checked={densificar} onChange={e => setDensificar(e.target.checked)} />
          densificar bordas
        </label>
        <button className="btn btn-sm btn-primary" onClick={rodar} disabled={ocupado || !centro}>
          {ocupado ? <><span className="spinner" /> Medindo (3× cada + explain)…</> : 'Comparar os dois motores'}
        </button>
      </div>

      {r && (
        <>
          <p style={{ fontSize: 13, margin: '14px 0 0' }}><strong>{r.pergunta}</strong>{' '}
            <span className="badge badge-gray">{r.vertices} vértices{r.densificado ? ' · bordas densificadas' : ''}</span></p>
          {cmp && (
            <div className={`geo-veredito ${cmp.mesmas_compras ? 'igual' : 'diferente'}`} role="status">
              {cmp.mesmas_compras ? (
                <>Mesma resposta nos dois motores: {fmt(r.nativo.n_terminais)} terminais e {fmt(r.nativo.compras)} compras,
                  terminal a terminal.</>
              ) : (
                <>Respostas diferentes. Só no nativo: {cmp.so_nativo.join(', ') || '—'}; só no Search:{' '}
                  {cmp.so_search.join(', ') || '—'}; compras divergentes: {cmp.compras_divergentes.join(', ') || '—'}.
                  O Search traça a borda do polígono em linha reta no plano lng/lat e o 2dsphere, pelo arco geodésico:
                  um ponto colado à borda pode cair dentro num e fora no outro. Marque “densificar bordas” e compare de novo.</>
              )}
            </div>
          )}

          <div className="geo-motores">
            <div>
              <CartaoMotor titulo="2dsphere nativo · $geoWithin" bloco={r.nativo} />
              <QueryBlock label="Pipeline executado (nativo)" query={
                `db.transacoes.aggregate(${JSON.stringify(r.nativo.pipeline, null, 2)})`} />
            </div>
            <div>
              {s?.estado === 'ok' ? (
                <CartaoMotor titulo="Atlas Search · compound + geoWithin" bloco={s} extra={
                  rel && (
                    <div style={{ fontSize: 12 }}>
                      <small style={{ color: 'var(--text-secondary)' }}>
                        à parte, o que só o Search faz: relevância para “{r.termo}” (<code>should: text</code>)
                        {rel.plano && <> · {fmtMs(rel.plano.ms_servidor)} no servidor, contra {fmtMs(s.plano?.ms_servidor)} sem texto</>}
                      </small>
                      {rel.erro ? <p style={{ margin: '4px 0 0' }}>falhou: <code>{rel.erro}</code></p> : (
                        <ul style={{ paddingLeft: 16, margin: '4px 0 0', lineHeight: 1.6 }}>
                          {rel.resultados.map(x => (
                            <li key={x.terminalId}>{x.nome} · {x.municipio} · score {x.score}</li>
                          ))}
                          {rel.resultados.length === 0 && <li>nenhum nome casou com o termo</li>}
                        </ul>
                      )}
                      <QueryBlock label="Pipeline executado (relevância, à parte)"
                        query={`db.transacoes.aggregate(${JSON.stringify(rel.pipeline, null, 2)})`} />
                    </div>
                  )} />
              ) : (
                <div className="banner banner-warning">
                  <span>⚠️</span>
                  <div>Atlas Search {s?.estado === 'erro' ? 'recusou a consulta' : 'indisponível'}: {s?.mensagem}.
                    O caminho nativo continua medido ao lado.</div>
                </div>
              )}
              {s?.pipeline && <QueryBlock label={`Pipeline ${s.estado === 'ok' ? 'executado' : 'que seria executado'} (Search · ${s.index})`}
                query={`db.transacoes.aggregate(${JSON.stringify(s.pipeline, null, 2)})`} />}
            </div>
          </div>

          {razao != null && (
            <p className="geo-nota-seletividade" style={{ marginTop: 12 }}>
              No servidor, o nativo levou {fmtMs(r.nativo.plano.ms_servidor)} e o Search, {fmtMs(s.plano.ms_servidor)}
              {' '}com o mesmo trabalho: {conclusao(razao)}
              {r.nativo.plano?.indice_usado && <> O nativo usou <code>{r.nativo.plano.indice_usado}</code>.</>}
              {' '}A parede inclui a rede até o cluster; medido agora, varia com cache.
              Um explain por motor por clique: oscila. A medição repetida (mediana) está em
              <code> scripts/bench_geo.py --geocerca</code>.
            </p>
          )}

          {todos.size > MAX_NO_MAPA && (
            <p className="geo-nota-seletividade">
              Mapa com {MAX_NO_MAPA} de {fmt(todos.size)} terminais{divergentes.size > 0
                ? `: primeiro os ${divergentes.size} em que os motores divergem, depois por id.` : ' (ordem do id).'}
            </p>
          )}
          <MapaConsulta centro={r.centro} raioKm={r.raioKm} poligono={r.poligono} amostra={pontos} />
        </>
      )}
    </section>
  )
}
