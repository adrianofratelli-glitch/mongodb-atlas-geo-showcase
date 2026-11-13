# Changelog

## Unreleased

- `start.sh`: launcher único (backend 8184 + frontend 5184, primeiro plano, limpeza da árvore no SIGTERM, portas sobrescrevíveis por `POV_BACKEND_PORT`/`POV_FRONTEND_PORT`); a PoV entra no catálogo do PoV Portfolio como `geo`. Teste do contrato em `backend/tests/test_start_sh.py`.
- UI sem overflow horizontal em 320 px (badge longo quebra linha; cards do painel 03 com `min-width` relativo), achado pelo `browser_stress.mjs` do Portal.
- `$geoNear` roda na própria `transacoes` com `key: "local"` (medido no 9.0.7: mesmo resultado da cópia); `transacoes_geonear` aposentada, card degrada sozinho se o servidor recusar (ADR 0001).
- Painel 03 na tela: explain medido de dois índices (64 vs 128.153 chaves) e `$search` com texto, `near`, raio e facetas (ADR 0002).
- Investigação confere a regra contra o gabarito do gerador (40/40 plantados a 900 km/h), sem chamar isso de precisão/recall.
- Manifesto de plantados em `demo_metadata`; seed em `*_test` não reescreve `fraud_seeds.json`. `create_search_index_geo.sh` aceita `GEO_DB` do ambiente.
- Testes live (`backend/tests_live`, `GEO_LIVE=1`) e `scripts/bench_geo.py` com latência medida no README.

- Atualiza dependências compatíveis e pisos de segurança; alinha metadados de versão entre aplicação e frontend.
- Reserva backend 8184, corrige CORS para 5184 e completa o índice do briefing.

- UI: layout MongoDB 2026 "Dark Stage v4" (tokens mais escuros, Special Gothic / Source Code Pro locais, motivos de escada e grade, movimento escalonado).

## 1.0.0 (2026-09-30)

First public release.

- Repository rebuilt with a clean, single-commit history.
- English README and repository description, with screenshots captured against a real Atlas cluster.
- MIT license.
- Internal notes, presentation decks, test-output snapshots, and tooling configuration removed from the repository.
