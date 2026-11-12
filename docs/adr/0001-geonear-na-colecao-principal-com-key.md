# ADR 0001 — `$geoNear` na coleção principal com `key: "local"`

- Status: aceito (2026-11-12)
- Substitui: a cópia `transacoes_geonear` criada pelo seed

## Contexto

`geo.transacoes` tem três índices 2dsphere sobre `local`, de propósito:
`local_2dsphere_idx` (puro), `cliente_status_local_idx` (composto do painel de
explain) e `categoria_local_idx`. Sem `key`, o servidor recusa o `$geoNear`
("There is more than one 2dsphere index ... unsure which to use"). A versão
anterior concluiu que nenhuma forma de escolher o índice resolvia e passou a
manter `transacoes_geonear`, uma cópia `$out` de 150 mil documentos com índice
único, só para esse operador.

## Medição (MongoDB 9.0.7, banco `geo_test`, 150 mil docs, raio de 50 km em São Paulo)

| forma | resultado |
|---|---|
| `$geoNear` sem `key` em `transacoes` | recusado (mais de um índice 2dsphere) |
| `$geoNear` com `key: "local"` em `transacoes` | roda; usa `local_2dsphere_idx`; 39.019 docs; 7.445 docs examinados |
| `$geoNear` em `transacoes_geonear` (cópia) | 39.019 docs; 7.445 docs examinados; mesmos 5 primeiros |

Reproduzível com `GEO_LIVE=1 GEO_DB=geo_test backend/venv/bin/python -m pytest backend/tests_live`
(`test_geonear_roda_na_colecao_principal_e_bate_com_o_circulo`): a contagem
do `$geoNear` é igual à do `$geoWithin` com `$centerSphere` no mesmo raio.

## Decisão

- `_geo_near_resultado` roda em `transacoes` com `key: "local"`. O resultado
  traz `colecao: "transacoes"`.
- Se o servidor recusar, só o card do `$geoNear` degrada e mostra o erro. Os
  outros quatro operadores continuam.
- `scripts/seed_geo.py` deixa de criar a cópia, e `--check` deixa de exigi-la.
  Bancos que já a têm não são tocados; apagá-la é decisão manual.

## Consequências

- Uma coleção a menos para manter em sincronia e 150 mil documentos a menos
  por seed.
- A armadilha passa a ser ensinada como ela é: com mais de um índice 2dsphere
  no campo, `key` diz qual usar.
- O invariante do `AGENTS.md` ("`$geoNear` roda em `transacoes_geonear`") fica
  desatualizado. Ele mora em `_shared/agent-config` e precisa ser corrigido lá.
