import React, { useEffect, useState } from 'react'
import { useApi } from '../hooks/useApi'
import MapaConsulta from './MapaConsulta'
import QueryBlock from './QueryBlock'

export default function ComparacaoRotas({ operador, centro, raioKm, cidade }) {
  const { call, loading, error } = useApi()
  const [data, setData] = useState(null)
  const [tentativa, setTentativa] = useState(0)
  const executar = () => setTentativa(v => v + 1)
  const lng = centro[0], lat = centro[1]
  useEffect(() => {
    const controller = new AbortController()
    setData(null)
    call(`/geo/rotas-comparar?${new URLSearchParams({ lng, lat, raioKm })}`, { signal: controller.signal })
      .then(result => { if (result && !controller.signal.aborted) setData(result) })
    return () => controller.abort()
  }, [lng, lat, raioKm, tentativa, call])
  if (!data) return <div role="status">
    <p>{loading ? 'Consultando as rotas no Atlas…' : error || 'Carregando exemplo…'}</p>
    {error && <button className="btn btn-sm" onClick={executar}>Tentar novamente</button>}
  </div>
  const resultado = data.resultados.find(r => r.operador === operador)
  return <div>
    <p className="query-map-note">3 rotas sintéticas · {cidade} · raio de {raioKm} km · consulta no Atlas via $documents</p>
    <p style={{ fontSize: 13 }}><strong>{operador === '$geoWithin'
      ? 'Quais rotas ficam inteiramente na área de atendimento?'
      : 'Quais rotas passam pela área de atendimento?'}</strong></p>
    <table style={{ width: '100%', fontSize: 12 }}>
      <thead><tr><th>Rota</th>{data.resultados.map(r => <th key={r.operador}>{r.operador}</th>)}</tr></thead>
      <tbody>{data.rotas.map(rota => <tr key={rota.id}>
        <td>{rota.id} · {rota.nome}</td>
        {data.resultados.map(r => <td key={r.operador} style={{ color: r.ids.includes(rota.id) ? '#00ed64' : 'var(--text-secondary)' }}>
          {r.ids.includes(rota.id) ? 'Retornada' : 'Não retornada'}
        </td>)}
      </tr>)}</tbody>
    </table>
    <MapaConsulta centro={data.centro} poligono={data.poligono} rotas={data.rotas} idsResultado={resultado.ids} />
    <QueryBlock defaultOpen label="Filtro executado" query={JSON.stringify(resultado.query, null, 2)} />
    <QueryBlock label="Ver entrada e pipeline completo" query={JSON.stringify(data.pipeline, null, 2)} />
    <button className="btn btn-sm" disabled={loading} onClick={executar}>{loading ? 'Consultando…' : 'Executar novamente no Atlas'}</button>
  </div>
}
