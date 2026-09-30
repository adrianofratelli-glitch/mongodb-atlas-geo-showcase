# UI — telas e fluxos

Sem screenshots no repositório (não há `*.png`/`*.jpg` versionados). Este
documento mapeia telas, componentes e fluxo de interação a partir do código
em `frontend/src/`.

## Tela única

`frontend/src/App.jsx` é a casca do app: sem seletor de módulo nem
roteamento por hash, porque esta PoV extraída só tem um módulo (Geo). Toda a
tela vive em `frontend/src/pages/Geo.jsx` (436 linhas).

Barra de status no topo (renderizada se `GET /geo/status` respondeu):
badges com total de transações, DB.coleção, nº de índices, aviso "dataset
sintético" e, se houver clientes plantados, badge de "N cenários de risco
disponíveis". Se `transacoes === 0`, aparece banner de aviso instruindo a
rodar `python scripts/seed_geo.py`.

---

## Seção 01 · Investigação retrospectiva (impossible travel)

`Geo.jsx:129-341`.

**Objetivo da tela**: "Investigar 90 dias sem tirar o histórico do banco."

**Bloco "onde roda"** (`geo-origem`, linhas 146-165): mostra explicitamente
que o cálculo é "agregação no cluster Atlas", a coleção (`geo.transacoes`),
o total estimado de documentos e o índice do recorte (`cliente_ts_idx`) —
existe para que a demo não pareça cálculo local do frontend.

**Controles** (linhas 166-197):
- Select "limite (km/h)": 300 / 600 / 900 / 1200 / 2000.
- Botão "Varrer a coleção inteira" → `rodarViagens()` → `GET
  /geo/impossible-travel?limiteKmh=...`.
- Select "recorte por cliente": populado só com clientes que o seed plantou
  (lido de `status.fraudes_plantadas.lista`) — nenhuma seleção do combo
  devolve tela vazia por engano.
- Botão "Só este cliente" → mesmo endpoint + `&clienteId=...`.
- Badges de contagem (sinalizadas / não sinalizadas) aparecem após rodar.

**Comparação de tempos** (`geo-comparacao`, linhas 199-213): guarda as
últimas medições de "coleção inteira" vs "recorte por cliente" lado a lado —
prova visual de que filtrar por cliente é mais barato.

**Seletividade** (`geo-seletividade`, linhas 215-247): 4 números — pares
avaliados, sinalizados, taxa % e alertas/dia (só quando não há filtro de
cliente, porque a métrica é sobre a janela de 90 dias inteira). Nota fixa
deixando claro que é taxa de sinalização, **não** acurácia de fraude
(dataset sintético, sem rótulo confirmado).

**Tabela + mini-mapa** (linhas 250-322): tabela rolável (`geo-tabela-wrap`)
com cliente, km, minutos, km/h, trajeto (`de → para`) e badge
sinalizada/não sinalizada. Clicar numa linha seleciona a viagem e atualiza o
`MiniMapa` (componente `MapaBrasil`, dois pontos + linha entre origem e
destino, com rótulo de km/minutos). Abaixo do mapa: IDs de dispositivo
(terminal) de origem/destino e a origem de captura (`TERMINAL_ADQUIRENTE` =
"terminal do adquirente, posição fixa") — prova de proveniência do dado.
Botão "Investigar este cliente" refaz a consulta filtrada pelo cliente da
linha selecionada.

**Rodapé**: nota de seletividade + aviso de que o percentual é do dataset
sintético, não de portfólio real; e `QueryBlock` colapsável com o pipeline
completo (JSON formatado, syntax highlight).

---

## Seção 02 · Operadores de consulta geoespacial

`Geo.jsx:343-428`.

**Objetivo da tela**: "Consultar por área, proximidade e distância."

**Agrupador** (`geo-grupos`, linhas 353-360): dois botões-toggle —
"Área · dentro ou intersecta?" (seleciona `$geoWithin` por padrão) vs
"Proximidade · quais estão mais perto?" (seleciona `$near` por padrão).

**`ComparacaoOperadores`** (componente separado): explica, para o operador
selecionado, título/uso/detalhe — texto fixo por operador (`$geoWithin`,
`$geoIntersects`, `$near`, `$nearSphere`, `$geoNear`), extraído do próprio
componente (`ComparacaoOperadores.jsx:3-27`).

**Controles** (linhas 364-378): select de centro (lista de municípios vinda
de `GET /geo/municipios`), select de raio (10/25/50/100/200 km), botão
"Rodar os 5 operadores". A consulta também roda automaticamente com debounce
de 250ms sempre que centro/raio muda (`useEffect` com `AbortController`,
linhas 56-72) — evita disparo de requisição a cada tecla/troca rápida.

**Resultado do operador selecionado** (linhas 380-427):
- Se for `$geoWithin`/`$geoIntersects`, alterna entre "Rotas · LineString"
  (usa `ComparacaoRotas`, chamando `GET /geo/rotas-comparar`) e "Terminais ·
  Point" (mostra contagem + amostra da consulta real sobre `transacoes`).
- Badge com contagem de documentos (ou "N primeiros documentos" quando o
  operador não suporta contagem — caso de `$near`/`$nearSphere`).
- Nota contextual: para operadores de área, lembra que sobre pontos os dois
  predicados coincidem, e que as rotas mostram a diferença real.
- Lista de amostra com `endToEndId` real, município/UF e distância em metros
  (quando aplicável) — prova de que veio da consulta, não de mock.
- `MapaConsulta` (tiles OpenStreetMap) plotando centro, raio, polígono (se
  aplicável) e a amostra de pontos.
- `QueryBlock` aberto por padrão (`defaultOpen`) com a query/filtro exato
  executado.

**Rodapé da tela** (`Limites`, linhas 429-433): componente `<details>`
colapsável "Escopo desta demonstração" — 3 itens fixos, verificáveis:
rotas são sintéticas sem persistência; investigação não calcula trajeto por
ruas nem aprova compra; consultas de proximidade usam 2dsphere e `$geoNear`
usa a coleção espelho. Ver comentário em `Limites.jsx` sobre por que a regra
é "limite inventado é pior que limite omitido".

---

## Componentes de suporte

| Componente | Papel |
|---|---|
| `MapaBrasil.jsx` (`MiniMapa`) | Mapa leve com malha IBGE local (sem tiles externos), usado na Seção 01 para mostrar 2 pontos + linha. |
| `MapaConsulta.jsx` | Mapa com tiles OpenStreetMap, zoom/pan, usado na Seção 02. Degrada (`failed` state) se os tiles não carregarem — continua mostrando pontos/polígono sem fundo de mapa. |
| `ComparacaoRotas.jsx` | Chama `GET /geo/rotas-comparar` e desenha as 3 rotas sintéticas classificadas por `$geoWithin`/`$geoIntersects`. |
| `ComparacaoOperadores.jsx` | Texto didático estático por operador (não chama API). |
| `QueryBlock.jsx` | `<details>`-like colapsável com `react-syntax-highlighter` (tema `atomOneDark`) — usado em ambas as seções para mostrar a query/pipeline JSON real. |
| `Limites.jsx` | Bloco de limitações declaradas, padrão reaproveitado do portfólio maior (módulo 08 original). |
| `geoMapMath.mjs` | Funções puras de projeção (`project`, `fitView`, `circleRing`, `metersPerPixel`) usadas por `MapaConsulta`. |
| `useApi.js`, `usePolling.js` | Hooks genéricos de fetch, copiados verbatim do repositório de origem. |

## Painel de busca (Atlas Search) — não exposto na UI

`POST /geo/search` e `GET /geo/explain-compare` estão implementados e
testados no backend, mas **não há tela para eles** neste frontend — ficam
disponíveis só via API para quem quiser explorar `$search` + facetas ou o
comparativo de planos de execução manualmente (ex.: via curl/Postman ou
Swagger em `/docs`, se habilitado). Se o gestor perguntar "onde está a tela
de busca", a resposta é: não existe, é intencional (README, seção "Armadilhas
técnicas").
