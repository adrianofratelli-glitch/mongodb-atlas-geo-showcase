# Mapa do código — mongodb-atlas-geo-showcase

> Também conhecida como: Geo (PoV standalone, fora do catálogo do Portal). Portas: frontend 5184 / backend 8184. Em uma frase: mostra, contra um cluster Atlas real, o que o MongoDB faz com dados geográficos (índices 2dsphere, `$geoWithin`/`$near`/`$geoNear`, `$setWindowFields` para "viagem impossível" e `$search` com geo), com o cálculo rodando no banco.

Detalhes das queries: [briefing/queries.md](briefing/queries.md). Telas: [briefing/ui-flows.md](briefing/ui-flows.md). Arquitetura: [briefing/architecture.md](briefing/architecture.md). Este mapa só aponta onde o código está.

## 1. Árvore anotada

```
backend/                      API FastAPI (porta 8184)
  main.py                     app, middlewares, /, /health/live, /health/ready, /preflight
  database.py                 MongoClient único (appname "mongodb-atlas-feature-showcase") e readiness()
  settings.py                 lê backend/.env (MONGO_URI, MONGO_DB, origens permitidas, token opcional...)
  security.py                 middlewares: bloqueia mutação remota/CSRF e põe cabeçalhos de segurança
  routers/geo.py              TODAS as rotas /geo/* e todas as queries MongoDB (945 linhas; abrir aqui primeiro)
  data/municipios.json        lista de municípios usada pelo seed
  data/fraud_seeds.json       clientes "plantados" pelo seed (gerado por scripts/seed_geo.py; a API lê)
  tests/test_geo.py           testes com Mongo simulado
frontend/                     React + Vite (porta 5184; proxy /api -> 8184, sem o prefixo /api: vite.config.js)
  src/App.jsx                 casca: cabeçalho, pill de preflight (GET /api/preflight), toasts de erro
  src/pages/Geo.jsx           a tela inteira: seção 01 (viagem impossível) e seção 02 (operadores geo)
  src/hooks/useApi.js         fetch com timeout, aborto e eventos (api-query-executed, api-error)
  src/components/ComparacaoOperadores.jsx   cartões dos 5 operadores
  src/components/ComparacaoRotas.jsx        $geoWithin x $geoIntersects com 3 rotas LineString (GET /geo/rotas-comparar)
  src/components/MapaConsulta.jsx, MapaBrasil.jsx, geoMapMath.mjs   mapas (SVG local ou Google Maps) e a matemática de projeção
  src/components/QueryBlock.jsx             bloco "ver query executada"
  src/components/Limites.jsx                caixa "escopo desta demonstração"
  src/data/brasil-uf.js       contornos das UFs para o mapa local
  src/pov-signature.css       estilo de marca (copiado de _shared/ui; não editar à mão)
  tests/geo-map.test.mjs      teste da matemática do mapa
scripts/
  seed_geo.py                 gera 150 mil transações, cria índices, cria a coleção transacoes_geonear
  create_search_index_geo.sh  cria/atualiza o Atlas Search index (via mongosh)
docs/                         briefing/, setup-geo.md, screenshots/
pyproject.toml                config do pytest (testpaths backend/tests) e do ruff
```

Não há `start.sh` nem Makefile: sobe-se à mão (ver seção 6 e README, "Commands").

## 2. "Apertei o botão X, o que roda?"

Todo fetch do front passa por `useApi().call` (`frontend/src/hooks/useApi.js`); o prefixo `/api` é removido pelo proxy do Vite. Todas as rotas vivem em `backend/routers/geo.py`, exceto `/preflight` (`backend/main.py:75`).

| Tela / botão | Componente (arquivo:linha) | Chamada HTTP | Handler | Função de negócio | Onde toca o MongoDB |
|---|---|---|---|---|---|
| Abrir a página: pill "pronto/não pronto" | `App.jsx:67` (fetch direto) | `GET /preflight` | `main.py:75` `preflight` | `database.py::readiness` + `geo.py::preflight_checks` (:188) | `ping`; `estimated_document_count` em `geo.transacoes`; `list_search_indexes` |
| Abrir a página: status do dataset (lista de clientes plantados, índices) | `Geo.jsx:50` | `GET /geo/status` | `geo.py:258` `status` | `geo.py::status` | `estimated_document_count`, `index_information` em `transacoes`; lê `backend/data/fraud_seeds.json` |
| Abrir a página: lista de municípios (select de centro) | `Geo.jsx:51` | `GET /geo/municipios` | `geo.py:290` `municipios` | `geo.py::_municipios` (:167, cache em memória) | `aggregate` `$group` por município/UF em `transacoes` |
| 01 · "Varrer a coleção inteira" | `Geo.jsx:172` -> `rodarViagens()` (:76) | `GET /geo/impossible-travel?limiteKmh=` | `geo.py:346` `impossible_travel` | `geo.py::impossible_travel` + `_haversine_stages` (:61) | `aggregate` `$setWindowFields`/`$shift` + `$facet`, `allowDiskUse` (:475) em `transacoes` |
| 01 · "Só este cliente" (select "recorte por cliente") | `Geo.jsx:181` -> `rodarViagens(clienteFiltro)` | `GET /geo/impossible-travel?limiteKmh=&clienteId=` | idem | idem (com `$match` de `clienteId` antes da janela) | idem |
| 01 · select de limite km/h | `Geo.jsx:168` | nenhuma até clicar em um botão acima | n/a | n/a | n/a |
| 01 · clicar numa linha da tabela / mini mapa | `Geo.jsx:263` (`setViagemSel`), `MiniMapa` `Geo.jsx:290` | nenhuma (usa o resultado já recebido) | n/a | n/a | n/a |
| 02 · select de município (centro) e de raio | `Geo.jsx:~366-374` -> estado `centroIdx`, `raioOperadores` | dispara o efeito abaixo | n/a | n/a | n/a |
| 02 · carga automática ao mudar centro/raio (debounce 250 ms) e botão "rodar" (`rodarOperadores`) | `Geo.jsx:58-70`, botão `Geo.jsx:375` | `POST /geo/operadores` | `geo.py:673` `operadores_geo` | `geo.py::operadores_geo`, `_poligono_quadrado` (:572), `_geo_near_resultado` (:621) | `count_documents` + `find` com `$geoWithin`, `$geoIntersects`, `$near`, `$nearSphere` em `transacoes`; `aggregate` `$geoNear` em `transacoes_geonear` |
| 02 · abas `$geoWithin`/`$geoIntersects` x `$near`/`$nearSphere` | `Geo.jsx:354-357` e `ComparacaoOperadores.jsx:39` | nenhuma | n/a | n/a | n/a |
| 02 · "Rotas · LineString" (e "Executar novamente no Atlas") | `Geo.jsx:385`, `ComparacaoRotas.jsx:12-15` e botão `:41` | `GET /geo/rotas-comparar?lng=&lat=&raioKm=` | `geo.py:744` `comparar_rotas` | `geo.py::comparar_rotas` | `db.aggregate` com `$documents` + `$facet` (:771-776), sem coleção |
| 02 · "Terminais · Point" | `Geo.jsx:386` | nenhuma (mostra o resultado de `/geo/operadores`) | n/a | n/a | n/a |
| "Ver query executada" / "Ver pipeline completo" | `QueryBlock.jsx`, `App.jsx:126`, `Geo.jsx:337,421` | nenhuma (texto vem da resposta) | n/a | n/a | n/a |

Rotas que existem na API mas **não têm botão na UI** (conferido: nenhum `call` para elas em `frontend/src`):

| Rota | Handler | Função / o que faz | Mongo |
|---|---|---|---|
| `POST /geo/explain-compare` | `geo.py:303` | `explain_compare`: mesmo `$geoWithin` com `hint` em dois índices e compara `executionStats` | `command` `explain` de `find` em `transacoes` (`_explain_find`, :149) |
| `POST /geo/search` | `geo.py:822` | `geo_search`: `$search` (fuzzy + `geoWithin` + categoria) e facetas | `aggregate` `$search` e `$searchMeta` em `transacoes`; `find_one` da âncora (`_ancora_da_contestacao`, :804) |
| `GET /geo/sinais-ao-vivo` | `geo.py:209` | `sinais_ao_vivo`: lê sinais já calculados por um processor externo | `find`+`sort`+`limit`, 2x `count_documents` em `sinais_ao_vivo` |
| `GET /health/live`, `/health/ready`, `/` | `main.py:59-72` | saúde | `ping` (ready) |

## 3. Onde estão as queries MongoDB

Textos completos dos pipelines: [briefing/queries.md](briefing/queries.md) (os números de linha de `geo.py` citados lá estão desatualizados; use os daqui).

| O que faz | arquivo::função (linha) | Operador / pipeline principal | Collection |
|---|---|---|---|
| Municípios do dataset | `backend/routers/geo.py::_municipios` (:167-186) | `$group` + `$sort` + `$project`, `allowDiskUse` | `transacoes` |
| Contagem para preflight/status | `geo.py::preflight_checks` (:191), `status` (:262) | `estimated_document_count` | `transacoes` |
| Índices existentes | `geo.py::status` (:265) | `index_information` | `transacoes` |
| Search index existe? | `geo.py::_search_disponivel` (:157-165) | `list_search_indexes` | `transacoes` |
| Explain com hint | `geo.py::_explain_find` (:149-154) e `explain_compare` (:303) | comando `explain` (`executionStats`) de `find` com `$geoWithin` + `$centerSphere` | `transacoes` |
| Viagem impossível | `geo.py::impossible_travel` (:346; `aggregate` :475) | `$setWindowFields` + `$shift`, haversine em MQL (`_haversine_stages` :61), `$facet` (:461) com ramos `avaliados`/`sinais`/`total_sinais`/`aprovados` (`$sample`) | `transacoes` |
| Operadores geo (find) | `geo.py::operadores_geo` (:673; filtros :688-691; `count_documents`/`find` :705-737) | `$geoWithin`, `$geoIntersects` (`$geometry` Polygon), `$near`, `$nearSphere` | `transacoes` |
| `$geoNear` | `geo.py::_geo_near_resultado` (:621; `aggregate` :655) | `$geoNear` + `$facet` (amostra por terminal e total) | `transacoes_geonear` |
| Rotas sintéticas | `geo.py::comparar_rotas` (:744; `aggregate` :776) | `$documents` + `$facet` com `$geoWithin` e `$geoIntersects` em `$match`, `maxTimeMS` | nenhuma (documentos em memória) |
| Busca textual + geo | `geo.py::geo_search` (:822; pipeline :869; `$searchMeta` :912; execução :924-925) | `$search` `compound` (`text` fuzzy ou `exists` + `geoWithin` circular + `in` categoria), `$searchMeta` `facet` | `transacoes` (index `idx_geo_estabelecimento`) |
| Âncora da contestação | `geo.py::_ancora_da_contestacao` (:804) | `find_one` por `endToEndId` | `transacoes` |
| Sinais ao vivo | `geo.py::sinais_ao_vivo` (:209; `find` :225; counts :229-230) | `find` sem o campo `pontos`, ordenado por `detectadoEm` desc | `sinais_ao_vivo` |
| Preflight | `backend/database.py::readiness` (:19) | `admin.command("ping")` | n/a |
| Criar índices | `scripts/seed_geo.py::criar_indices` (:258-277) | `create_index`: `e2e_unq_idx` (único), `cliente_status_local_idx`, `local_2dsphere_idx`, `cliente_ts_idx`, `uf_ts_idx`, `categoria_local_idx` | `transacoes` |
| Coleção espelho do `$geoNear` | `scripts/seed_geo.py::garantir_colecao_geonear` (:292-302) | `aggregate([{$out}])` + `create_index` 2dsphere | `transacoes_geonear` |
| Carga do dataset | `scripts/seed_geo.py::main` (`insert_many` :481; `drop` :463-467; guarda `assert_writable_db` :381) | `insert_many(ordered=False)` em lotes de 5.000 | `transacoes` |
| Registro da versão do dataset | `scripts/seed_geo.py::registrar_dataset` (:305-316), `verificar_prontidao` (:319), `dataset_atual` (:359) | `replace_one(upsert)` / leituras de conferência | `demo_metadata`, `transacoes` |
| Search index | `scripts/create_search_index_geo.sh` (`updateSearchIndex` :86, `createSearchIndex` :90) | definição `idx_geo_estabelecimento` (string pt, token+facet, geo) | `transacoes` |

Armadilha registrada no código: `$geoNear` não roda em `transacoes` porque ela tem dois índices 2dsphere de propósito; por isso existe `transacoes_geonear` (comentários em `geo.py:49-54` e `:650-655`).

## 4. Compartilhado × só desta PoV

- **`_shared`**: nenhum import em código Python/JS. A única ligação é visual: `frontend/src/pov-signature.css` é cópia mantida por `_shared/ui/pov-signature.css` via `_shared/ui/sync-ui.sh` (fonte: `CLAUDE.md` deste repo, linha 95); não editar à mão.
- **Variáveis de ambiente** (`backend/.env`, modelo `backend/.env.example`; `frontend/.env.example`):
  - Conexão: `MONGO_URI` (cluster; vem do ambiente comum), `MONGO_DB` (padrão `POC`; **não é** o banco do Geo), `MONGO_TIMEOUT_MS` — `backend/settings.py`.
  - Locais do módulo Geo: `GEO_DB` (padrão `geo`) e `GEO_SEARCH_INDEX` (padrão `idx_geo_estabelecimento`) — lidos em `geo.py:33-35` e no seed/script.
  - Segurança/operação: `DEMO_ADMIN_TOKEN`, `ALLOWED_ORIGINS`, `MAX_REQUEST_BYTES`; front: `VITE_DEMO_API_TOKEN`, `VITE_API_PROXY_TARGET`.
  - `ATLAS_PUBLIC_KEY/PRIVATE_KEY/PROJECT_ID/CLUSTER`: lidas em `settings.py`, sem uso no restante do código (conferido).
  - Não confirmei no repositório quais vêm do `.env.shared`/`sync_env`.
- **Bancos/coleções**: banco `geo` com `transacoes`, `transacoes_geonear`, `demo_metadata` (todos criados pelo seed, exclusivos desta PoV). `sinais_ao_vivo` é lida pela rota `/geo/sinais-ao-vivo` mas **não é escrita neste repo**: a docstring (`geo.py:212`) e o texto da linha 563 atribuem a leitura ao processor `geoSinais30s` "do módulo 07" (outra PoV/módulo). Não encontrei esse processor aqui.
- **Chamadas externas**: apenas o MongoDB Atlas (pymongo) e `mongosh` no script do search index. Opcionalmente o SDK do Google Maps no navegador (`frontend/src/components/MapaBrasil.jsx`, `carregarSdk` :294). Sem LLM, Voyage ou Langfuse.

## 5. "Quero mexer em..."

- Texto/títulos da tela -> `frontend/src/pages/Geo.jsx` (seções 01 e 02) e `App.jsx` (cabeçalho).
- A regra de viagem impossível (limite, corte, saída) -> `backend/routers/geo.py::impossible_travel` (:346); fórmula de distância em `_haversine_stages` (:61).
- Opções do select de km/h -> `LIMITES_KMH` em `frontend/src/pages/Geo.jsx`.
- Operadores comparados (filtros e `$geoNear`) -> `geo.py::operadores_geo` (:673) e `_geo_near_resultado` (:621).
- Rotas de exemplo (coordenadas) -> `geo.py::comparar_rotas` (:744).
- Adicionar rota -> `geo.py` (decorator `@router`) + chamada com `call('/geo/...')` na página.
- Religar o painel de busca na UI -> a rota já existe (`geo.py:822`, corpo em `SearchRequest` :789); falta um componente que faça `call('/geo/search', {method:'POST', ...})`.
- Índices -> `scripts/seed_geo.py::criar_indices` (:258); depois `python scripts/seed_geo.py --ensure`/`--drop`.
- Quantidade de dados/clientes/fraudes plantadas -> `scripts/seed_geo.py` (`--clientes`, `--por-cliente`, `--fraudes`, :408-410); gerador em `gerar` (:142).
- Definição do Atlas Search index -> `scripts/create_search_index_geo.sh` (bloco `definicao`).
- Porta -> `frontend/vite.config.js` (5184 e alvo 8184), `uvicorn ... --port 8184` (README) e `ALLOWED_ORIGINS` padrão em `backend/settings.py`.
- Segurança de mutações -> `backend/security.py::MutationGuardMiddleware` (:28). (Hoje não há rota de escrita em `/geo`; o guard protege POST/DELETE em geral, e os POSTs de leitura passam por ele.)

## 6. Testes

- `backend/tests/test_geo.py` (565 linhas, Mongo simulado, sem cluster): resumo de plano do `explain`, `explain_compare` com os dois hints, monta `$setWindowFields`+haversine em um único estágio, corte geométrico, seletividade (pares avaliados/alertas por dia), `$search` (degrada sem índice, geoWithin em metros, âncora, sem termo ordena por distância), `$geoNear` amostrando terminais, rotas via `$documents`, determinismo do seed, `dataset_atual`, preflight somente leitura.
- `frontend/tests/geo-map.test.mjs`: matemática de projeção/mapa.
- Comandos (README, "Commands"), na raiz: `pytest` (usa `pyproject.toml`, `testpaths = backend/tests`); `ruff check backend`; `cd frontend && node --test tests/*.test.mjs`. Antes da demo: `curl http://localhost:8184/preflight`.
