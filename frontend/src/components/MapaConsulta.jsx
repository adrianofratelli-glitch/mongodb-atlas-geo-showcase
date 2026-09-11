import React, { useEffect, useMemo, useRef, useState } from 'react'
import { circleRing, fitView, metersPerPixel, project } from './geoMapMath.mjs'

const TILES = import.meta.env.VITE_MAP_TILES_URL || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'

export default function MapaConsulta({ centro, raioKm, poligono, amostra = [], rotas = [], idsResultado = [] }) {
  const ref = useRef(null)
  const [width, setWidth] = useState(850)
  const height = 380
  const [failed, setFailed] = useState(false)
  const [mode, setMode] = useState('resultados')
  const [manual, setManual] = useState(null)
  const [selected, setSelected] = useState(null)
  const [opened, setOpened] = useState(null)
  const points = amostra.filter(a => a.local?.coordinates)
  const ring = useMemo(() => poligono?.coordinates[0] || circleRing(centro, raioKm), [poligono, centro, raioKm])
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(ref.current)
    return () => observer.disconnect()
  }, [])
  const fitted = fitView(mode === 'area' ? [...ring, centro] : [centro, ...points.map(a => a.local.coordinates),
    ...rotas.flatMap(r => r.local.coordinates)], width, height)
  const geometryKey = JSON.stringify([centro, raioKm, poligono, amostra, rotas])
  useEffect(() => {
    setManual(null)
    setSelected(null)
    setOpened(null)
  }, [geometryKey])
  const view = manual || fitted
  const origin = project(view.center, view.zoom)
  const left = origin[0] - width / 2, top = origin[1] - height / 2
  const position = c => { const p = project(c, view.zoom); return [p[0] - left, p[1] - top] }
  const inside = ([x, y], pad = 25) => x > pad && y > pad && x < width - pad && y < height - pad
  const grouped = new Map()
  points.forEach((a, i) => {
    const key = a.local.coordinates.join(',')
    if (!grouped.has(key)) grouped.set(key, { coord: a.local.coordinates, indices: [] })
    grouped.get(key).indices.push(i)
  })
  const tiles = []
  if (!failed) {
    const n = 2 ** view.zoom
    for (let x = Math.floor(left / 256); x <= Math.floor((left + width) / 256); x++) {
      for (let y = Math.floor(top / 256); y <= Math.floor((top + height) / 256); y++) {
        if (y < 0 || y >= n) continue
        const wrappedX = ((x % n) + n) % n
        tiles.push({ key: `${view.zoom}/${wrappedX}/${y}`, x: x * 256 - left, y: y * 256 - top,
          url: TILES.replace('{z}', view.zoom).replace('{x}', wrappedX).replace('{y}', y) })
      }
    }
  }
  const mpp = metersPerPixel(view.center[1], view.zoom)
  const scaleM = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000]
    .filter(n => n / mpp < Math.min(140, width / 3)).pop() || 10
  const chooseMode = next => { setMode(next); setManual(null); setSelected(null); setOpened(null) }
  const focus = i => {
    setSelected(i)
    setOpened(grouped.get(points[i].local.coordinates.join(',')))
    setManual({ center: points[i].local.coordinates, zoom: Math.max(view.zoom, 15) })
  }
  return (
    <div className="query-map" ref={ref}>
      <div className="query-map-toolbar">
        <div role="group" aria-label="Enquadramento do mapa">
          <button className="tag" aria-pressed={mode === 'resultados' && !manual} onClick={() => chooseMode('resultados')}>Ver resultados</button>
          <button className="tag" aria-pressed={mode === 'area' && !manual} onClick={() => chooseMode('area')}>Área completa</button>
        </div>
        <span className="tag">Ruas · online</span>
      </div>
      <div className="query-map-surface roads" style={{ height }}>
        {!failed && <>
        {tiles.map(t => <img key={t.key} src={t.url} alt="" referrerPolicy="origin" draggable={false}
          style={{ position: 'absolute', left: t.x, top: t.y, width: 256, height: 256 }}
          onError={() => setFailed(true)} />)}
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={rotas.length ? "Área consultada e rotas retornadas pelo operador" : "Área da consulta e localização dos resultados; use os botões numerados para explorar"}>
          <polygon points={ring.map(c => position(c).join(',')).join(' ')} fill="#007f9c12"
            stroke="#007b94" strokeWidth="2" strokeDasharray={poligono ? undefined : '7 4'} />
          {rotas.map(r => {
            const returned = idsResultado.includes(r.id)
            const [x, y] = position(r.local.coordinates[0])
            return <g key={r.id}>
              <title>{r.id} · {r.nome} · {returned ? 'retornada' : 'não retornada'}</title>
              <polyline points={r.local.coordinates.map(c => position(c).join(',')).join(' ')} fill="none" stroke="#fff" strokeWidth="7" />
              <polyline points={r.local.coordinates.map(c => position(c).join(',')).join(' ')} fill="none"
                stroke={returned ? '#007c38' : '#64748b'} strokeWidth="4" strokeDasharray={returned ? undefined : '6 5'} />
              <circle cx={x} cy={y} r="12" fill={returned ? '#007c38' : '#64748b'} stroke="#fff" strokeWidth="2" />
              <text x={x} y={y + 4} fill="#fff" fontSize="12" fontWeight="700" textAnchor="middle">{r.id}</text>
            </g>
          })}
          {(() => {
            const [x, y] = position(centro)
            return !rotas.length && inside([x, y], 0) && <g>
              <circle cx={x} cy={y} r="23" fill="none" stroke="#006078" strokeWidth="2" />
              <path d={`M${x - 30},${y}h10 M${x + 20},${y}h10 M${x},${y - 30}v10 M${x},${y + 20}v10`}
                stroke="#006078" strokeWidth="2" />
              <text x={x} y={y + 44} textAnchor="middle" fontSize="12" fill="#003747"
                stroke="#fff" strokeWidth="3" paintOrder="stroke">centro da consulta</text>
            </g>
          })()}
          {[...grouped.values()].map(p => {
            const [x, y] = position(p.coord), active = p.indices.includes(selected)
            if (!inside([x, y], 0)) return null
            return <g key={p.coord.join(',')} className="query-map-marker" role="button" tabIndex="0"
              aria-label={`Resultado ${p.indices.map(i => i + 1).join(', ')}; abrir detalhes e aproximar`}
              onClick={() => focus(p.indices[0])} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); focus(p.indices[0]) } }}>
              <title>{p.indices.map(i => points[i].endToEndId).join(' · ')}</title>
              <circle cx={x} cy={y} r={active ? 17 : 14} fill={active ? '#fff' : '#00ed64'} stroke="#003a25" strokeWidth="2" />
              <text x={x} y={y + 4} textAnchor="middle" fontSize="11" fontWeight="700" fill="#003522">{p.indices.length > 1 ? `×${p.indices.length}` : p.indices[0] + 1}</text>
            </g>
          })}
        </svg>
        {opened && <section className="query-map-popup" aria-label="Detalhes da localização" onKeyDown={e => {
          if (e.key === 'Escape') setOpened(null)
        }}>
          <button className="query-map-popup-close" aria-label="Fechar detalhes da localização" onClick={() => setOpened(null)}>×</button>
          <strong>{opened.indices.length > 1 ? `${opened.indices.length} resultados na mesma posição` : 'Localização do resultado'}</strong>
          <p>Longitude {opened.coord[0]}<br />Latitude {opened.coord[1]}</p>
          <div className="query-map-popup-list">
            {opened.indices.map(i => <button key={points[i].endToEndId} aria-pressed={selected === i} onClick={() => focus(i)}>
              <b>{i + 1} · {points[i].dispositivo?.id || points[i].municipio}</b>
              <span>{points[i].endToEndId}</span>
            </button>)}
          </div>
          {opened.indices.length > 1 && <p>Os documentos compartilham a mesma coordenada cadastrada.</p>}
        </section>}
        <div className="query-map-zoom">
          <button aria-label="Aproximar mapa" disabled={view.zoom >= 18} onClick={() => setManual({ ...view, zoom: view.zoom + 1 })}>+</button>
          <button aria-label="Afastar mapa" disabled={view.zoom <= 3} onClick={() => setManual({ ...view, zoom: view.zoom - 1 })}>−</button>
        </div>
        <div className="query-map-scale"><span style={{ width: scaleM / mpp }} />{scaleM >= 1000 ? `${scaleM / 1000} km` : `${scaleM} m`}</div>
        <div className="query-map-attribution"><a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors</a></div>
        </>}
        {failed && <div className="query-map-unavailable" role="status">
          <p>Mapa de ruas indisponível. Verifique a conexão com a internet.</p>
          <button className="tag" onClick={() => setFailed(false)}>Tentar novamente</button>
        </div>}
      </div>
      <div className="query-map-legend">{rotas.length ? <><span>━ Verde: retornada</span><span>┄ Cinza: não retornada</span></> : <><span>◎ Centro</span><span>● Resultados da amostra</span></>}<span>{poligono ? '▱ Polígono consultado' : `◯ Raio de ${raioKm} km`}</span></div>
      <div className="query-map-results">
        {points.map((a, i) => <button key={a.endToEndId} aria-pressed={selected === i} onClick={() => focus(i)}>
          <b>{i + 1}</b><span>{a.dispositivo?.id || a.municipio}</span>
          {a.distanciaMetros != null && <strong>{a.distanciaMetros.toLocaleString('pt-BR')} m</strong>}
        </button>)}
      </div>
      <p className="query-map-note">{rotas.length ? 'Traçados sintéticos para comparar geometrias; não representam trajetos calculados pelas ruas.' : 'Contorno aproximado para visualização. Pontos coincidentes são agrupados; a query define a área e calcula os resultados.'}</p>
    </div>
  )
}
