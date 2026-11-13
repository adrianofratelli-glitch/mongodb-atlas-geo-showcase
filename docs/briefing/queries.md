# Queries, pipelines e índices — MongoDB Atlas Geo Showcase

> Números de linha podem ficar defasados após mudanças: a fonte atualizada é [MAPA_DO_CODIGO.md](../MAPA_DO_CODIGO.md).

Mapa completo de "onde está a query X" para responder rápido ao gestor.
Tudo abaixo foi extraído do código real (`backend/routers/geo.py`,
`scripts/seed_geo.py`, `scripts/create_search_index_geo.sh`). Nenhum exemplo
usa dado real do cluster — coordenadas e IDs são ilustrativos.

Banco: `geo` (`GEO_DB`). Coleções: `transacoes` (principal) e
`demo_metadata` (identidade do dataset e clientes plantados). A antiga cópia
`transacoes_geonear` foi aposentada (ADR 0001).

---

## Índices

Criados por `criar_indices()` em `scripts/seed_geo.py:258-277`, todos com
nome explícito (a lista completa que `/geo/status` também expõe):

| Nome | Campos | Tipo | Por que existe |
|---|---|---|---|
| `e2e_unq_idx` | `endToEndId` asc | único | Idempotência do seed — reexecutar não duplica transação. |
| `cliente_status_local_idx` | `clienteId` asc, `status` asc, `local` **2dsphere** | composto (Demo A) | Compara plano de execução com `local_2dsphere_idx` sob o mesmo filtro de `$geoWithin`. Igualdade primeiro, geo por último — o campo geo **não** precisa ser prefixo do índice para `$geoWithin`/`$geoIntersects` (nota didática do código, `geo.py:330-337`). |
| `local_2dsphere_idx` | `local` **2dsphere** | geo puro (Demo A) | Outro lado do comparativo de explain — mede se o índice composto ou o puro examina menos chaves para o mesmo filtro. |
| `cliente_ts_idx` | `clienteId` asc, `ts` asc | composto | Sustenta o `$setWindowFields` particionado por cliente e ordenado por `ts` no painel de investigação (Demo B). |
| `uf_ts_idx` | `uf` asc, `ts` desc | composto | Suporte a consultas por UF/tempo (não exercitado diretamente pelos endpoints atuais, mas mantido como índice de suporte geral). |
| `categoria_local_idx` | `estabelecimento.categoria` asc, `local` **2dsphere** | composto | Suporte a filtro por categoria combinado com geo (usado no painel de busca, `POST /geo/search`, categoria como faceta/filtro). |

Três índices 2dsphere em `local` convivem de propósito. `$geoNear` só os
aceita com `key: "local"`; sem `key`, o servidor recusa ("more than one
2dsphere index"). Com `key`, o planner usa `local_2dsphere_idx` (medido no
9.0.7; ver `docs/adr/0001-geonear-na-colecao-principal-com-key.md`).

**Armadilha registrada**: círculo (`$near`/`$nearSphere`/`$geoNear`, via
`$maxDistance` esférico) e quadrado (`$geoWithin`/`$geoIntersects`, via
`$geometry` Polygon) sobre o **mesmo raio** retornam contagens diferentes por
design — círculo inscrito no quadrado cobre menos área. Medido em 2M
documentos, raio 2000km: 128.364 (quadrado) vs 119.152 (círculo) — geometria,
não bug.

**Atlas Search index** (`idx_geo_estabelecimento`, criado/atualizado por
`scripts/create_search_index_geo.sh`, dinâmico `false`):

```js
{
  mappings: {
    dynamic: false,
    fields: {
      estabelecimento: {
        type: 'document',
        fields: {
          nome: { type: 'string', analyzer: 'lucene.portuguese' },
          categoria: [{ type: 'token' }, { type: 'stringFacet' }]
        }
      },
      uf: [{ type: 'token' }, { type: 'stringFacet' }],
      local: { type: 'geo' }
    }
  }
}
```
Script é idempotente: compara definição canonicalizada (chaves ordenadas) e
só chama `updateSearchIndex` se divergir; espera `READY` + `queryable` com
timeout configurável (`GEO_SEARCH_READY_TIMEOUT_SECONDS`, padrão 600s).

---

## Demo A — `POST /geo/explain-compare`

**Onde**: `backend/routers/geo.py:319-368` (modelo `ExplainRequest`, função
`explain_compare`), helpers `_explain_find` (linha 149) e `_resumo_plano`
(linha 117).

**O que faz**: roda o **mesmo** filtro `$geoWithin` duas vezes, forçando um
índice diferente via `hint` em cada chamada (`explain()` com
`verbosity: executionStats`), e devolve lado a lado `nReturned`,
`totalKeysExamined`, `totalDocsExamined`, `executionTimeMillis` e estágio
vencedor (IXSCAN vs COLLSCAN) de cada plano.

```js
db.transacoes.find({
  clienteId: "<id>",
  status: "APROVADA",
  local: { $geoWithin: { $centerSphere: [[lng, lat], raioKm / 6371.0088] } }
}).hint("cliente_status_local_idx").explain("executionStats")

// e a mesma query com .hint("local_2dsphere_idx")
```

A resposta traz `comando` em cada plano (o explain com o `hint` real,
montado por `geo.py::_comando_explain`) e `query` com os dois juntos; é isso
que o painel 03 mostra em "Comandos executados".

**Por que existe**: prova, com número medido (não narrativa), que o índice
2dsphere está sendo usado (IXSCAN, não COLLSCAN) e compara custo entre um
índice composto (igualdade + geo) e um geo puro. O código deixa explícito
que a divergência medida é o que vale — se em algum cenário o 2dsphere puro
examinar menos chaves que o composto, isso é reportado como está, sem ajuste
de texto para caber numa narrativa esperada.

---

## Demo B — `GET /geo/impossible-travel`

**Onde**: `backend/routers/geo.py:371-594`. Helper de haversine em
`_haversine_stages` (linha 61-94).

**O que faz**: para cada cliente, ordena as transações por `ts`, usa
`$setWindowFields` + `$shift` para trazer a transação anterior na mesma
janela, calcula a distância haversine (em MQL puro, sem `$function`) entre
os dois pontos e a velocidade implícita (km/h). Um `$facet` com dois ramos
roda sobre o mesmo `$setWindowFields` (calculado uma única vez):

```js
db.transacoes.aggregate([
  // opcional: { $match: { clienteId: "<id>" } }
  { $setWindowFields: {
      partitionBy: "$clienteId",
      sortBy: { ts: 1 },
      output: {
        ts_ant:    { $shift: { output: "$ts", by: -1 } },
        coord_ant: { $shift: { output: "$local.coordinates", by: -1 } },
        // ... municipio_ant, uf_ant, dispositivo_ant, localizacao_meta_ant
      }
  }},
  { $match: { ts_ant: { $ne: null } } },      // descarta 1ª transação de cada cliente
  { $addFields: { minutos: { $divide: [{ $subtract: ["$ts", "$ts_ant"] }, 60000] } } },
  { $facet: {
      avaliados: [{ $count: "pares" }],
      sinais: [
        // corte geométrico: nenhum par na Terra dista mais que meia
        // circunferência, então descarta intervalos longos demais para violar
        // o limite ANTES do haversine (a parte cara)
        { $match: { minutos: { $gt: 0, $lt: /* π·R/limiteKmh em minutos */ 1234 } } },
        // haversine em $let aninhado (ver abaixo)
        { $addFields: { kmh: { $divide: ["$km", { $divide: ["$minutos", 60] }] } } },
        { $match: { kmh: { $gt: 900 /* limiteKmh */ } } },
        { $sort: { kmh: -1 } },
        { $limit: 50 },
        { $project: { /* clienteId, endToEndId, km, minutos, kmh, de, para, ts_ant, ts */ } }
      ],
      total_sinais: [ /* mesmos estágios até antes do $sort */, { $count: "total" } ],
      // gabarito do gerador: clientes sinalizados, sem o corte da tabela
      clientes_sinalizados: [ /* mesmos estágios até antes do $sort */, { $group: { _id: null, ids: { $addToSet: "$clienteId" } } } ],
      aprovados: [
        { $match: { minutos: { $gt: 0 } } },
        { $sample: { size: 200 } },
        // haversine + kmh + filtro <= limite + sort por ts + limit + project
      ]
  }}
], { allowDiskUse: true })
```

Haversine em MQL puro (`_haversine_stages`, linhas 61-94) — um único
`$addFields` com `$let` aninhado, porque a versão em 4 stages encadeadas
custava 4 passadas completas sobre o resultado da janela (medido em
`executionStats`, era a maior fatia do tempo do pipeline):

```js
{ $addFields: { km: { $let: {
  vars: {
    phi1: { $degreesToRadians: "$lat1" },
    phi2: { $degreesToRadians: "$lat2" },
    dphi: { $degreesToRadians: { $subtract: ["$lat2", "$lat1"] } },
    dlmb: { $degreesToRadians: { $subtract: ["$lng2", "$lng1"] } }
  },
  in: { $let: {
    vars: { a: { $add: [
      { $pow: [{ $sin: { $divide: ["$$dphi", 2] } }, 2] },
      { $multiply: [
        { $cos: "$$phi1" }, { $cos: "$$phi2" },
        { $pow: [{ $sin: { $divide: ["$$dlmb", 2] } }, 2] }
      ]}
    ]}},
    // $min contra 1 protege $asin de erro de arredondamento em pares quase antipodais
    in: { $multiply: [2 * 6371.0088, { $asin: { $sqrt: { $min: ["$$a", 1] } } }] }
  }}
}}}}
```

**Por que existe**: investigação retrospectiva de "viagem impossível" —
duas compras presenciais do mesmo cliente distantes demais para o tempo
entre elas — inteiramente no cluster, sem trazer histórico para a aplicação.
Índice de suporte: `cliente_ts_idx`. `$facet` evita rodar o
`$setWindowFields` (caro) duas vezes. O ramo `clientes_sinalizados` alimenta
`gabarito_sintetico` (`geo.py::_gabarito`): plantados encontrados / plantados
e emergentes. É cobertura do gerador, não precisão/recall de fraude. Seletividade (pares avaliados,
sinalizados, taxa%, alertas/dia) é contada **antes** do corte geométrico —
resposta à pergunta real de um time de risco ("de quantas oportunidades"),
não só "quantos sinais saíram". Isto é sinal de risco, **nunca** decisão de
fraude — não há rótulo de fraude confirmada no dataset.

---

## Demo B2 — `POST /geo/operadores`

**Onde**: `backend/routers/geo.py:633-766`. Geometria auxiliar em
`_poligono_quadrado`, `$geoNear` isolado em `geo.py::_geo_near_resultado`.

**O que faz**: roda os 5 operadores/estágios geoespaciais do MongoDB lado a
lado sobre a mesma geometria (quadrado para área, ponto para proximidade):

```js
// $geoWithin — inteiramente dentro da geometria
db.transacoes.find({ local: { $geoWithin: { $geometry: <Polygon> } } })

// $geoIntersects — geometria cruza a geometria informada
db.transacoes.find({ local: { $geoIntersects: { $geometry: <Polygon> } } })

// $near — find(), ordena por proximidade, exige índice geo, sem distância no resultado
db.transacoes.find({ local: { $near: { $geometry: <Point>, $maxDistance: raioKm*1000 } } })

// $nearSphere — mesma ordenação, sempre esférica
db.transacoes.find({ local: { $nearSphere: { $geometry: <Point>, $maxDistance: raioKm*1000 } } })

// $geoNear — estágio de agregação, primeiro estágio obrigatório, devolve distância
db.transacoes.aggregate([
  { $geoNear: { near: <Point>, key: "local", distanceField: "distanciaMetros", maxDistance: raioKm*1000, spherical: true } },
  { $facet: {
      amostra: [
        { $group: { _id: "$dispositivo.id", documento: { $first: "$$ROOT" } } },
        { $replaceWith: "$documento" },
        { $sort: { distanciaMetros: 1, "dispositivo.id": 1 } },
        { $limit: 5 },
        { $project: { _id: 0, endToEndId: 1, municipio: 1, uf: 1, local: 1, "dispositivo.id": 1, distanciaMetros: { $round: ["$distanciaMetros", 0] } } }
      ],
      total: [{ $count: "n" }]
  }}
])
```

**Por que existe**: comparação didática lado a lado — quando usar cada
operador. `$near`/`$nearSphere` são operadores de `find()` e não funcionam
dentro de `$match` de um pipeline de agregação (restrição real do MongoDB),
por isso não têm `count_documents`. `$geoNear` resolve essa lacuna (roda em
pipeline, devolve distância), mas precisa ser o primeiro estágio e, com mais
de um índice 2dsphere no campo, precisa de `key`. Se o servidor recusar, o
card do `$geoNear` mostra o erro e os outros quatro continuam.
`$geoIntersects` sobre dado tipo `Point` coincide com `$geoWithin` neste
dataset — a diferença só apareceria com `LineString`/`Polygon` armazenados
(exercitado à parte no endpoint de rotas, abaixo).

---

## `GET /geo/rotas-comparar`

**Onde**: `backend/routers/geo.py:769-811`.

**O que faz**: gera 3 rotas sintéticas (`LineString`) sem persistir no
banco, injeta via `$documents` e classifica cada uma com `$geoWithin` e
`$geoIntersects` sobre a mesma área:

```js
db.aggregate([
  { $documents: [
      { id: "A", nome: "Percurso local", local: { type: "LineString", coordinates: [...] } },
      { id: "B", nome: "Travessia regional", local: { type: "LineString", coordinates: [...] } },
      { id: "C", nome: "Ligação distante", local: { type: "LineString", coordinates: [...] } }
  ]},
  { $facet: {
      geoWithin:     [{ $match: { local: { $geoWithin:     { $geometry: <Polygon> } } } }, { $project: { _id: 0, id: 1 } }],
      geoIntersects: [{ $match: { local: { $geoIntersects: { $geometry: <Polygon> } } } }, { $project: { _id: 0, id: 1 } }]
  }}
], { maxTimeMS: 10000 })
```

**Por que existe**: mostra a diferença real entre `$geoWithin` (toda a
geometria precisa estar contida) e `$geoIntersects` (basta cruzar) usando
`LineString`, já que sobre `Point` os dois operadores coincidem. `$documents`
evita precisar persistir rotas de exemplo no banco.

---

## `POST /geo/search`

**Onde**: `backend/routers/geo.py:814-970`. Âncora da investigação em
`_ancora_da_contestacao` (linha 804-819).

**O que faz** (painel 03, bloco B): um único `$search` combinando relevância
textual (fuzzy, `lucene.portuguese`), proximidade (`near` como `should`, só
com termo), filtro geoespacial (`geoWithin` circular) e filtro de categoria —
mais `$searchMeta` para facetas por categoria/UF:

```js
db.transacoes.aggregate([
  { $search: {
      index: "idx_geo_estabelecimento",
      compound: {
        must: [
          // com termo: fuzzy text search
          { text: { query: "<termo>", path: "estabelecimento.nome", fuzzy: { maxEdits: 1 } } }
          // sem termo: só exige que o campo exista (compound precisa de ≥1 cláusula pontuável)
          // { exists: { path: "estabelecimento.nome" } }
        ],
        // só com termo: nomes iguais empatam no texto; near desempata por proximidade
        should: [
          { near: { path: "local", origin: { type: "Point", coordinates: [lng, lat] }, pivot: raioKm * 500 } }
        ],
        filter: [
          { geoWithin: { path: "local", circle: { center: { type: "Point", coordinates: [lng, lat] }, radius: raioKm * 1000 } } }
          // opcional: { in: { path: "estabelecimento.categoria", value: [...] } }
        ]
      },
      highlight: { path: "estabelecimento.nome" }
  }},
  { $addFields: { score: { $meta: "searchScore" }, highlights: { $meta: "searchHighlights" } } },
  // + haversine (km_do_centro) para validar o raio sem confiar no $search
  { $sort: { score: -1, endToEndId: 1 } },        // ou { km_do_centro: 1, endToEndId: 1 } sem termo
  { $group: { _id: "$dispositivo.id", documento: { $first: "$$ROOT" } } },  // dedup por terminal
  { $replaceWith: "$documento" },
  { $sort: { score: -1 } },                        // ou { km_do_centro: 1 } sem termo
  { $limit: 20 },
  { $project: { /* endToEndId, terminalId, estabelecimento, municipio, uf, valor, local, score, highlights, km_do_centro */ } }
])

// e em paralelo, para as facetas:
db.transacoes.aggregate([
  { $searchMeta: {
      index: "idx_geo_estabelecimento",
      facet: {
        operator: { compound: { /* mesmo compound acima */ } },
        facets: {
          categoria: { type: "string", path: "estabelecimento.categoria" },
          uf:        { type: "string", path: "uf" }
        }
      }
  }}
])
```

**Por que existe**: mostra que `geoWithin` é operador de primeira classe
dentro de `$search` — diferente de `$vectorSearch`, cujo `filter` **rejeita**
operadores geoespaciais (armadilha documentada no README). O centro pode vir
de uma coordenada livre ou da âncora de uma "compra contestada" real
(`endToEndId`), transformando a busca de catálogo em investigação com ponto
de partida. Deduplicação por terminal (`$group` + `$replaceWith`) evita que
20 compras da mesma maquininha ocupem 20 posições no resultado — a pergunta
é "quais estabelecimentos existem aqui", não "quais transações".

---

## `POST /geo/geocerca-comparar`

**Onde**: `backend/routers/geo.py::geocerca_comparar` (ADR 0003). Polígono em
`_poligono_geocerca` (heptágono irregular sintético, anel fechado
anti-horário); `densificar: true` passa por `_densificar_anel` (vértice a
cada 0,05°).

**O que faz** (painel 04): a mesma pergunta — terminais de uma categoria
dentro da geocerca, com contagem de compras — em dois motores, com o mesmo
`$group` no fim para a resposta ser comparável terminal a terminal.

Nativo (planner escolhe `categoria_local_idx`):

```js
db.transacoes.aggregate([
  { $match: {
      "estabelecimento.categoria": "<categoria>",
      local: { $geoWithin: { $geometry: { type: "Polygon", coordinates: [[ /* 7 ou ~600 vértices */ ]] } } }
  } },
  { $group: { _id: "$dispositivo.id", compras: { $sum: 1 }, nome: { $first: "$estabelecimento.nome" },
              municipio: { $first: "$municipio" }, uf: { $first: "$uf" }, local: { $first: "$local" } } },
  { $sort: { _id: 1 } }
])
```

Atlas Search (índice próprio `idx_geo_geocerca`):

```js
db.transacoes.aggregate([
  { $search: {
      index: "idx_geo_geocerca",
      compound: {
        filter: [
          { geoWithin: { path: "local", geometry: { type: "Polygon", coordinates: [[ /* o mesmo anel */ ]] } } },
          { in: { path: "estabelecimento.categoria", value: ["<categoria>"] } }
        ],
        // só com termo: soma relevância, não filtra (o conjunto continua o mesmo)
        should: [ { text: { query: "<termo>", path: "estabelecimento.nome", fuzzy: { maxEdits: 1 } } } ]
      },
      returnStoredSource: true
  } },
  { $facet: {
      terminais: [ /* o mesmo $group + $sort do nativo */ ],
      // só com termo: um por terminal, score > 0, top 5
      relevancia: [
        { $group: { _id: "$dispositivo.id", nome: { $first: "$estabelecimento.nome" },
                    municipio: { $first: "$municipio" }, score: { $max: { $meta: "searchScore" } } } },
        { $match: { score: { $gt: 0 } } }, { $sort: { score: -1, _id: 1 } }, { $limit: 5 },
        { $project: { _id: 0, terminalId: "$_id", nome: 1, municipio: 1, score: { $round: ["$score", 3] } } }
      ]
  } }
])
```

Antes do `$search`, `_estado_search_index` lê `list_search_indexes` e exige
`status: "READY"` e `queryable`; caso contrário o Search não roda (índice
ausente ou em BUILDING devolveria vazio sem erro). Cada pipeline roda
`execucoes` vezes (padrão 3, alternados) e uma vez em `explain`
(`executionStats`); `_resumo_explain_agregacao` extrai só números (o bloco
do mongot traz o host do nó). A resposta devolve os pipelines exatos que
foram executados.

**Índice** `idx_geo_geocerca` (de `scripts/create_search_index_geo.sh`):

```js
{
  mappings: { dynamic: false, fields: {
    estabelecimento: { type: "document", fields: {
      nome: { type: "string", analyzer: "lucene.portuguese" },
      categoria: { type: "token" } } },
    local: { type: "geo" } } },
  storedSource: { include: ["dispositivo.id", "estabelecimento.nome", "municipio", "uf", "local"] }
}
```

**Medido** (geo_f4_test, 2026-11-13): mesma resposta em 117 de 120 geocercas
(40 municípios × 8/60/600 km); as 3 divergentes têm 600 km (1–3 terminais só
no Search, borda reta × geodésica) e se alinham densificando. Servidor:
nativo 37–110 ms × Search 84–227 ms em polígono de 7 vértices; com ~600
vértices, nativo 380 ms × Search 238 ms.

## `GET /geo/sinais-ao-vivo` (código herdado, não chamado pelo frontend)

**Onde**: `backend/routers/geo.py:231-277`. Só `find`/`count_documents`
simples sobre `geo.sinais_ao_vivo` (populada por um stream processor que
existe apenas no repositório de origem, `geoSinais30s`). Degrada sozinho
para `estado: "indisponivel"` quando a coleção não existe. Não remover sem
checar dependência.

---

## `GET /geo/municipios`

**Onde**: `backend/routers/geo.py:176-194, 290-293`. Agregação simples,
cacheada em memória (`_municipios_cache`):

```js
db.transacoes.aggregate([
  { $group: { _id: { municipio: "$municipio", uf: "$uf" }, transacoes: { $sum: 1 }, centro: { $first: "$local.coordinates" } } },
  { $sort: { transacoes: -1 } },
  { $project: { _id: 0, municipio: "$_id.municipio", uf: "$_id.uf", transacoes: 1, centro: 1 } }
], { allowDiskUse: true })
```

**Por que existe**: popula o seletor "centro" do painel 02 com municípios
reais do dataset e um ponto representativo para centrar o mapa.

## `GET /geo/status`

**Onde**: `backend/routers/geo.py:281-310`. Usa `estimated_document_count()`
e `index_information()` — sem agregação, é metadado de coleção/índice. A
lista de clientes com par plantado vem de `geo.py::_manifesto`:
`demo_metadata.clientesPlantados` (`find_one({_id: "geo_seed"})`), com
fallback para `backend/data/fraud_seeds.json`.
