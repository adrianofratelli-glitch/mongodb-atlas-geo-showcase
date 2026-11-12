# ADR 0002 — Painel 03: explain medido e `$search` com geo na tela

- Status: aceito (2026-11-12)

## Contexto

`POST /geo/explain-compare` e `POST /geo/search` estavam implementados e
testados, mas fora da tela. A prova de que o índice importa (IXSCAN e chaves
examinadas) existia só como texto no README. Medido ao vivo no `geo_test`
(cliente plantado, raio de 2.000 km, centro em São Paulo), para os mesmos
63 documentos devolvidos:

| índice | chaves examinadas | ms (servidor) |
|---|---:|---:|
| `cliente_status_local_idx` (igualdade + geo) | 64 | 0–1 |
| `local_2dsphere_idx` (só geo) | 128.153 | ≈ 400–480 |

## Decisão

- Novo painel `frontend/src/components/PainelIndiceBusca.jsx`, montado em
  `Geo.jsx` depois dos operadores. (A) roda o explain dos dois índices e mostra
  estágios, chaves, devolvidos e ms. (B) roda o `$search` com texto (seleção, não
  texto livre), raio e facetas, e mostra o pipeline e o `$searchMeta`.
- Com termo, o `compound` do Search ganha `should: near` (pivot = metade do
  raio). Nomes iguais ("Padaria da Praça") empatavam no score textual e a ordem
  ficava arbitrária. Agora o desempate é a proximidade, calculada pelo próprio
  Search. Sem termo, a ordem continua sendo a distância haversine.

## Consequências

- A tese "igualdade antes do geo" fica visível e medida a cada clique, com a
  ressalva de cache na tela.
- O mesmo dataset mostra o geo nativo (painel 02) e o geo do Atlas Search
  (painel 03). Fica de fora a comparação lado a lado de latência entre
  `$geoNear` e Search `near` (pendência).
