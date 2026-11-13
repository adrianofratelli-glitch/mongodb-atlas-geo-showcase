# Mapa do código — mongodb-atlas-geo-showcase

> Também conhecida como: Geo (id `geo` no catálogo do Portal, `pov-portfolio/povs.json`, desde 2026-11-13). Portas: frontend 5184 / backend 8184. Em uma frase: mostra, contra um cluster Atlas real, o que o MongoDB faz com dados geográficos (índices 2dsphere, `$geoWithin`/`$near`/`$geoNear`, `$setWindowFields` para "viagem impossível" e `$search` com geo), com o cálculo rodando no banco.

Detalhes das queries: [briefing/queries.md](briefing/queries.md). Telas: [briefing/ui-flows.md](briefing/ui-flows.md). Arquitetura: [briefing/architecture.md](briefing/architecture.md). Este mapa só aponta onde o código está.

## 1. Árvore anotada

```
backend/                      API FastAPI (porta 8184)
  main.py                     app, middlewares, /, /health/live, /health/ready, /preflight
  database.py                 MongoClient único (appname "mongodb-atlas-feature-showcase") e readiness()
  settings.py                 lê backend/.env (MONGO_URI, MONGO_DB, origens permitidas, token opcional...)
  security.py                 middlewares: bloqueia mutação remota/CSRF e põe cabeçalhos de segurança
  routers/geo.py              TODAS as rotas /geo/* e todas as queries MongoDB (~1.020 linhas; abrir aqui primeiro)
  data/municipios.json        lista de municípios usada pelo seed
  data/fraud_seeds.json       clientes "plantados" (fallback; a API lê primeiro geo.demo_metadata)
  tests/test_geo.py           45 testes com Mongo simulado
  tests_live/test_live_geo.py 6 testes contra banco *_test real (só com GEO_LIVE=1)
frontend/                     React + Vite (porta 5184; proxy /api -> 8184, sem o prefixo /api: vite.config.js)
  src/App.jsx                 casca: cabeçalho, pill de preflight (GET /api/preflight), toasts de erro
  src/pages/Geo.jsx           a tela: seção 01 (viagem impossível), seção 02 (operadores geo), monta a seção 03
  src/hooks/useApi.js         fetch com timeout, aborto e eventos (api-query-executed, api-error)
  src/components/ComparacaoOperadores.jsx   cartões dos 5 operadores
  src/components/ComparacaoRotas.jsx        $geoWithin x $geoIntersects com 3 rotas LineString (GET /geo/rotas-comparar)
  src/components/MapaConsulta.jsx, MapaBrasil.jsx, geoMapMath.mjs   mapas (SVG local ou Google Maps) e a matemática de projeção
  src/components/PainelIndiceBusca.jsx      seção 03: explain de dois índices e busca $search (texto + near + raio + facetas)
  src/components/QueryBlock.jsx             bloco "ver query executada"
  src/components/Limites.jsx                caixa "escopo desta demonstração"
  src/data/brasil-uf.js       contornos das UFs para o mapa local
  src/pov-signature.css       estilo de marca (copiado de _shared/ui; não editar à mão)
  tests/geo-map.test.mjs      teste da matemática do mapa
scripts/
  seed_geo.py                 gera 150 mil transações, cria índices, grava o manifesto em demo_metadata
  create_search_index_geo.sh  cria/atualiza o Atlas Search index (via mongosh; GEO_DB do ambiente vence o .env)
  bench_geo.py                latência por fluxo: parede p50/p95 e tempo no servidor (explain); só leitura
docs/                         briefing/, setup-geo.md, screenshots/
pyproject.toml                config do pytest (testpaths backend/tests) e do ruff
```

`start.sh` (raiz) sobe backend :8184 e frontend :5184 em primeiro plano e derruba a árvore no SIGTERM: é o launcher do Portal. `POV_BACKEND_PORT`/`POV_FRONTEND_PORT` trocam as portas (instância de teste do Portal). Sem Makefile; passos à mão no README, "Commands".

## 2. "Apertei o botão X, o que roda?"

Todo fetch do front passa por `useApi().call` (`frontend/src/hooks/useApi.js`); o prefixo `/api` é removido pelo proxy do Vite. Todas as rotas vivem em `backend/routers/geo.py`, exceto `/preflight` (`backend/main.py:75`).

| Tela / botão | Componente (arquivo:linha) | Chamada HTTP | Handler | Função de negócio | Onde toca o MongoDB |
|---|---|---|---|---|---|
| Abrir a página: pill "pronto/não pronto" | `App.jsx:67` (fetch direto) | `GET /preflight` | `main.py:75` `preflight` | `database.py::readiness` + `geo.py::preflight_checks` (:223) | `ping`; `estimated_document_count` em `geo.transacoes`; `list_search_indexes` |
| Abrir a página: status do dataset (lista de clientes plantados, índices) | `Geo.jsx:51` | `GET /geo/status` | `geo.py:294` `status` | `geo.py::status`, `_manifesto` (:98, cache) | `estimated_document_count`, `index_information` em `transacoes`; `find_one` em `demo_metadata` (fallback `backend/data/fraud_seeds.json`) |
| Abrir a página: lista de municípios (select de centro) | `Geo.jsx:52` | `GET /geo/municipios` | `geo.py:327` `municipios` | `geo.py::_municipios` (:202, cache em memória) | `aggregate` `$group` por município/UF em `transacoes` |
| 01 · "Varrer a coleção inteira" | `Geo.jsx:174` -> `rodarViagens()` (:77) | `GET /geo/impossible-travel?limiteKmh=` | `geo.py:385` `impossible_travel` | `geo.py::impossible_travel` + `_haversine_stages` (:62) + `_gabarito` (:620) | `aggregate` `$setWindowFields`/`$shift` + `$facet`, `allowDiskUse` (`geo.py:519`) em `transacoes` |
| 01 · "Só este cliente" (select "recorte por cliente") | `Geo.jsx:185` -> `rodarViagens(clienteFiltro)` | `GET /geo/impossible-travel?limiteKmh=&clienteId=` | idem | idem (com `$match` de `clienteId` antes da janela) | idem |
| 01 · select de limite km/h | `Geo.jsx:169` | nenhuma até clicar em um botão acima | n/a | n/a | n/a |
| 01 · clicar numa linha da tabela / mini mapa | `Geo.jsx:274` (`setViagemSel`), `MiniMapa` `Geo.jsx:301` | nenhuma (usa o resultado já recebido) | n/a | n/a | n/a |
| 02 · select de município (centro) e de raio | `Geo.jsx:377-382` -> estado `centroIdx`, `raioOperadores` | dispara o efeito abaixo | n/a | n/a | n/a |
| 02 · carga automática ao mudar centro/raio (debounce 250 ms) e botão "rodar" (`rodarOperadores`) | `Geo.jsx:58-70`, botão `Geo.jsx:386` | `POST /geo/operadores` | `geo.py:754` `operadores_geo` | `geo.py::operadores_geo`, `_poligono_quadrado` (:644), `_geo_near_resultado` (:693) | `count_documents` + `find` com `$geoWithin`, `$geoIntersects`, `$near`, `$nearSphere` em `transacoes`; `aggregate` `$geoNear` com `key: "local"` em `transacoes` |
| 02 · abas `$geoWithin`/`$geoIntersects` x `$near`/`$nearSphere` | `Geo.jsx:365-368` e `ComparacaoOperadores.jsx:40` | nenhuma | n/a | n/a | n/a |
| 02 · "Rotas · LineString" (e "Executar novamente no Atlas") | `Geo.jsx:396`, `ComparacaoRotas.jsx:12-15` e botão `:41` | `GET /geo/rotas-comparar?lng=&lat=&raioKm=` | `geo.py:825` `comparar_rotas` | `geo.py::comparar_rotas` | `db.aggregate` com `$documents` + `$facet` (`geo.py:851`), sem coleção |
| 02 · "Terminais · Point" | `Geo.jsx:397` | nenhuma (mostra o resultado de `/geo/operadores`) | n/a | n/a | n/a |
| 03 · "Comparar planos" (selects cliente/raio, centro próprio) | `PainelIndiceBusca.jsx:31` | `POST /geo/explain-compare` | `geo.py:340` `explain_compare` | `geo.py::explain_compare`, `_explain_find` (:182), `_resumo_plano` (:141) | `command` `explain` (`executionStats`) de `find` com `hint` nos dois índices, em `transacoes` |
| 03 · "Buscar" (selects termo/raio) | `PainelIndiceBusca.jsx:50` | `POST /geo/search` | `geo.py:903` `geo_search` | `geo.py::geo_search` | `aggregate` `$search` (:1014) e `$searchMeta` (:1015) em `transacoes` |
| "Ver query executada" / "Ver pipeline completo" | `QueryBlock.jsx`, `App.jsx:126`, `Geo.jsx:348,438`, `PainelIndiceBusca.jsx:136` | nenhuma (texto vem da resposta) | n/a | n/a | n/a |

Rotas que existem na API mas **não têm botão na UI** (conferido: nenhum `call` para elas em `frontend/src`):

| Rota | Handler | Função / o que faz | Mongo |
|---|---|---|---|
| `GET /geo/sinais-ao-vivo` | `geo.py:245` | `sinais_ao_vivo`: lê sinais já calculados por um processor externo | `find`+`sort`+`limit`, 2x `count_documents` em `sinais_ao_vivo` |
| `GET /health/live`, `/health/ready`, `/` | `main.py:59-72` | saúde | `ping` (ready) |

## 3. Onde estão as queries MongoDB

Textos completos dos pipelines: [briefing/queries.md](briefing/queries.md) (os números de linha de `geo.py` citados lá estão desatualizados; use os daqui).

| O que faz | arquivo::função (linha) | Operador / pipeline principal | Collection |
|---|---|---|---|
| Municípios do dataset | `backend/routers/geo.py::_municipios` (:202-220) | `$group` + `$sort` + `$project`, `allowDiskUse` | `transacoes` |
| Contagem para preflight/status | `geo.py::preflight_checks` (:223), `status` (:294) | `estimated_document_count` | `transacoes` |
| Índices existentes | `geo.py::status` (:294) | `index_information` | `transacoes` |
| Search index existe? | `geo.py::_search_disponivel` (:192-200) | `list_search_indexes` | `transacoes` |
| Explain com hint | `geo.py::_explain_find` (:182-189) e `explain_compare` (:340) | comando `explain` (`executionStats`) de `find` com `$geoWithin` + `$centerSphere` | `transacoes` |
| Viagem impossível | `geo.py::impossible_travel` (:385; `aggregate` :519) | `$setWindowFields` + `$shift`, haversine em MQL (`_haversine_stages` :62), `$facet` com ramos `avaliados`/`sinais`/`total_sinais`/`clientes_sinalizados` (`$addToSet`, gabarito)/`aprovados` (`$sample`) | `transacoes` |
| Operadores geo (find) | `geo.py::operadores_geo` (:754; filtros :771-774; `count_documents`/`find` :785-817) | `$geoWithin`, `$geoIntersects` (`$geometry` Polygon), `$near`, `$nearSphere` | `transacoes` |
| `$geoNear` | `geo.py::_geo_near_resultado` (:693; `aggregate` :727) | `$geoNear` com `key: "local"` + `$facet` (amostra por terminal e total); degrada o card se o servidor recusar | `transacoes` |
| Rotas sintéticas | `geo.py::comparar_rotas` (:825) | `$documents` + `$facet` com `$geoWithin` e `$geoIntersects` em `$match`, `maxTimeMS` | nenhuma (documentos em memória) |
| Busca textual + geo | `geo.py::geo_search` (:903; execução :1014-1015) | `$search` `compound` (`text` fuzzy ou `exists`; `should: near` com termo; `geoWithin` circular + `in` categoria), `$searchMeta` `facet` | `transacoes` (index `idx_geo_estabelecimento`) |
| Âncora da contestação | `geo.py::_ancora_da_contestacao` (:884) | `find_one` por `endToEndId` | `transacoes` |
| Manifesto de plantados | `geo.py::_manifesto` (:98) | `find_one({_id: "geo_seed"})`, fallback arquivo | `demo_metadata` |
| Sinais ao vivo | `geo.py::sinais_ao_vivo` (:245; `find` :260; counts :264-265) | `find` sem o campo `pontos`, ordenado por `detectadoEm` desc | `sinais_ao_vivo` |
| Preflight | `backend/database.py::readiness` (:19) | `admin.command("ping")` | n/a |
| Criar índices | `scripts/seed_geo.py::criar_indices` (:261-280) | `create_index`: `e2e_unq_idx` (único), `cliente_status_local_idx`, `local_2dsphere_idx`, `cliente_ts_idx`, `uf_ts_idx`, `categoria_local_idx` | `transacoes` |
| Carga do dataset | `scripts/seed_geo.py::main` (`insert_many` :500; `drop` :482-486; guarda `assert_writable_db` :397) | `insert_many(ordered=False)` em lotes de 5.000 | `transacoes` |
| Registro da versão do dataset | `scripts/seed_geo.py::registrar_dataset` (:302, grava `clientesPlantados`), `verificar_prontidao` (:330), `dataset_atual` (:364) | `replace_one(upsert)` / leituras de conferência | `demo_metadata`, `transacoes` |
| Search index | `scripts/create_search_index_geo.sh` (`updateSearchIndex` :89, `createSearchIndex` :93) | definição `idx_geo_estabelecimento` (string pt, token+facet, geo) | `transacoes` |

Armadilha registrada no código: `transacoes` tem três índices 2dsphere em `local`; `$geoNear` só roda com `key: "local"` (comentário em `geo.py:49-53`, ADR 0001). A antiga cópia `transacoes_geonear` foi aposentada.

## 4. Compartilhado × só desta PoV

- **`_shared`**: nenhum import em código Python/JS. A única ligação é visual: `frontend/src/pov-signature.css` é cópia mantida por `_shared/ui/pov-signature.css` via `_shared/ui/sync-ui.sh` (fonte: `CLAUDE.md` deste repo, linha 95); não editar à mão.
- **Variáveis de ambiente** (`backend/.env`, modelo `backend/.env.example`; `frontend/.env.example`):
  - Conexão: `MONGO_URI` (cluster; vem do ambiente comum), `MONGO_DB` (padrão `POC`; **não é** o banco do Geo), `MONGO_TIMEOUT_MS` — `backend/settings.py`.
  - Locais do módulo Geo: `GEO_DB` (padrão `geo`) e `GEO_SEARCH_INDEX` (padrão `idx_geo_estabelecimento`) — lidos em `geo.py:33-35` e no seed/script (a variável de ambiente vence o `.env` nos dois scripts).
  - Segurança/operação: `DEMO_ADMIN_TOKEN`, `ALLOWED_ORIGINS`, `MAX_REQUEST_BYTES`; front: `VITE_DEMO_API_TOKEN`, `VITE_API_PROXY_TARGET`.
  - `ATLAS_PUBLIC_KEY/PRIVATE_KEY/PROJECT_ID/CLUSTER`: lidas em `settings.py`, sem uso no restante do código (conferido).
  - Não confirmei no repositório quais vêm do `.env.shared`/`sync_env`.
- **Bancos/coleções**: banco `geo` com `transacoes` e `demo_metadata` (criados pelo seed, exclusivos desta PoV). `sinais_ao_vivo` é lida pela rota `/geo/sinais-ao-vivo` mas **não é escrita neste repo**: a docstring de `geo.py::sinais_ao_vivo` atribui a leitura ao processor `geoSinais30s` do repositório de origem. Não existe aqui.
- **Chamadas externas**: apenas o MongoDB Atlas (pymongo) e `mongosh` no script do search index. Opcionalmente o SDK do Google Maps no navegador (`frontend/src/components/MapaBrasil.jsx`, `carregarSdk` :294). Sem LLM, Voyage ou Langfuse.

## 5. "Quero mexer em..."

- Texto/títulos da tela -> `frontend/src/pages/Geo.jsx` (seções 01 e 02), `frontend/src/components/PainelIndiceBusca.jsx` (seção 03) e `App.jsx` (cabeçalho).
- A regra de viagem impossível (limite, corte, saída) -> `backend/routers/geo.py::impossible_travel` (:385); fórmula de distância em `_haversine_stages` (:62); gabarito em `_gabarito` (:620).
- Opções do select de km/h -> `LIMITES_KMH` em `frontend/src/pages/Geo.jsx`.
- Operadores comparados (filtros e `$geoNear`) -> `geo.py::operadores_geo` (:754) e `_geo_near_resultado` (:693).
- Rotas de exemplo (coordenadas) -> `geo.py::comparar_rotas` (:825).
- Adicionar rota -> `geo.py` (decorator `@router`) + chamada com `call('/geo/...')` na página.
- Busca e explain da seção 03 -> `frontend/src/components/PainelIndiceBusca.jsx` (termos e raios nas constantes do topo) e `geo.py::geo_search` (:903, corpo em `SearchRequest` :869).
- Índices -> `scripts/seed_geo.py::criar_indices` (:261); depois `python scripts/seed_geo.py --ensure`/`--drop`.
- Quantidade de dados/clientes/fraudes plantadas -> `scripts/seed_geo.py` (`--clientes`, `--por-cliente`, `--fraudes`, :424-426); gerador em `gerar` (:145).
- Definição do Atlas Search index -> `scripts/create_search_index_geo.sh` (bloco `definicao`).
- Porta -> `frontend/vite.config.js` (5184 e alvo 8184), `uvicorn ... --port 8184` (README) e `ALLOWED_ORIGINS` padrão em `backend/settings.py`.
- Segurança de mutações -> `backend/security.py::MutationGuardMiddleware` (:28). (Hoje não há rota de escrita em `/geo`; o guard protege POST/DELETE em geral, e os POSTs de leitura passam por ele.)

## 6. Testes

- `backend/tests/test_geo.py` (45 testes, Mongo simulado, sem cluster): manifesto (banco antes do arquivo), gabarito do gerador, `$geoNear` com `key` e degradação do card, `near` como `should` no `$search`; resumo de plano do `explain`, `explain_compare` com os dois hints, monta `$setWindowFields`+haversine em um único estágio, corte geométrico, seletividade (pares avaliados/alertas por dia), `$search` (degrada sem índice, geoWithin em metros, âncora, sem termo ordena por distância), `$geoNear` amostrando terminais, rotas via `$documents`, determinismo do seed, `dataset_atual`, preflight somente leitura.
- `backend/tests_live/test_live_geo.py` (6 testes, só com `GEO_LIVE=1` e `GEO_DB=*_test`): IXSCAN e chaves do composto ≪ puro, `$geoNear` = círculo `$centerSphere`, 40/40 plantados a 900 km/h, recorte de 74 pares, raio e facetas do `$search`, rotas A vs A+B.
- `scripts/bench_geo.py`: latência (parede p50/p95 e servidor via explain); números no README, "Measured latency".
- `frontend/tests/geo-map.test.mjs`: matemática de projeção/mapa.
- `backend/tests/test_start_sh.py` (4 testes): contrato do `start.sh` com o Portal (bash válido, portas padrão 8184/5184, limpeza armada antes dos filhos, `wait` em primeiro plano, preview na porta do launcher).
- Comandos (README, "Commands"), na raiz: `pytest` (usa `pyproject.toml`, `testpaths = backend/tests`); `ruff check backend`; `cd frontend && node --test tests/*.test.mjs`. Antes da demo: `curl http://localhost:8184/preflight`.
