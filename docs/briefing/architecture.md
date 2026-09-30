# Arquitetura — MongoDB Atlas Geo Showcase

## O que é essa PoV

PoV standalone extraída do módulo 08 (Geo) da `mongodb-atlas-feature-showcase`,
para provar comportamento geoespacial real do MongoDB Atlas — sem storytelling
de antifraude e sem mapa bonito por si só. Não é motor antifraude, não tem
rótulo de fraude confirmada, não calcula rota por ruas. **Sem LLM.** UI,
docstrings e mensagens de erro em pt-BR por design (público brasileiro).

Dois painéis visíveis no frontend, mais um painel de busca (Atlas Search) que
existe na API mas está fora do fluxo padrão da tela:

1. **Investigação retrospectiva** (`impossible-travel`) — pares de compras
   presenciais do mesmo cliente distantes demais para o tempo decorrido entre
   elas. `$setWindowFields` particiona por cliente, `$shift` traz a compra
   anterior, e a distância sai de haversine em operadores MQL puros — tudo
   dentro do cluster, nenhum documento volta para cálculo na aplicação.
2. **Operadores de consulta geoespacial** (`operadores`) — os cinco
   operadores/estágios geoespaciais do MongoDB lado a lado sobre a mesma
   geometria: `$geoWithin`, `$geoIntersects`, `$near`, `$nearSphere`,
   `$geoNear`.
3. **Busca por relevância + geo** (`search`, `explain-compare` fora do fluxo
   visível padrão) — `$search` combinando texto, filtro geoespacial e
   facetas; e comparação de planos de execução (`explain`) sob dois índices
   diferentes.

## Stack

```
React 18 + Vite (frontend/, :5184) --fetch--> FastAPI (backend/main.py, :8010) --> PyMongo --> MongoDB Atlas
```

- **Frontend**: React 18, Vite, sem biblioteca de mapa externa (sem
  Leaflet/Mapbox/tiles — ver seção "Mapa" abaixo). Fetch puro via hooks
  próprios.
- **Backend**: FastAPI + PyMongo, um único `MongoClient` compartilhado
  (`backend/database.py`). Sem ORM, sem camada de service — os endpoints em
  `backend/routers/geo.py` montam pipeline/filtro e chamam o driver
  diretamente.
- **Dados**: MongoDB Atlas, banco `geo` (configurável via `GEO_DB`), coleção
  principal `transacoes`, mais uma coleção espelho `transacoes_geonear` só
  para o operador `$geoNear` (ver "Decisão: por que duas coleções").
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
| `backend/tests/test_geo.py` | 34 testes unitários, Mongo stubado via monkeypatch — roda sem cluster ao vivo. |

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
4. Painel de busca (fora do fluxo da tela, só via API): `POST /geo/search` →
   `$search` (Atlas Search) com filtro `geoWithin` + texto opcional +
   facetas via `$searchMeta`.

Nenhum cálculo geoespacial roda no frontend nem na camada de aplicação Python
— tudo que aparece na tela é o resultado de uma query/pipeline que rodou no
Atlas. Ver `docs/briefing/queries.md` para o detalhe de cada uma.

## Decisões de arquitetura (o "porquê")

- **Por que duas coleções (`transacoes` e `transacoes_geonear`)?**
  `$geoNear` recusa rodar quando o campo geo tem mais de um índice 2dsphere,
  e não existe `hint` que resolva isso — testado em três formas (hint no
  `aggregate()`, `key` dentro do estágio, hint cru via `db.command`), todas
  recusadas com `code 27 IndexNotFound`. Como `transacoes` precisa de dois
  índices 2dsphere de propósito (`local_2dsphere_idx` puro e
  `cliente_status_local_idx` composto, para o comparativo de explain da Demo
  A), a solução foi copiar os dados via `$out` para `transacoes_geonear`, que
  tem um único índice 2dsphere — mantida pelo próprio `scripts/seed_geo.py`
  em ambos os caminhos (`--ensure` e geração completa), sem reescrever o
  gerador principal. Ver `backend/routers/geo.py:49-54` e
  `scripts/seed_geo.py:292-302`.

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

## Testes e verificação

```bash
pytest                          # backend/tests, Mongo stubado — sem cluster ao vivo
ruff check backend
cd frontend && node --test tests/*.test.mjs
```

Antes de qualquer demo: `curl http://localhost:8010/preflight` — valida
`MONGO_URI`, conectividade, dataset carregado e (opcionalmente, sem
reprovar) disponibilidade do Atlas Search index.
