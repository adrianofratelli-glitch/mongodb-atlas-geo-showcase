# ADR 0003 — Painel 04: a mesma geocerca no 2dsphere nativo e no Atlas Search

- Status: aceito (2026-11-13)
- Complementa: ADR 0002 (painel 03)

## Contexto

O painel 03 já usa `$search` com texto, `near`, raio e facetas, mas não
responde à pergunta que um arquiteto faz primeiro: "para geofencing, uso o
índice 2dsphere do banco ou o Atlas Search?". A pesquisa do tema
(`geoWithin`/`geoShape` em `compound`, `$vectorSearch` com filtro por região)
deixou duas opções:

- **(a)** `geoWithin` (ou `geoShape`) do Search num `compound` com texto e
  filtro, ao lado do `$geoWithin` nativo, com a mesma pergunta, latência e
  explain medidos e a resposta comparada;
- **(b)** busca geo + vetor (`$vectorSearch` com pré-filtro por região).

## Decisão

Implementar **(a)** no painel 04 (`POST /geo/geocerca-comparar`,
`frontend/src/components/PainelGeocerca.jsx`).

- **Pergunta única:** "quais terminais da categoria X estão dentro da
  geocerca, e com quantas compras?". A geocerca é um heptágono irregular
  sintético em volta do centro (`_poligono_geocerca`), não um limite real.
- **Nativo:** `$match` com `estabelecimento.categoria` e `$geoWithin`
  `$geometry` (o planner escolhe `categoria_local_idx`) + `$group` por terminal.
- **Search:** `$search` com `compound.filter` = `geoWithin` `geometry` + `in`
  categoria, e o texto como `should` (ordena por relevância, não filtra; o
  conjunto continua comparável). Mesmo `$group` dentro de um `$facet`, com um
  ramo extra "mais relevantes para o termo".
- **Índice próprio** `idx_geo_geocerca` (não o `idx_geo_estabelecimento` do
  painel 03): só `local` (geo), `estabelecimento.categoria` (token) e
  `estabelecimento.nome` (string pt), com `storedSource` dos campos que o
  `$group` usa e `returnStoredSource: true`. Criado pelo mesmo
  `scripts/create_search_index_geo.sh`.
- **Antes de consultar**, `list_search_indexes` confere que o índice existe
  e está `READY`/`queryable` (`_estado_search_index`). `$search` com índice
  ausente ou em BUILDING devolve vazio sem erro; sem o índice, o Search não
  roda, o card mostra "indisponível" e o nativo continua medido. O
  `_search_disponivel` do painel 03 passou a usar a mesma checagem.
- **Medição:** cada motor roda 3×, alternados (parede p50, inclui a rede),
  mais um `explain("executionStats")` do mesmo pipeline (tempo no servidor:
  `executionTimeMillisEstimate` do último estágio). Do bloco do mongot só saem
  números: ele traz o host do nó.
- **A MQL exibida é a executada:** a resposta devolve os dois pipelines exatos
  enviados ao `aggregate` e ao `explain` (teste offline compara as listas).
- **`geoShape` fica de fora:** o dataset só tem pontos. `geoWithin` é o
  operador do Search para pontos; `geoShape` serve a formas indexadas e exige
  `indexShapes: true`, que aumenta o índice sem mudar a resposta aqui.

## Achados medidos (geo_f4_test, 150 mil docs, MongoDB 9.0.7)

- **Mesma resposta** em 117 de 120 casos (40 municípios × 8/60/600 km,
  farmácia): conjunto de terminais e compras iguais, terminal a terminal.
- **Divergência real em 3 casos de 600 km** (Sorocaba, Campinas,
  Florianópolis): 1 a 3 terminais só no Search. O Search traça a aresta do
  polígono como reta no plano lng/lat; o 2dsphere, como arco geodésico. Em
  arestas de centenas de km, o ponto perto da borda cai dentro num e fora no
  outro. A tela mostra a diferença sem ajuste.
- **Remédio medido:** "densificar bordas" (`_densificar_anel`, um vértice a
  cada 0,05° ≈ 5,5 km; 7 → ~600 vértices) alinha os dois motores nos três
  casos. Custo: o polígono denso pesa mais no nativo que no Search.
- **Latência no servidor** (mediana de 3 explains, farmácia, termo
  "drogaria"):

  | geocerca | vértices | terminais nativo / Search | mesma resposta | nativo (ms) | Search (ms) |
  |---|---:|---:|---|---:|---:|
  | São Paulo ≈ 8 km | 7 | 8 / 8 | sim | 37 | 84 |
  | São Paulo ≈ 15 km | 7 | 24 / 24 | sim | 50 | 130 |
  | São Paulo ≈ 60 km | 7 | 48 / 48 | sim | 50 | 142 |
  | Sorocaba ≈ 600 km | 7 | 163 / 166 | não (3 só no Search) | 110 | 227 |
  | Sorocaba ≈ 600 km, densificada | 598 | 166 / 166 | sim | 380 | 238 |

  Para polígono simples + igualdade, o nativo com índice composto é o caminho
  mais barato (≈ 2–3× menos). Com polígono de centenas de vértices a ordem se
  inverte. O Search se paga quando a pergunta tem texto, relevância ou
  facetas. A tela mostra os números de cada clique, sem conclusão fixa.

## Por que não (b) agora

- O único texto do dataset é o nome sintético do estabelecimento
  (prefixo + sufixo, como "Drogaria Central") e a categoria. Embedding disso
  não traz sinal semântico que o `text` fuzzy e o `in` de categoria não
  tragam; seria vetor de vitrine.
- O `filter` do `$vectorSearch` não tem predicado geoespacial; a própria doc
  aponta o operador `vectorSearch` dentro de `$search` para filtrar por
  localização. Fazer isso direito exige dado textual rico (descrição,
  avaliação, sinistro narrado), modelo de embedding via gateway e um índice
  vetorial: fica como evolução se a PoV ganhar esse dado.

## Consequências

- A tese "geo no mesmo cluster, dois motores, você escolhe pela pergunta"
  fica medida na tela, com a divergência de borda exposta e o remédio.
- Mais um índice Search na coleção (`idx_geo_geocerca`). No banco da demo
  `geo`, ele só existe depois de `./scripts/create_search_index_geo.sh`; até
  lá o painel 04 mostra o Search indisponível e o `seed_geo.py --check`
  reprova.
- Cada clique custa 6 agregações + 2 explains (≈ 3–5 s de parede a partir
  de um notebook com RTT ≈ 320 ms).
