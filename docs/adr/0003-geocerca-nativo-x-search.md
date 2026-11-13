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
  categoria e o mesmo `$group`. O texto entra num segundo pipeline, com o
  mesmo `filter` e o texto como `should` (ordena por relevância, não filtra),
  que devolve os 5 terminais mais relevantes. Os três pipelines saem de
  `_pipelines_geocerca`, usado pelo endpoint e pelo bench.
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
- **Medição justa:** os dois pipelines comparados fazem o mesmo trabalho
  (filtro + `$group`, sem pontuação). Cada um roda 3×, alternados (parede p50,
  inclui a rede), mais um `explain("executionStats")` (tempo no servidor:
  `executionTimeMillisEstimate` do último estágio). Com termo, o `compound`
  com `should: text` roda à parte, uma vez e em explain: é o custo extra da
  relevância. Falha do lado Search (execução, explain ou relevância) degrada
  só o cartão do Search. Do bloco do mongot só saem
  números: ele traz o host do nó.
- **A MQL exibida é a executada:** a resposta devolve os dois pipelines exatos
  enviados ao `aggregate` e ao `explain` (teste offline compara as listas).
- **`geoShape` fica de fora:** o dataset só tem pontos. `geoWithin` é o
  operador do Search para pontos; `geoShape` serve a formas indexadas e exige
  `indexShapes: true`, que aumenta o índice sem mudar a resposta aqui.

## Achados medidos (geo_f4_test, 150 mil docs, MongoDB 9.0.7)

- **Mesma resposta** em 117 de 120 casos (40 municípios × 8/60/600 km,
  farmácia, sem densificar) e em 120 de 120 com as bordas densificadas:
  conjunto de terminais e compras iguais, terminal a terminal. Varredura
  reproduzível com `GEO_DB=geo_f4_test backend/venv/bin/python scripts/bench_geo.py --geocerca --varredura --runs 5`.
- **Divergência real em 3 casos de 600 km** (Sorocaba, Campinas,
  Florianópolis): 1 a 3 terminais só no Search. O Search traça a aresta do
  polígono como reta no plano lng/lat; o 2dsphere, como arco geodésico. Em
  arestas de centenas de km, o ponto perto da borda cai dentro num e fora no
  outro. A tela mostra a diferença sem ajuste.
- **Remédio medido:** "densificar bordas" (`_densificar_anel`, um vértice a
  cada 0,05° ≈ 5,5 km; 7 → ~600 vértices) alinha os dois motores nos três
  casos e mantém 120/120 na varredura. Custo: o polígono denso pesa mais no nativo que no Search.
- **Latência com o mesmo trabalho dos dois lados** (sem texto: polígono +
  categoria + o mesmo `$group`; servidor = mediana de 5 explains, parede =
  p50 de 5 execuções; RTT ≈ 375 ms). Reproduza com
  `GEO_DB=geo_f4_test backend/venv/bin/python scripts/bench_geo.py --geocerca --varredura --runs 5`:

  | geocerca | vértices | terminais nativo / Search | mesma resposta | nativo servidor (ms) | Search servidor (ms) | Search ÷ nativo | relevância "drogaria" servidor (ms) |
  |---|---:|---:|---|---:|---:|---:|---:|
  | São Paulo ≈ 8 km | 7 | 8 / 8 | sim | 30 | 72 | 2,4× | 84 |
  | São Paulo ≈ 15 km | 7 | 24 / 24 | sim | 46 | 92 | 2,0× | 105 |
  | São Paulo ≈ 60 km | 7 | 48 / 48 | sim | 50 | 97 | 1,9× | 125 |
  | Sorocaba ≈ 600 km | 7 | 163 / 166 | não (3 só no Search) | 109 | 139 | 1,3× | 204 |
  | Sorocaba ≈ 600 km, densificada | 598 | 166 / 166 | sim | 358 | 210 | 0,6× | 242 |

  Com polígono simples + igualdade, o nativo com índice composto fica ≈ 2×
  mais barato no servidor (1,9–2,4×) em geocercas de até 60 km e 1,3× a
  600 km. Com 598 vértices a ordem se inverte: o Search leva 0,6× o tempo do
  nativo. Na parede, a rede domina e os dois empatam (diferença ≤ 4% nas
  geocercas de até 60 km). A relevância (`should: text`, um por terminal,
  top 5) custa de +12 a +65 ms no servidor sobre o Search sem texto: é
  trabalho que o nativo não faz, por isso fica fora da comparação. O
  endpoint mede um explain por motor a cada clique e a tela tira a conclusão
  da razão medida, sem frase fixa.

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
- Cada clique custa 6 agregações + 2 explains (+ 1 agregação e 1 explain com termo) (≈ 3–5 s de parede a partir
  de um notebook com RTT ≈ 320 ms).
