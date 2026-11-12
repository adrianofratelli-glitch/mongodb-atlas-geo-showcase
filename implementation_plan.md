# Geo Showcase — briefing de construção

PoV standalone de consultas geoespaciais no Atlas, sem LLM. A interface
compara investigação retrospectiva e operadores geoespaciais; não representa
decisão de fraude nem benchmark de capacidade.

| Referência | Conteúdo |
|---|---|
| [Arquitetura](docs/briefing/architecture.md) | Backend, interface, modelagem e limites |
| [Queries](docs/briefing/queries.md) | Pipelines reais, índices e geometria |
| [Fluxos](docs/briefing/ui-flows.md) | Painéis e roteiro de apresentação |
| [README](README.md) | Instalação, execução e latência medida |
| [ADRs](docs/adr/) | `$geoNear` com `key`; painel 03 (explain e busca na tela) |

Portas dedicadas: frontend `127.0.0.1:5184`, backend `127.0.0.1:8184`.
O proxy de `/api` remove esse prefixo antes de encaminhar ao backend.
Esta PoV permanece fora do catálogo do launcher; as portas são reservadas
também no registro do workspace.

Validação local: `backend/venv/bin/python -m pytest backend/tests`,
`npm --prefix frontend run build` e `node --test frontend/tests/*.test.mjs`.
Testes unitários usam MongoDB simulado. Contra o cluster, num banco `*_test`
semeado: `GEO_LIVE=1 GEO_DB=geo_test backend/venv/bin/python -m pytest
backend/tests_live` e `GEO_DB=geo_test backend/venv/bin/python
scripts/bench_geo.py` (latência). Decisões em `docs/adr/`.
