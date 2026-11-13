# UI — telas e fluxos

> Números de linha podem ficar defasados após mudanças: a fonte atualizada é [MAPA_DO_CODIGO.md](../MAPA_DO_CODIGO.md).

Screenshots em `docs/screenshots/` (01 a 05, usados no README). Este
documento mapeia telas, componentes e fluxo de interação a partir do código
em `frontend/src/`.

## Tela única

`frontend/src/App.jsx` é a casca do app: sem seletor de módulo nem
roteamento por hash, porque esta PoV extraída só tem um módulo (Geo). Toda a
tela vive em `frontend/src/pages/Geo.jsx`, mais o painel 03 em
`frontend/src/components/PainelIndiceBusca.jsx` e o painel 04 em
`frontend/src/components/PainelGeocerca.jsx`.

Toda seção abre com a faixa **caso de negócio** (`CasoNegocio.jsx`): a
pergunta de setor que ela responde (01 prevenção a fraude com cartão; 02
varejo e logística; 03 engenharia/custo e fraude/varejo; 04 logística,
seguros e varejo). São perguntas típicas, não clientes; o dado é sintético.

Barra de status no topo (renderizada se `GET /geo/status` respondeu):
badges com total de transações, DB.coleção, nº de índices, aviso "dataset
sintético" e, se houver clientes plantados, badge de "N cenários de risco
disponíveis". Se `transacoes === 0`, aparece banner de aviso instruindo a
rodar `python scripts/seed_geo.py`.

---

## Seção 01 · Investigação retrospectiva (impossible travel)

`Geo.jsx:131-346`.

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

**Gabarito do gerador** (só na coleção inteira): "N de 40 pares plantados
encontrados acima de X km/h · M sinalizado(s) não plantado(s)", com nota de
que mede cobertura do gerador sintético, não precisão/recall de fraude. Ao
vivo no `geo_test`: 40/40 de 300 a 1.200 km/h, 37/40 a 2.000 km/h e 1
emergente a 300 km/h.

**Rodapé**: nota de seletividade + aviso de que o percentual é do dataset
sintético, não de portfólio real; e `QueryBlock` colapsável com o pipeline
completo (JSON formatado, syntax highlight).

---

## Seção 02 · Operadores de consulta geoespacial

`Geo.jsx:348-437`.

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
- Se o servidor recusar o `$geoNear`, o card mostra um banner com o erro e o
  badge "indisponível"; os outros operadores seguem normais.

---

## Seção 03 · Índice certo e busca com geo

`frontend/src/components/PainelIndiceBusca.jsx` (ADR 0002). Select de centro
próprio (municípios) e dois blocos:

- **A · Mesmo `$geoWithin`, dois índices**: selects de cliente (só
  plantados) e raio (50/500/2.000 km), botão "Comparar planos" → `POST
  /geo/explain-compare`. Tabela com índice, estágios, chaves examinadas,
  devolvidos e ms de cada plano, e a frase "o 2dsphere puro examinou N× mais
  chaves" (medido, com ressalva de cache). Ao vivo: 64 vs 128.153 chaves
  para os mesmos 63 documentos.
- **B · Atlas Search: texto + raio + facetas**: selects de termo (vazio,
  padaria, farmácia, posto, restaurante, barbearia) e raio (5/25/50 km),
  botão "Buscar" → `POST /geo/search`. Badges de ordenação, total no filtro
  e facetas de categoria/UF; lista com nome, município, km do centro e score;
  `QueryBlock` do pipeline `$search` e do `$searchMeta`. Sem índice Search, o
  banner "Índice de busca ausente" aparece e o bloco A continua funcionando.

## Seção 04 · Geocerca: mesma pergunta, dois motores

`frontend/src/components/PainelGeocerca.jsx` (ADR 0003). Selects de centro
(municípios), tamanho da geocerca (≈ 8/15/60/600 km), categoria (as 5 do
seed) e texto (termos que existem em nomes daquela categoria, ou vazio),
checkbox "densificar bordas" e botão "Comparar os dois motores" → `POST
/geo/geocerca-comparar` (3 execuções de cada motor + 1 explain de cada).

- Pergunta em uma linha e badge de vértices (7, ou ~600 densificado).
- Veredito: verde "Mesma resposta nos dois motores: N terminais e M
  compras" ou laranja "Respostas diferentes", com os ids só no nativo / só
  no Search / compras divergentes e a explicação da borda reta × geodésica.
- Dois cartões: terminais, compras, servidor (explain), parede p50, primeiro
  estágio; no nativo também índice e chaves/docs examinados. Os dois
  pipelines comparados fazem o mesmo trabalho (sem texto). No Search, à
  parte, a relevância para o termo (`should: text`): tempo no servidor contra
  o Search sem texto, os 5 terminais mais relevantes (score > 0) e o próprio
  `QueryBlock`. Cada cartão tem o `QueryBlock` do pipeline executado. Sem
  índice `READY`, ou se a execução/explain do Search falhar, o cartão do
  Search vira aviso e o nativo continua medido.
- Nota com os dois tempos de servidor; a conclusão ("nativo N× mais barato",
  "Search N× mais barato" ou "empate técnico", abaixo de 20%) sai da razão
  medida no clique. A medição repetida fica em `scripts/bench_geo.py`.
- Mapa (`MapaConsulta`) com o polígono e até 24 terminais: os divergentes
  primeiro.

Roteiro sugerido: São Paulo ≈ 15 km (mesma resposta; nativo mais barato) →
Sorocaba ≈ 600 km (3 terminais de Juiz de Fora só no Search) → marcar
"densificar bordas" (respostas iguais; agora o Search é mais barato).

**Rodapé da tela** (`Limites`): componente `<details>`
colapsável "Escopo desta demonstração" — itens fixos, verificáveis:
rotas são sintéticas sem persistência; investigação não calcula trajeto por
ruas nem aprova compra; `$geoNear` indica o índice com `key: "local"`; o
gabarito do painel 01 não mede fraude real; a geocerca do painel 04 é
sintética e os casos de negócio são perguntas típicas, não clientes. Ver comentário em `Limites.jsx` sobre por que a regra
é "limite inventado é pior que limite omitido".

---

## Componentes de suporte

| Componente | Papel |
|---|---|
| `MapaBrasil.jsx` (`MiniMapa`) | Mapa leve com malha IBGE local (sem tiles externos), usado na Seção 01 para mostrar 2 pontos + linha. |
| `MapaConsulta.jsx` | Mapa com tiles OpenStreetMap, zoom/pan, usado nas Seções 02 e 04. Degrada (`failed` state) se os tiles não carregarem — continua mostrando pontos/polígono sem fundo de mapa. |
| `ComparacaoRotas.jsx` | Chama `GET /geo/rotas-comparar` e desenha as 3 rotas sintéticas classificadas por `$geoWithin`/`$geoIntersects`. |
| `ComparacaoOperadores.jsx` | Texto didático estático por operador (não chama API). |
| `QueryBlock.jsx` | `<details>`-like colapsável com `react-syntax-highlighter` (tema `atomOneDark`) — usado nas três seções para mostrar a query/pipeline JSON real. |
| `PainelIndiceBusca.jsx` | Seção 03: explain medido de dois índices e busca `$search` com texto, `near`, raio e facetas. |
| `PainelGeocerca.jsx` | Seção 04: geocerca no 2dsphere nativo × Atlas Search, veredito, medições, pipelines e mapa. |
| `CasoNegocio.jsx` | Faixa "caso de negócio" no topo de cada seção. |
| `Limites.jsx` | Bloco de limitações declaradas, padrão reaproveitado do portfólio maior (módulo 08 original). |
| `geoMapMath.mjs` | Funções puras de projeção (`project`, `fitView`, `circleRing`, `metersPerPixel`) usadas por `MapaConsulta`. |
| `useApi.js`, `usePolling.js` | Hooks genéricos de fetch, copiados verbatim do repositório de origem. |

## Endpoint herdado sem tela

`GET /geo/sinais-ao-vivo` (lê `geo.sinais_ao_vivo`, populada por um processor
que só existe no repositório de origem) não é chamado por nenhuma tela e
degrada para `indisponivel`.
