# MongoDB Atlas Geo Showcase

PoV interativa que prova comportamento geoespacial real do MongoDB Atlas contra um
cluster real, sem storytelling de antifraude e sem mapa bonito por si só. Dois
painéis:

1. **Investigação retrospectiva** (`impossible-travel`) — pares de compras
   presenciais do mesmo cliente distantes demais para o tempo entre elas.
   `$setWindowFields` particiona por cliente, `$shift` traz a compra anterior e
   a distância sai de haversine em operadores MQL puros, dentro do cluster.
2. **Operadores de consulta geoespacial** (`operadores`) — os cinco
   operadores/estágios geoespaciais do MongoDB lado a lado sobre a mesma
   geometria: `$geoWithin`, `$geoIntersects`, `$near`, `$nearSphere` e
   `$geoNear`.

Este repositório foi extraído do módulo Geo (08) da
[`mongodb-atlas-feature-showcase`](https://github.com/adrianofratelli-glitch/mongodb-atlas-feature-showcase)
como PoV standalone. Frontend React 18 + Vite, backend FastAPI + PyMongo,
MongoDB Atlas como camada de dados. Sem LLM.

Textos da UI, docstrings e mensagens de erro são pt-BR por design (público
brasileiro).

## O que isto prova, e o que não prova

- Prova: predicados geoespaciais reais (`$geoWithin`, `$geoIntersects`,
  `$near`, `$nearSphere`, `$geoNear`) rodando no cluster, com índice
  `2dsphere` (confirmado via `explain()`, IXSCAN não COLLSCAN), e um cálculo
  de distância (haversine) inteiramente em MQL, sem trazer dado à aplicação.
- Não prova: não é motor antifraude, não tem rótulo de fraude confirmada
  (então não existe precisão/recall calculável), não faz álgebra de geometria
  (sem buffer/união/interseção/área — só WGS84, sem raster nem topologia).
  `$geoNear` precisa ser o primeiro estágio do pipeline; o `filter` do
  `$vectorSearch` rejeita operadores geoespaciais.

## Comandos

```bash
# Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # preencha MONGO_URI
uvicorn main:app --reload --port 8010

# Dataset (raiz do repo, venv do backend ativa)
python scripts/seed_geo.py            # 150 mil transações georreferenciadas em geo.transacoes
python scripts/seed_geo.py --drop     # recria do zero
python scripts/seed_geo.py --ensure   # caminho idempotente
./scripts/create_search_index_geo.sh  # índice do Atlas Search (painel de busca, ver docs/setup-geo.md)

# Frontend
cd frontend
npm install
cp .env.example .env
npm run dev            # :5184, proxy /api -> :8010
```

Testes e lint (raiz do repo):

```bash
pytest                          # backend/tests, Mongo stubado — sem cluster ao vivo
ruff check backend
cd frontend && node --test tests/*.test.mjs
```

Antes de qualquer demo: `curl http://localhost:8010/preflight`.

## Ambiente

Copie `backend/.env.example` para `backend/.env`:

- `MONGO_URI`, `MONGO_DB` (padrão `POC`), `MONGO_TIMEOUT_MS`.
- `GEO_DB` (padrão `geo`), `GEO_SEARCH_INDEX` (padrão `idx_geo_estabelecimento`).
- `DEMO_ADMIN_TOKEN` — necessário só para permitir mutações vindas de algo que
  não seja loopback (esta PoV não expõe mutações destrutivas, mas o guard é o
  mesmo do restante do portfólio); espelhe como `VITE_DEMO_API_TOKEN` no
  frontend.
- `ALLOWED_ORIGINS` (padrão `http://localhost:5184,http://127.0.0.1:5184`).

## Dataset

`scripts/seed_geo.py` gera 150 mil transações de cartão presencial, clusters
gaussianos ao redor de 40 municípios reais. A localização é a coordenada
cadastrada do terminal do adquirente (`TERMINAL_ADQUIRENTE`, `CADASTRAL`) — um
terminal mantém identidade, estabelecimento e coordenada estáveis. Viagem
impossível é sinal de risco, nunca decisão de fraude. Idempotente por uma
semente fixa de RNG mais um índice único em `endToEndId`.

Pares plantados de viagem impossível derivam o intervalo de uma velocidade
alvo (1.100–9.000 km/h), nunca o contrário: sortear minutos diretamente dava
16.000–42.000 km/h — vinte vezes qualquer padrão real de cartão clonado. O
dataset aleatoriza a posição do par na sequência do cliente, então os casos se
espalham pelos 90 dias em vez de se concentrarem no início.

`backend/data/fraud_seeds.json` guarda os IDs de cliente cujos pares foram
plantados, para que a demo tenha resultado garantido no palco; regerado pelo
seed.

## Armadilhas técnicas

- **`$geoNear` recusa rodar quando o campo geo tem mais de um índice
  2dsphere, e não há hint que resolva** — testado em três formas (hint no
  `aggregate()`, `key` dentro do estágio, hint cru via `db.command`), as três
  recusadas com `code 27 IndexNotFound`. `geo.transacoes` tem dois de
  propósito (o puro `local_2dsphere_idx` e o composto
  `cliente_status_local_idx` do painel de explain). Resolvido com
  `geo.transacoes_geonear`, cópia via `$out` mantida pelo próprio
  `scripts/seed_geo.py` (nos dois caminhos, `--ensure` e geração completa) com
  um único índice — sem reescrever o gerador.
- **Achado de resiliência**: círculo (`$near`/`$nearSphere`/`$geoNear`, via
  `$maxDistance` esférico) e quadrado (`$geoWithin`/`$geoIntersects`, via
  `$geometry` Polygon) sobre o mesmo raio retornam contagens diferentes por
  design — círculo inscrito no quadrado cobre menos área. Testado em 2M
  documentos (raio 2000km): 128.364 (quadrado) vs 119.152 (círculo),
  consistente com a geometria, não bug.
- **`$near`/`$nearSphere` são operadores de `find()`**: não funcionam dentro
  de `$match` de um pipeline de agregação, então não têm `count_documents` —
  restrição real do MongoDB, não desta demo. `$geoNear` resolve isso: é o
  caminho de agregação, primeiro estágio obrigatório.
- O quadrado ao redor de centro+raio usa clamp de coordenadas perto do
  polo/antimeridiano — sem o clamp, `$geoWithin` retorna `BadValue` de
  latitude fora de `[-90,90]`.
- O painel de investigação roda um `$facet` com dois ramos sobre o mesmo
  `$setWindowFields` (a parte cara, uma vez só): `sinais` (acima do limite) e
  `aprovados` (`$sample` dentro do limite). A lista final intercala as duas
  classes em vez de ordenar só por `ts`, porque a amostra aprovada tende a
  concentrar datas recentes e empurrava todas as sinalizadas para o fim da
  tabela. Seletividade (pares avaliados / sinalizados / taxa / alertas por
  dia) é contada **antes** do corte geométrico.
- O mapa (`frontend/src/components/MapaBrasil.jsx`) usa malha estadual do
  IBGE (`frontend/src/data/brasil-uf.js`, 27 UFs, ~41 KB), simplificada com
  Douglas-Peucker a 0,05° sobre coordenadas quantizadas em grade de 0,02° — a
  quantização é o que impede fresta entre UFs vizinhas. Projeção
  equiretangular com fator `cos(-15°)`: sem ele o Sul sai ~18% largo demais.
  Sem Leaflet/Mapbox/tiles e sem dependência de mapa externa — o módulo
  renderiza e continua funcional com a rede externa bloqueada. A única
  requisição externa é o Google Fonts em `frontend/index.html`.
- O painel de busca por relevância textual (`POST /geo/search`,
  `GET /geo/explain-compare`) continua implementado e testado, mas fora do
  fluxo visível padrão do frontend (só os dois painéis acima estão na tela) —
  disponível via API para quem quiser explorar o `$search` + facetas.

## Segurança

`MutationGuardMiddleware` bloqueia mutações fora do loopback a menos que
`DEMO_ADMIN_TOKEN` case via `hmac.compare_digest`; `ApiHardeningMiddleware`
aplica teto de tamanho de corpo e cabeçalhos `nosniff`/`DENY`/`no-referrer`/
`no-store`. Esta PoV não expõe endpoints destrutivos (sem criação/exclusão de
índice, sem `collMod`) — os dois módulos são somente leitura sobre
`geo.transacoes`.

Nunca aponte para nada além de um cluster de demonstração descartável, e
mantenha credenciais fora de controle de versão (`backend/.env` está no
`.gitignore`).
