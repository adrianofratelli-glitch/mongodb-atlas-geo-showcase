const R = 6371008.8
export const TILE_SIZE = 256
export function project([lng, lat], zoom = 0) {
  const sin = Math.sin(Math.max(-85.05112878, Math.min(85.05112878, lat)) * Math.PI / 180)
  const size = TILE_SIZE * 2 ** zoom
  return [(lng + 180) / 360 * size, (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * size]
}
export function unproject([x, y], zoom = 0) {
  const size = TILE_SIZE * 2 ** zoom
  return [x / size * 360 - 180, Math.atan(Math.sinh(Math.PI * (1 - 2 * y / size))) * 180 / Math.PI]
}
export function circleRing([lng, lat], radiusKm) {
  const phi = lat * Math.PI / 180, lambda = lng * Math.PI / 180, d = radiusKm * 1000 / R
  return Array.from({ length: 97 }, (_, i) => {
    const bearing = i / 96 * Math.PI * 2
    const p = Math.asin(Math.sin(phi) * Math.cos(d) + Math.cos(phi) * Math.sin(d) * Math.cos(bearing))
    const l = lambda + Math.atan2(Math.sin(bearing) * Math.sin(d) * Math.cos(phi), Math.cos(d) - Math.sin(phi) * Math.sin(p))
    return [l * 180 / Math.PI, p * 180 / Math.PI]
  })
}
export function fitView(coords, width, height, maxZoom = 16) {
  const pts = coords.map(c => project(c))
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1])
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys)
  const zoom = Math.max(3, Math.min(maxZoom, Math.floor(Math.log2(Math.min(
    Math.max(100, width - 120) / Math.max(maxX - minX, .00001),
    Math.max(100, height - 100) / Math.max(maxY - minY, .00001),
  )))))
  return { center: unproject([(minX + maxX) / 2, (minY + maxY) / 2]), zoom }
}
export const metersPerPixel = (lat, zoom) => Math.cos(lat * Math.PI / 180) * 2 * Math.PI * R / (256 * 2 ** zoom)
