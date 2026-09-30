# Módulo de risco geográfico — setup

Como materializar o dataset `geo` e seu índice do Atlas Search, além do que o
módulo alega e do que ele não alega.

Voltar para o [README](../README.md).

O módulo roda contra o próprio banco (`geo`, sobrescreva com `GEO_DB`), então
nunca precisa de nenhuma outra coleção.

```bash
python scripts/seed_geo.py            # 2.000 clientes × 75 transações = 150 mil docs
python scripts/seed_geo.py --drop     # recria do zero
python scripts/seed_geo.py --ensure   # mantém se estiver atual; recria se estiver defasado/incompleto
./scripts/create_search_index_geo.sh  # cria/atualiza e espera até READY
```

O script também mantém `geo.transacoes_geonear` — uma cópia via `$out` com um
único índice `2dsphere`, dedicada ao operador `$geoNear` (que recusa rodar
quando o campo tem mais de um índice 2dsphere, e `transacoes` tem dois de
propósito). Os dois caminhos (`--drop` e `--ensure`) mantêm as duas coleções
sincronizadas; nenhum script separado é necessário.

⚠️ **O `--drop` apaga a coleção, e o índice do Atlas Search vai junto.**
Sempre rode `./scripts/create_search_index_geo.sh` depois, ou o painel de
busca (fora do fluxo visível padrão, ver README) abre como `nao_configurado`.

O gerador usa uma semente fixa e carrega uma versão de dataset, então todo
`endToEndId` é estável e o índice único rejeita reinserções: rodar o seed duas
vezes deixa 150 mil documentos, não 300 mil. Os pontos são clusters gaussianos
ao redor de 40 municípios brasileiros reais, ponderados por população —
coordenadas uniformemente aleatórias dentro do bounding box do país parecem
obviamente falsas num projetor.

**Dataset v5 — os casos plantados.** Quarenta clientes carregam um par
plantado de viagem impossível, listados em `backend/data/fraud_seeds.json`.
Cada par deriva seu intervalo de uma **velocidade alvo** (uniforme entre 1.100
e 9.000 km/h) aplicada à distância real entre as duas cidades — nunca o
contrário. Sortear minutos diretamente produzia 16.000–42.000 km/h, vinte
vezes qualquer padrão real de cartão clonado, e um intervalo fixo de 5 minutos
deixava todas as quarenta linhas idênticas na tela. A posição na sequência do
cliente e o destino também são aleatorizados, dentro da mesma semente fixa de
RNG, de modo que o dataset segue reprodutível.

A localização nunca é apresentada como campo de um meio de pagamento remoto.
Todo ponto deste dataset é uma compra de cartão presencial, e sua coordenada
pertence ao terminal do adquirente — dado cadastral, não o celular do
cliente. Essa distinção é o argumento inteiro: a posição de um terminal não é
controlada por quem está pagando, ainda que possa estar desatualizada ou
errada no cadastro. A procedência viaja com o ponto (id do terminal, canal,
origem, qualidade), de modo que o sinal nunca pareça um fato sem origem.

Índices criados pelo seed:

| Índice | Usado por |
|---|---|
| `cliente_status_local_idx` — `{clienteId: 1, status: 1, local: "2dsphere"}` | painel de explain, o plano composto |
| `local_2dsphere_idx` — `{local: "2dsphere"}` | painel de explain, o plano só-geo contra o qual ele é comparado |
| `cliente_ts_idx` — `{clienteId: 1, ts: 1}` | investigação retrospectiva, partição + ordenação do `$setWindowFields` |
| `categoria_local_idx` — `{"estabelecimento.categoria": 1, local: "2dsphere"}` | consultas geográficas por categoria |
| `uf_ts_idx` — `{uf: 1, ts: -1}` | recorte regional |
| `e2e_unq_idx` — único `{endToEndId: 1}` | idempotência do seed |

## O índice do Atlas Search

O painel de busca por relevância textual (fora do fluxo visível padrão do
frontend, disponível via `POST /geo/search`) precisa de um índice do Atlas
Search. Crie com:

```bash
./scripts/create_search_index_geo.sh
```

Até ele reportar `READY`, o painel mostra um aviso de "não configurado" em vez
de inventar resultados. A definição que ele aplica:

```json
{
  "mappings": {
    "dynamic": false,
    "fields": {
      "estabelecimento": {
        "type": "document",
        "fields": {
          "nome": { "type": "string", "analyzer": "lucene.portuguese" },
          "categoria": [{ "type": "token" }, { "type": "stringFacet" }]
        }
      },
      "uf": [{ "type": "token" }, { "type": "stringFacet" }],
      "local": { "type": "geo" }
    }
  }
}
```

`categoria` e `uf` são indexados duas vezes de propósito: `token` serve ao
filtro exato, `stringFacet` serve à faceta do `$searchMeta`.

## O que o módulo não alega

A página diz isto em voz alta, e este documento também: o MongoDB responde
*predicados* geoespaciais — está dentro, cruza, o que há por perto. Ele não tem
álgebra de geometria (sem buffer, união, interseção ou área), só WGS84 sem
reprojeção, e nada de raster, topologia ou roteamento. O `$geoNear` precisa ser
o primeiro estágio do pipeline, e o `filter` do `$vectorSearch` não aceita
operadores geoespaciais de forma alguma. Cargas que exigem construção de
geometria, topologia, roteamento ou análise GIS pesada precisam de um sistema
geoespacial dedicado.
