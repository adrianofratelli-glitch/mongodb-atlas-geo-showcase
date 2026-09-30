# Queries, pipelines e índices — MongoDB Atlas Geo Showcase

Mapa completo de "onde está a query X" para responder rápido ao gestor.
Tudo abaixo foi extraído do código real (`backend/routers/geo.py`,
`scripts/seed_geo.py`, `scripts/create_search_index_geo.sh`). Nenhum exemplo
usa dado real do cluster — coordenadas e IDs são ilustrativos.

Banco: `geo` (`GEO_DB`). Coleções: `transacoes` (principal),
`transacoes_geonear` (espelho só para `$geoNear`, ver arquitetura).

---

## Índices

Criados por `criar_indices()` em `scripts/seed_geo.py:258-277`, todos com
nome explícito (a lista completa que `/geo/status` também expõe):

| Nome | Campos | Tipo | Por que existe |
|---|---|---|---|
| `e2e_unq_idx` | `endToEndId` asc | único | Idempotência do seed — reexecutar não duplica transação. |
| `cliente_status_local_idx` | `clienteId` asc, `status` asc, `local` **2dsphere** | composto (Demo A) | Compara plano de execução com `local_2dsphere_idx` sob o mesmo filtro de `$geoWithin`. Igualdade primeiro, geo por último — o campo geo **não** precisa ser prefixo do índice para `$geoWithin`/`$geoIntersects` (nota didática do código, `geo.py:305-314`). |
| `local_2dsphere_idx` | `local` **2dsphere** | geo puro (Demo A) | Outro lado do comparativo de explain — mede se o índice composto ou o puro examina menos chaves para o mesmo filtro. |
| `cliente_ts_idx` | `clienteId` asc, `ts` asc | composto | Sustenta o `$setWindowFields` particionado por cliente e ordenado por `ts` no painel de investigação (Demo B). |
| `uf_ts_idx` | `uf` asc, `ts` desc | composto | Suporte a consultas por UF/tempo (não exercitado diretamente pelos endpoints atuais, mas mantido como índice de suporte geral). |
| `categoria_local_idx` | `estabelecimento.categoria` asc, `local` **2dsphere** | composto | Suporte a filtro por categoria combinado com geo (usado no painel de busca, `POST /geo/search`, categoria como faceta/filtro). |

Na coleção espelho `transacoes_geonear` (`scripts/seed_geo.py:292-302`):

| Nome | Campos | Tipo | Por que existe |
|---|---|---|---|
| `local_2dsphere_idx` | `local` **2dsphere** | único índice geo desta coleção | `$geoNear` recusa rodar quando o campo tem mais de um índice 2dsphere, e não há `hint` que resolva (testado em 3 formas, todas com `code 27 IndexNotFound`). Coleção populada via `{"$out": "transacoes_geonear"}`, mantida pelo próprio seed em `--ensure` e na geração completa. |

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

**Onde**: `backend/routers/geo.py:296-343` (modelo `ExplainRequest`, função
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

**Por que existe**: prova, com número medido (não narrativa), que o índice
2dsphere está sendo usado (IXSCAN, não COLLSCAN) e compara custo entre um
índice composto (igualdade + geo) e um geo puro. O código deixa explícito
que a divergência medida é o que vale — se em algum cenário o 2dsphere puro
examinar menos chaves que o composto, isso é reportado como está, sem ajuste
de texto para caber numa narrativa esperada.

---

## Demo B — `GET /geo/impossible-travel`

**Onde**: `backend/routers/geo.py:346-569`. Helper de haversine em
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
`$setWindowFields` (caro) duas vezes. Seletividade (pares avaliados,
sinalizados, taxa%, alertas/dia) é contada **antes** do corte geométrico —
resposta à pergunta real de um time de risco ("de quantas oportunidades"),
não só "quantos sinais saíram". Isto é sinal de risco, **nunca** decisão de
fraude — não há rótulo de fraude confirmada no dataset.

---

## Demo B2 — `POST /geo/operadores`

**Onde**: `backend/routers/geo.py:608-741`. Geometria auxiliar em
`_poligono_quadrado` (linha 572-605), `$geoNear` isolado em
`_geo_near_resultado` (linha 621-670).

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
db.transacoes_geonear.aggregate([
  { $geoNear: { near: <Point>, distanceField: "distanciaMetros", maxDistance: raioKm*1000, spherical: true } },
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
pipeline, devolve distância), mas precisa ser o primeiro estágio — por isso
roda contra `transacoes_geonear` (índice único, ver seção de índices).
`$geoIntersects` sobre dado tipo `Point` coincide com `$geoWithin` neste
dataset — a diferença só apareceria com `LineString`/`Polygon` armazenados
(exercitado à parte no endpoint de rotas, abaixo).

---

## `GET /geo/rotas-comparar`

**Onde**: `backend/routers/geo.py:744-786`.

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

**Onde**: `backend/routers/geo.py:789-945`. Âncora da investigação em
`_ancora_da_contestacao` (linha 804-819).

**O que faz**: um único `$search` combinando relevância textual (fuzzy,
`lucene.portuguese`), filtro geoespacial (`geoWithin` circular) e filtro de
categoria — mais `$searchMeta` para facetas por categoria/UF:

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

## `GET /geo/sinais-ao-vivo` (código herdado, não chamado pelo frontend)

**Onde**: `backend/routers/geo.py:209-254`. Só `find`/`count_documents`
simples sobre `geo.sinais_ao_vivo` (populada por um stream processor que
existe apenas no repositório de origem, `geoSinais30s`). Degrada sozinho
para `estado: "indisponivel"` quando a coleção não existe. Não remover sem
checar dependência.

---

## `GET /geo/municipios`

**Onde**: `backend/routers/geo.py:167-185, 290-293`. Agregação simples,
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

**Onde**: `backend/routers/geo.py:258-287`. Usa `estimated_document_count()`
e `index_information()` — sem agregação, é metadado de coleção/índice. Lê
`backend/data/fraud_seeds.json` para listar clientes com par plantado.
