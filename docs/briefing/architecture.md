# Arquitetura — MongoDB Atlas Geo Showcase

## O que é essa PoV

PoV standalone extraída do módulo 08 (Geo) da `mongodb-atlas-feature-showcase`,
para provar comportamento geoespacial real do MongoDB Atlas — sem storytelling
de antifraude e sem mapa bonito por si só. Não é motor antifraude, não tem
rótulo de fraude confirmada, não calcula rota por ruas. **Sem LLM.** UI,
docstrings e mensagens de erro em pt-BR por design (público brasileiro).

Três painéis visíveis no frontend:

1. **Investigação retrospectiva** (`impossible-travel`) — pares de compras
   presenciais do mesmo cliente distantes demais para o tempo decorrido entre
   elas. `$setWindowFields` particiona por cliente, `$shift` traz a compra
   anterior, e a distância sai de haversine em operadores MQL puros — tudo
   dentro do cluster, nenhum documento volta para cálculo na aplicação. A
   resposta inclui o gabarito do gerador (`gabarito_sintetico`): quantos pares
   plantados pelo seed a regra encontra no limite escolhido e quantos
   sinalizados não foram plantados. É cobertura do gerador, não precisão de
   fraude.
2. **Operadores de consulta geoespacial** (`operadores`) — os cinco
   operadores/estágios geoespaciais do MongoDB lado a lado sobre a mesma
   geometria: `$geoWithin`, `$geoIntersects`, `$near`, `$nearSphere`,
   `$geoNear`.
3. **Índice certo e busca com geo** (`explain-compare`, `search`) —
   o mesmo `$geoWithin` medido sob dois índices (`explain` com
   `executionStats`) e um `$search` que combina texto fuzzy, `near` (score por
   proximidade), raio `geoWithin` e facetas via `$searchMeta`. Componente
   `frontend/src/components/PainelIndiceBusca.jsx` (ADR 0002).

## Stack

```
React 19 + Vite (frontend/, :5184) --fetch--> FastAPI (backend/main.py, :8184) --> PyMongo --> MongoDB Atlas
```

- **Frontend**: React 19, Vite, sem biblioteca de mapa externa (sem
  Leaflet/Mapbox/tiles — ver seção "Mapa" abaixo). Fetch puro via hooks
  próprios.
- **Backend**: FastAPI + PyMongo, um único `MongoClient` compartilhado
  (`backend/database.py`). Sem ORM, sem camada de service — os endpoints em
  `backend/routers/geo.py` montam pipeline/filtro e chamam o driver
  diretamente.
- **Dados**: MongoDB Atlas, banco `geo` (configurável via `GEO_DB`), coleção
  `transacoes` e `demo_metadata` (identidade do dataset e lista de clientes
  plantados). `$geoNear` roda na própria `transacoes` com `key: "local"`
  (ver "Decisão: `$geoNear` com `key`").
- **Dataset**: sintético, 150 mil transações de cartão presencial, gerado por
  `scripts/seed_geo.py`, clusterizadas em torno de 40 municípios reais do
  Brasil.

## Componentes do backend

| Arquivo | Papel |
|---|---|
| `backend/main.py` | App FastAPI mínimo: CORS, middleware de request-id, handlers de exceção, `/`, `/health/live`, `/health/ready`, `/preflight`. |
| `backend/settings.py` | Configuração central via `.env` (dataclass frozen), sem dependência extra além de `python-dotenv`. |
| `backend/database.py` | Instancia o `MongoClient` único (`connect=False`, lazy) e expõe `readiness()` para o healthcheck. |
| `backend/security.py` | `MutationGuardMiddleware` (bloqueia mutação fora de loopback sem `DEMO_ADMIN_TOKEN`) e `ApiHardeningMiddleware` (teto de tamanho de corpo, headers `nosniff`/`DENY`/`no-referrer`/`no-store`). |
| `backend/routers/geo.py` | Todo o domínio da PoV: os 3 painéis + `status`, `municipios`, `sinais-ao-vivo` (código herdado, não usado pelo frontend deste repo). |
| `backend/tests/test_geo.py` | 45 testes unitários, Mongo stubado via monkeypatch — roda sem cluster ao vivo. |
| `backend/tests_live/test_live_geo.py` | 6 testes contra um banco `*_test` real (só com `GEO_LIVE=1`): IXSCAN, `$geoNear` igual ao círculo, 40/40 plantados, raio do `$search`, rotas. |
| `scripts/bench_geo.py` | Latência por fluxo (parede p50/p95 e tempo no servidor via explain), somente leitura. |

## Componentes do frontend

| Arquivo | Papel |
|---|---|
| `frontend/src/App.jsx` | Casca de módulo único — sem seletor/roteamento por hash, porque só existe este módulo aqui. |
| `frontend/src/pages/Geo.jsx` | Os dois painéis visíveis (investigação + operadores), toda a orquestração de estado e chamadas à API. |
| `frontend/src/components/MapaBrasil.jsx` | Mini-mapa de dois pontos (origem/destino) para o painel de investigação, usando a malha IBGE local. |
| `frontend/src/components/MapaConsulta.jsx` | Mapa de tiles OpenStreetMap para o painel de operadores — mostra centro, raio, polígono e amostra de resultados. |
| `frontend/src/components/ComparacaoRotas.jsx` | Visualização de `$geoWithin`/`$geoIntersects` sobre rotas sintéticas (LineString). |
| `frontend/src/components/ComparacaoOperadores.jsx` | Texto explicativo de quando usar cada um dos 5 operadores. |
| `frontend/src/components/QueryBlock.jsx` | Componente colapsável que renderiza a query/pipeline executado, com syntax highlight — prova visual de que a tela reflete a consulta real. |
| `frontend/src/components/geoMapMath.mjs` | Matemática de projeção/zoom do mapa de tiles. |
| `frontend/src/components/Limites.jsx` | Bloco de "Escopo desta demonstração" — lista limitações verificáveis, nunca inventadas (ver comentário no próprio arquivo). |
| `frontend/src/hooks/useApi.js`, `usePolling.js` | Genéricos, copiados verbatim do repositório de origem. |

## Fluxo de dados

1. Frontend chama `GET /geo/status` e `GET /geo/municipios` ao montar a
   página (`Geo.jsx:49-52`) para popular badges de estado e o seletor de
   centro do mapa.
2. Painel 01: usuário escolhe limite de km/h (e opcionalmente um cliente) →
   `GET /geo/impossible-travel` → pipeline de agregação roda inteiro no
   cluster (`$setWindowFields` + `$shift` + haversine em MQL) → resposta traz
   resultados, seletividade e custo medido (ms, docs no escopo) → tabela +
   mini-mapa.
3. Painel 02: usuário escolhe centro/raio → `POST /geo/operadores` (debounce
   de 250ms, `AbortController` cancela chamada em voo) → backend roda os 5
   operadores/estágios em paralelo sobre a mesma geometria → resposta traz
   query e amostra de cada um → mapa de tiles + `QueryBlock`.
4. Painel 03: botão "Comparar planos" → `POST /geo/explain-compare` (dois
   `explain` com `hint`); botão "Buscar" → `POST /geo/search` → `$search`
   (Atlas Search) com filtro `geoWithin`, texto opcional com `should: near`
   e facetas via `$searchMeta`.

Nenhum cálculo geoespacial roda no frontend nem na camada de aplicação Python
— tudo que aparece na tela é o resultado de uma query/pipeline que rodou no
Atlas. Ver `docs/briefing/queries.md` para o detalhe de cada uma.

## Decisões de arquitetura (o "porquê")

- **Decisão: `$geoNear` com `key`.** `transacoes` tem três índices 2dsphere
  em `local` de propósito (puro, composto da Demo A, categoria + local). Sem
  `key`, o servidor recusa o `$geoNear`. Com `key: "local"`, ele roda na
  própria coleção: no 9.0.7 dá a mesma contagem e os mesmos documentos
  examinados que a antiga cópia `transacoes_geonear`, que foi aposentada. Se o
  servidor recusar, só o card do `$geoNear` degrada. Ver
  `docs/adr/0001-geonear-na-colecao-principal-com-key.md` e
  `backend/routers/geo.py::_geo_near_resultado`.

- **Decisão: manifesto de plantados no banco.** O seed grava a lista em
  `demo_metadata.clientesPlantados`, e a API lê de lá (`geo.py::_manifesto`),
  com fallback para `backend/data/fraud_seeds.json`. Seed em banco `*_test`
  não reescreve o arquivo versionado.

- **Por que sem biblioteca de mapa externa?** `MapaBrasil.jsx` usa malha
  estadual do IBGE embarcada localmente (`frontend/src/data/brasil-uf.js`,
  27 UFs, ~41 KB), simplificada com Douglas-Peucker a 0,05° sobre
  coordenadas quantizadas em grade de 0,02° (a quantização evita fresta
  entre UFs vizinhas), com projeção equiretangular corrigida por
  `cos(-15°)` (sem a correção o Sul do Brasil sai ~18% largo demais). Isso
  garante que o módulo renderiza e continua funcional mesmo com a rede
  externa bloqueada — a única requisição externa de todo o app é o Google
  Fonts em `frontend/index.html`. `MapaConsulta.jsx` (painel 02) é a
  exceção: usa tiles do OpenStreetMap para mostrar o contexto geográfico
  real ao redor do centro/raio escolhido, mas continua funcional (degradado,
  sem tiles) se a rede externa cair.

- **Por que `$facet` com dois ramos no painel de investigação?** O
  `$setWindowFields` (a parte cara do pipeline) roda uma única vez, e o
  `$facet` bifurca em `sinais` (pares acima do limite) e `aprovados`
  (`$sample` dentro do limite) — mostra as duas faces da mesma decisão, não
  só a fila de suspeitos. A lista final intercala as duas classes em vez de
  ordenar só por `ts`, porque a amostra aprovada tende a concentrar datas
  recentes e empurraria todas as sinalizadas para o fim da tabela
  (`backend/routers/geo.py:461-498`).

- **Por que a seletividade é contada antes do corte geométrico?** A
  pergunta de um time de risco não é "quantos sinais saíram" e sim "de
  quantas oportunidades" — sem denominador, "40 pares" não diz se a regra é
  seletiva ou se inunda a fila de alertas (`backend/routers/geo.py:461-466`).

- **Por que sem LLM?** Escopo deliberado desta PoV — o objetivo é provar
  comportamento geoespacial puro do banco, não um caso de uso de IA. Não há
  `agent-behavior.md` neste briefing por esse motivo.

- **Segurança**: `MutationGuardMiddleware` bloqueia mutação fora de loopback
  a menos que `DEMO_ADMIN_TOKEN` case via `hmac.compare_digest`;
  `ApiHardeningMiddleware` aplica teto de tamanho de corpo e headers de
  hardening. Na prática, esta PoV não expõe nenhum endpoint destrutivo — os
  painéis visíveis e o de busca são somente leitura sobre `geo.transacoes`.
  Os middlewares seguem ativos por consistência com o resto do portfólio,
  não porque bloqueiam algo que hoje existe aqui.

## Ambiente / variáveis

`backend/.env` (a partir de `.env.example`, nunca commitado —
`backend/.env` está no `.gitignore`):

- `MONGO_URI`, `MONGO_DB` (padrão `POC`), `MONGO_TIMEOUT_MS`
- `GEO_DB` (padrão `geo`), `GEO_SEARCH_INDEX` (padrão `idx_geo_estabelecimento`)
- `DEMO_ADMIN_TOKEN` — necessário só para permitir mutação vinda de fora do
  loopback (esta PoV não expõe mutação destrutiva, mas o guard é o mesmo do
  restante do portfólio)
- `ALLOWED_ORIGINS` (padrão `http://localhost:5184,http://127.0.0.1:5184`)
- `MAX_REQUEST_BYTES`

`frontend/.env`: `VITE_DEMO_API_TOKEN` (espelha `DEMO_ADMIN_TOKEN`),
`VITE_API_PROXY_TARGET`, `VITE_MAP_TILES_URL` (opcional, sobrescreve a URL
dos tiles do OpenStreetMap).

**Nunca aponte para nada além de um cluster de demonstração descartável.**

## Como sobe (launcher)

`start.sh` na raiz sobe o backend (`uvicorn` em 127.0.0.1:8184, espera
`/health/live`) e depois o frontend (`vite preview` do bundle em 5184,
reconstruído só quando `src/` muda; `POV_DEV=1` usa `--reload` e `vite dev`).
Fica em primeiro plano e arma os traps antes do primeiro filho: no SIGTERM (ou
Ctrl+C) guarda os PIDs da árvore inteira, manda TERM e depois KILL (o `npm`
deixaria o `vite` neto escutando, já reparentado) e **sai** com 143/130, mesmo
no meio da partida, em vez de seguir e subir o frontend sem trap. Porta
ainda ocupada espera até 10 s e depois falha sem matar o processo alheio.

É o launcher do PoV Portfolio (id `geo` em `pov-portfolio/povs.json`, health
`/health/live`). `POV_BACKEND_PORT`/`POV_FRONTEND_PORT` (o portal exporta a
partir do manifesto) trocam as portas só na instância de teste do portal; com
porta de frontend diferente de 5184, o script exporta `ALLOWED_ORIGINS` para a
nova origem, e `VITE_API_PROXY_TARGET` sempre aponta o proxy para o backend em
uso. Contrato testado em `backend/tests/test_start_sh.py`.

## Testes e verificação

```bash
pytest                          # backend/tests, Mongo stubado — sem cluster ao vivo
ruff check backend
cd frontend && node --test tests/*.test.mjs
GEO_LIVE=1 GEO_DB=geo_test python -m pytest backend/tests_live   # contra banco *_test semeado
GEO_DB=geo_test python scripts/bench_geo.py --runs 7             # latência (somente leitura)
```

Antes de qualquer demo: `curl http://localhost:8184/preflight` — valida
`MONGO_URI`, conectividade, dataset carregado e (opcionalmente, sem
reprovar) disponibilidade do Atlas Search index.
