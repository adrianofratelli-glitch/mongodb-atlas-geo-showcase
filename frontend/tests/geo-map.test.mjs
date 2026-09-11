import test from 'node:test'
import assert from 'node:assert/strict'
import { project, unproject, circleRing, fitView, metersPerPixel } from '../src/components/geoMapMath.mjs'

test('projeção mantém coordenadas dos terminais ao alternar o zoom', () => {
  for (const coord of [[-46.6333, -23.5505], [-60.0217, -3.1019], [-51.2177, -30.0346]]) {
    for (const zoom of [3, 10, 16, 18]) {
      const back = unproject(project(coord, zoom), zoom)
      assert.ok(Math.abs(back[0] - coord[0]) < 1e-9)
      assert.ok(Math.abs(back[1] - coord[1]) < 1e-9)
    }
  }
})
test('contorno radial representa a distância solicitada na esfera', () => {
  const centro = [-46.6333, -23.5505], radius = 50
  const rad = n => n * Math.PI / 180
  for (const [lng, lat] of circleRing(centro, radius)) {
    const a = Math.sin(rad(lat - centro[1]) / 2) ** 2 + Math.cos(rad(lat)) * Math.cos(rad(centro[1])) * Math.sin(rad(lng - centro[0]) / 2) ** 2
    const km = 6371.0088 * 2 * Math.asin(Math.sqrt(a))
    assert.ok(Math.abs(km - radius) < 1e-7)
  }
})
test('área inteira cabe tanto em mapa largo quanto em tela estreita', () => {
  const ring = circleRing([-46.6333, -23.5505], 200)
  for (const width of [300, 850]) {
    const view = fitView(ring, width, 380)
    const center = project(view.center, view.zoom)
    for (const point of ring) {
      const p = project(point, view.zoom)
      assert.ok(Math.abs(p[0] - center[0]) < width / 2)
      assert.ok(Math.abs(p[1] - center[1]) < 190)
    }
  }
})
test('pontos coincidentes não produzem zoom infinito e a escala acompanha o zoom', () => {
  const coord = [-46, -23]
  const view = fitView([coord, coord], 850, 380)
  assert.equal(view.zoom, 16)
  assert.ok(Math.abs(metersPerPixel(-23, 15) / metersPerPixel(-23, 16) - 2) < 1e-12)
})
