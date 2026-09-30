import React, { useEffect, useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import QueryBlock from '../components/QueryBlock'
import MiniMapa from '../components/MapaBrasil'
import MapaConsulta from '../components/MapaConsulta'
import ComparacaoRotas from '../components/ComparacaoRotas'
import ComparacaoOperadores from '../components/ComparacaoOperadores'
import Limites from '../components/Limites'

// Nenhum campo desta aba é texto livre. Um clienteId digitado errado devolve
// tela vazia, e no palco isso é lido como "a demo não encontrou nada" — não
// como erro de digitação. Toda opção abaixo existe no dataset gerado por
// scripts/seed_geo.py.
const LIMITES_KMH = [300, 600, 900, 1200, 2000]
const RAIOS_OPERADORES_KM = [10, 25, 50, 100, 200]

// "2239.8 ms" obriga a plateia a contar casas; acima de 1 s a unidade muda.
const fmtDuracao = (ms) => (ms == null
  ? '—'
  : ms >= 1000 ? `${(ms / 1000).toFixed(1).replace('.', ',')} s` : `${Math.round(ms)} ms`)

export default function Geo() {
  const { call } = useApi()
  // Cada ação controla o próprio estado: rodar a detecção não pode desabilitar
  // outra ação da mesma tela.
  const [ocupado, setOcupado] = useState({})
  const comOcupado = async (chave, fn) => {
    setOcupado((o) => ({ ...o, [chave]: true }))
    try { return await fn() } finally { setOcupado((o) => ({ ...o, [chave]: false })) }
  }
  const [status, setStatus] = useState(null)
  const [municipios, setMunicipios] = useState([])

  // 01 — sinal de risco (impossible travel)
  const [limiteKmh, setLimiteKmh] = useState(900)
  const [viagens, setViagens] = useState(null)
  const [viagemSel, setViagemSel] = useState(null)
  const [clienteFiltro, setClienteFiltro] = useState('')
  const [medicoesViagens, setMedicoesViagens] = useState({})

  // 02 — operadores de consulta geoespacial
  const [centroIdx, setCentroIdx] = useState(0)
  const [raioOperadores, setRaioOperadores] = useState(50)
  const [operadores, setOperadores] = useState(null)
  const [operadorSel, setOperadorSel] = useState('$geoWithin')
  const [mostrarRotas, setMostrarRotas] = useState(true)
  const grupoArea = ['$geoWithin', '$geoIntersects'].includes(operadorSel)

  useEffect(() => {
    call('/geo/status').then(d => d && setStatus(d))
    call('/geo/municipios').then(d => d && setMunicipios(d.municipios || []))
  }, [])

  const centro = municipios[centroIdx]?.centro || null

  const [reconsulta, setReconsulta] = useState(0)
  const rodarOperadores = () => setReconsulta(v => v + 1)
  useEffect(() => {
    const controller = new AbortController()
    setOperadores(null)
    const timer = setTimeout(() => comOcupado('operadores', async () => {
    if (!centro) return
    const d = await call('/geo/operadores', {
      method: 'POST',
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ centro, raioKm: Number(raioOperadores), limite: 5 }),
    })
    if (d && !controller.signal.aborted) setOperadores(d)
    }), 250)
    return () => { clearTimeout(timer); controller.abort() }
  }, [centro, raioOperadores, reconsulta, call])

  // O recorte é a resposta à pergunta de escala: filtrar antes da janela reduz
  // o universo varrido.
  const rodarViagens = (clienteId = '') => comOcupado('viagens', async () => {
    const alvo = clienteId.trim()
    const query = `limiteKmh=${Number(limiteKmh)}${alvo ? `&clienteId=${encodeURIComponent(alvo)}` : ''}`
    const d = await call(`/geo/impossible-travel?${query}`)
    if (d) {
      setViagens(d)
      setViagemSel(d.resultados[0] || null)
      setMedicoesViagens(anteriores => ({
        // Comparar somente execuções com o mesmo limiar da regra.
        ...(anteriores.limite === d.limite_kmh ? anteriores : {}),
        limite: d.limite_kmh,
        [alvo ? 'cliente' : 'colecao']: { ...d.custo, clienteId: alvo },
      }))
    }
  })

  // Os clientes ofertados são os que o seed plantou (backend lê fraud_seeds.json):
  // a opção existe no dataset, então nenhuma seleção devolve tela vazia por engano.
  // O valor selecionado entra na lista mesmo quando não foi plantado (um caso
  // emergente vindo do próprio resultado), senão o <select> ficaria exibindo uma
  // opção que não existe.
  const clientesPlantados = useMemo(() => {
    const base = status?.fraudes_plantadas?.lista || []
    const extras = [clienteFiltro].filter(c => c && !base.includes(c))
    return [...base, ...extras].sort()
  }, [status, clienteFiltro])

  const semDados = status && status.transacoes === 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {status && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <span className={`badge ${status.transacoes > 0 ? 'badge-green' : 'badge-yellow'}`}>
            {status.transacoes.toLocaleString('pt-BR')} transações · {status.db}.{status.colecao}
          </span>
          <span className="badge badge-gray">{status.indices.length} índices</span>
          <span className="badge badge-gray">dataset sintético · coordenadas dos terminais</span>
          {status.fraudes_plantadas?.clientes > 0 && (
            <span className="badge badge-purple">
              {status.fraudes_plantadas.clientes} cenários de risco disponíveis
            </span>
          )}
        </div>
      )}

      {semDados && (
        <div className="banner banner-warning">
          <span>⚠️</span>
          <div>Dataset vazio. Rode <code>python scripts/seed_geo.py</code> antes da demonstração.</div>
        </div>
      )}

      {/* ── 01 · Sinal de risco ─────────────────────────────────────────── */}
      <section className="card">
        <div className="kicker" style={{ marginBottom: 8, color: '#ff6960' }}>01 · Investigação retrospectiva</div>
        {/* O título prometia detecção ("o mesmo cálculo sobre 90 dias") e a
            evidência entrega investigação. Quem opera antifraude percebe a
            diferença na hora, e a promessa maior é a que derruba a menor. */}
        <h2 style={{ fontSize: 18, marginBottom: 6 }}>
          Investigar 90 dias sem tirar o histórico do banco
        </h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: 13, marginBottom: 14 }}>
          Duas compras presenciais do mesmo cliente, distantes demais para o tempo entre elas.{' '}
          <code>$setWindowFields</code> particiona por cliente, <code>$shift</code> traz a compra anterior e
          a distância sai de haversine em MQL nativo. <strong>O histórico não sai do banco</strong> — nenhuma
          cópia especializada para manter.
        </p>
        {/* A pergunta que a tela deixava sem resposta: "isso está rodando ONDE?".
            Sem a origem explícita, o painel parece cálculo local do frontend. */}
        {status && (
          <div className="geo-origem">
            <div>
              <small>onde roda</small>
              <span>agregação no cluster Atlas</span>
            </div>
            <div>
              <small>coleção</small>
              <span><code>{status.db}.{status.colecao}</code></span>
            </div>
            <div>
              <small>documentos na coleção (estimativa)</small>
              <span>{status.transacoes.toLocaleString('pt-BR')}</span>
            </div>
            <div>
              <small>índice do recorte</small>
              <span><code>cliente_ts_idx</code></span>
            </div>
          </div>
        )}
        <div className="geo-controles">
          <label>limite (km/h)
            <select value={limiteKmh} disabled={ocupado.viagens} onChange={e => setLimiteKmh(Number(e.target.value))}>
              {LIMITES_KMH.map(v => <option key={v} value={v}>{v} km/h</option>)}
            </select>
          </label>
          <button className="btn btn-sm btn-primary" onClick={() => rodarViagens()} disabled={ocupado.viagens}>
            {ocupado.viagens ? <><span className="spinner" /> Calculando…</> : 'Varrer a coleção inteira'}
          </button>
          <label>recorte por cliente
            <select value={clienteFiltro} disabled={ocupado.viagens} onChange={e => setClienteFiltro(e.target.value)}>
              <option value="">— escolha um cliente —</option>
              {clientesPlantados.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <button className="btn btn-sm" onClick={() => rodarViagens(clienteFiltro)}
            disabled={ocupado.viagens || !clienteFiltro.trim()}
            title="O mesmo pipeline sobre um cliente só: é o recorte que mantém isto barato em produção">
            Só este cliente
          </button>
          {viagens && (
            <>
              <span className="badge badge-red">
                {viagens.encontrados} sinalizadas exibidas acima de {viagens.limite_kmh} km/h
                {viagens.truncado && ' (truncado)'}
              </span>
              <span className="badge badge-green">
                {viagens.encontrados_aprovados} não sinalizadas (amostra)
              </span>
            </>
          )}
        </div>

        {viagens && (
          <div className="geo-comparacao" aria-label="Tempos medidos por escopo">
            {['colecao', 'cliente'].map(escopo => {
              const medicao = medicoesViagens[escopo]
              return (
                <div key={escopo}>
                  <small>{escopo === 'colecao' ? 'Coleção inteira' : 'Recorte por cliente'}</small>
                  <strong>{fmtDuracao(medicao?.ms)}</strong>
                  <span>{medicao ? medicao.escopo : 'Execute este escopo para comparar'}</span>
                </div>
              )
            })}
            <p>Últimas execuções nesta tela · limite {medicoesViagens.limite} km/h · tempos sujeitos a cache e rede.</p>
          </div>
        )}

        {viagens && (
          <>
            {/* A pergunta de risco vem antes da de engenharia: quantos casos
                isto joga na fila? Sem denominador, "40 pares" não diz se a
                regra é seletiva ou se inunda a operação. */}
            {viagens.seletividade && (
              <div className="geo-seletividade">
                <div>
                  <span>{(viagens.seletividade.pares_avaliados ?? 0).toLocaleString('pt-BR')}</span>
                  <small>pares consecutivos avaliados</small>
                </div>
                <div>
                  <span style={{ color: '#ff6960' }}>{viagens.seletividade.sinalizados}</span>
                  <small>sinalizados acima de {viagens.limite_kmh} km/h</small>
                </div>
                <div>
                  <span>{viagens.seletividade.taxa_pct != null
                    ? `${viagens.seletividade.taxa_pct.toLocaleString('pt-BR', { maximumFractionDigits: 4 })}%`
                    : '—'}</span>
                  <small>taxa de sinalização</small>
                </div>
                {viagens.seletividade.alertas_por_dia != null && (
                  <div>
                    <span>{viagens.seletividade.alertas_por_dia.toLocaleString('pt-BR')}</span>
                    <small>alertas por dia em {viagens.seletividade.janela_dias} dias de histórico</small>
                  </div>
                )}
              </div>
            )}
            {viagens.seletividade && (
              <p className="geo-nota-seletividade">Dataset sintético · taxa de sinalização, não acurácia de fraude.</p>
            )}
          </>
        )}

        {viagens && (
          <div className="row" style={{ marginTop: 16, alignItems: 'flex-start' }}>
            <div className="col" style={{ minWidth: 320 }}>
              <div className="geo-tabela-wrap" tabIndex={0} role="region"
                aria-label="Resultados da investigação retrospectiva — lista rolável">
                <table className="geo-tabela">
                  <thead>
                    <tr><th>cliente</th><th>km</th><th>min</th><th>km/h</th><th>trajeto</th><th>resultado da regra</th></tr>
                  </thead>
                  <tbody>
                    {viagens.resultados.map(v => (
                      <tr key={v.endToEndId}
                        className={viagemSel?.endToEndId === v.endToEndId ? 'sel' : ''}
                        onClick={() => setViagemSel(v)}>
                        <td><code>{v.clienteId}</code></td>
                        <td>{v.km}</td>
                        <td>{v.minutos}</td>
                        <td style={{ color: v.classificacao === 'sinalizada' ? '#ff6960' : 'inherit', fontWeight: 700 }}>
                          {v.kmh}
                        </td>
                        <td>{v.de.municipio} → {v.para.municipio}</td>
                        {/* Duas faces da mesma decisão: sinalizada acima do
                            limite, não sinalizada dentro dele. */}
                        <td>
                          <span className={`badge ${v.classificacao === 'sinalizada' ? 'badge-red' : 'badge-green'}`}>
                            {v.classificacao === 'sinalizada' ? 'sinalizada' : 'não sinalizada'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {viagens.resultados.length === 0 && (
                <p style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
                  Nenhum par acima do limite. Baixe o valor para ver o comportamento.
                </p>
              )}
            </div>
            <div className="col" style={{ minWidth: 260 }}>
              <MiniMapa
                pontos={viagemSel ? [
                  { coord: viagemSel.de.coordinates, rotulo: `origem — ${viagemSel.de.municipio}`, cor: '#06b6d4', destaque: true },
                  { coord: viagemSel.para.coordinates, rotulo: `destino — ${viagemSel.para.municipio}`, cor: '#ff6960', destaque: true },
                ] : []}
                linha={viagemSel ? { de: viagemSel.de.coordinates, para: viagemSel.para.coordinates } : null}
                rotuloLinha={viagemSel ? `${viagemSel.km} km · ${viagemSel.minutos} min` : null}
              />
              {viagemSel && (
                <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 8 }}>
                  <code>{viagemSel.clienteId}</code> · {viagemSel.km} km em {viagemSel.minutos} min
                  {/* Proveniência à vista: o terminal é o que separa este sinal
                      de um palpite sobre o GPS do cliente. */}
                  <div style={{ marginTop: 5 }}>
                    origem <code>{viagemSel.de.dispositivo?.id || '—'}</code> → destino{' '}
                    <code>{viagemSel.para.dispositivo?.id || '—'}</code>
                    <br />captura por {viagemSel.para.localizacaoMeta?.origem === 'TERMINAL_ADQUIRENTE'
                      ? 'terminal do adquirente (posição fixa)'
                      : (viagemSel.para.localizacaoMeta?.origem || 'origem desconhecida')}
                  </div>
                  <button className="btn btn-xs btn-ghost" style={{ marginLeft: 8 }}
                    disabled={ocupado.viagens}
                    onClick={() => {
                      setClienteFiltro(viagemSel.clienteId)
                      rodarViagens(viagemSel.clienteId)
                    }}>
                    {ocupado.viagens ? 'Investigando…' : 'Investigar este cliente'}
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {viagens && (
          <div style={{ marginTop: 12 }}>
            {viagens.seletividade?.nota && (
              <p className="geo-nota-seletividade">
                {viagens.seletividade.nota}
                {/* A taxa é consequência do que o seed plantou. Deixar isso
                    implícito convida o analista a comparar com o número dele. */}
                {viagens.seletividade.aviso && (
                  <> <strong>{viagens.seletividade.aviso}</strong></>
                )}
              </p>
            )}

            <QueryBlock label="Ver pipeline completo"
              query={JSON.stringify(viagens.pipeline, null, 2)} />
          </div>
        )}
      </section>

      {/* ── 02 · Operadores de consulta ─────────────────────────────────── */}
      <section className="card">
        <div className="kicker" style={{ marginBottom: 8, color: '#00ED64' }}>02 · Operadores de consulta geoespacial</div>
        <h2 style={{ fontSize: 18, marginBottom: 6 }}>
          Consultar por área, proximidade e distância
        </h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: 13, marginBottom: 14 }}>
          Escolha a pergunta e compare quando usar cada operador. Selecione um operador para ver seu mapa e sua query.
        </p>

        <div className="geo-grupos" role="group" aria-label="Tipo de consulta geoespacial">
          <button className="tag" aria-pressed={grupoArea} onClick={() => setOperadorSel('$geoWithin')}>
            Área · dentro ou intersecta?
          </button>
          <button className="tag" aria-pressed={!grupoArea} onClick={() => setOperadorSel('$near')}>
            Proximidade · quais estão mais perto?
          </button>
        </div>
        <ComparacaoOperadores area={grupoArea} selecionado={operadorSel}
          onSelecionar={setOperadorSel} resultados={operadores?.resultados} colecao={status?.colecao} />

        <div className="geo-controles">
          <label>centro
            <select value={centroIdx} onChange={e => setCentroIdx(Number(e.target.value))}>
              {municipios.map((m, i) => <option key={i} value={i}>{m.municipio}/{m.uf}</option>)}
            </select>
          </label>
          <label>raio (km)
            <select value={raioOperadores} onChange={e => setRaioOperadores(Number(e.target.value))}>
              {RAIOS_OPERADORES_KM.map(v => <option key={v} value={v}>{v} km</option>)}
            </select>
          </label>
          <button className="btn btn-sm btn-primary" onClick={rodarOperadores} disabled={ocupado.operadores || !centro}>
            {ocupado.operadores ? <><span className="spinner" /> Rodando…</> : 'Rodar os 5 operadores'}
          </button>
        </div>

        {operadores && (
          <div className="row" style={{ marginTop: 16, alignItems: 'stretch', flexWrap: 'wrap' }}>
            {operadores.resultados.filter(r => r.operador === operadorSel).map(r => (
              <div key={r.operador} className="col card" style={{ minWidth: 260, flex: '1 1 260px' }}>
                {['$geoWithin', '$geoIntersects'].includes(r.operador) && <div role="group" aria-label="Geometria do exemplo" style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
                  <button className="tag" aria-pressed={mostrarRotas} onClick={() => setMostrarRotas(true)}>Rotas · LineString</button>
                  <button className="tag" aria-pressed={!mostrarRotas} onClick={() => setMostrarRotas(false)}>Terminais · Point</button>
                </div>}
                {mostrarRotas && ['$geoWithin', '$geoIntersects'].includes(r.operador) ? <ComparacaoRotas operador={r.operador} centro={operadores.centro} raioKm={operadores.raioKm} cidade={`${municipios[centroIdx]?.municipio}/${municipios[centroIdx]?.uf}`} /> : <>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <code style={{ fontSize: 14, fontWeight: 700 }}>{r.operador}</code>
                  <span className="badge badge-gray">
                    {r.contagem == null ? `${r.amostra.length} primeiros documentos` : `${r.contagem} documentos`}
                  </span>
                </div>
                {!grupoArea && <p className="query-map-note">Mapa e query de {r.operador} · centro [{operadores.centro.join(', ')}] · raio {operadores.raioKm} km</p>}
                {grupoArea && <p className="query-map-note">Para pontos no interior da área, os dois predicados coincidem. As rotas mostram a diferença entre conter e intersectar.</p>}
                {grupoArea && (r.amostra.length > 0 ? (
                  <>
                    {/* endToEndId à vista: é o identificador real do documento no
                        cluster, não um rótulo inventado pra tela — prova que a
                        amostra veio da consulta, não de um mock. */}
                    <p style={{ color: 'var(--text-disabled)', fontSize: 11, margin: '0 0 4px' }}>
                      {r.amostra.length} {r.amostra_por_terminal ? 'terminais mais próximos (uma transação por terminal)' : 'documentos exibidos'} · {r.colecao || status?.colecao}:
                    </p>
                    <ul style={{ fontSize: 12, paddingLeft: 16, margin: 0, lineHeight: 1.7 }}>
                      {r.amostra.map(a => (
                        <li key={a.endToEndId}>
                          <code style={{ fontSize: 11 }}>{a.endToEndId}</code> · {a.municipio}/{a.uf}
                          {a.distanciaMetros != null && ` · ${a.distanciaMetros.toLocaleString('pt-BR')} m`}
                        </li>
                      ))}
                    </ul>
                  </>
                ) : (
                  <p style={{ color: 'var(--text-secondary)', fontSize: 12 }}>Nenhum documento nesta área.</p>
                ))}
                <div style={{ marginTop: 8 }}>
                  <MapaConsulta centro={operadores.centro} raioKm={operadores.raioKm}
                    amostra={r.amostra}
                    poligono={['$geoWithin', '$geoIntersects'].includes(r.operador) ? operadores.poligono : null} />
                  <QueryBlock defaultOpen label="Query executada" query={JSON.stringify(r.query, null, 2)} />
                </div>
                </>}
              </div>
            ))}
          </div>
        )}
      </section>
      <Limites titulo="Escopo desta demonstração" itens={[
        <>O exemplo de rotas usa três LineStrings sintéticas via $documents, sem índice nem persistência, para demonstrar os predicados. Centro e raio governam terminais e rotas. Os percursos sintéticos mantêm suas distâncias ao centro quando o raio muda; não representam trajetos pelas ruas.</>,
        <>A investigação calcula distância esférica e velocidade implícita; não calcula trajeto por ruas nem aprova uma compra.</>,
        <>As consultas de proximidade aos terminais usam índices 2dsphere. O $geoNear usa uma cópia de demonstração com um único índice geo; o nome da coleção está no resultado.</>,
      ]} />
    </div>
  )
}
