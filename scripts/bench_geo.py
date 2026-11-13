#!/usr/bin/env python3
"""Mede latência dos fluxos da PoV contra o cluster (somente leitura).

Para cada fluxo: tempo de parede (aplicação → Atlas → aplicação, p50/p95 em N
execuções quentes) e tempo no servidor lido do `explain("executionStats")`. A
diferença entre os dois é rede: medir só a parede faz um recorte de 2 ms no
servidor parecer lento quando o RTT é de centenas de ms.

    GEO_DB=geo_test backend/venv/bin/python scripts/bench_geo.py --runs 7

Geocerca do painel 04 (ADR 0003), só ela, com a varredura de municípios:

    GEO_DB=geo_test backend/venv/bin/python scripts/bench_geo.py --geocerca --varredura --runs 5

`--geocerca` mede o nativo e o Search com o MESMO trabalho (polígono +
categoria + `$group`, sem texto) e, à parte, o custo extra da relevância
(`compound` com `should: text`). `--varredura` compara a resposta dos dois
motores em todos os municípios × 8/60/600 km, com e sem densificar.

Lê `backend/.env`; a variável de ambiente `GEO_DB` vence o arquivo. Não grava nada.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / "backend" / ".env")
sys.path.insert(0, str(RAIZ / "backend"))

from routers import geo  # noqa: E402

SAO_PAULO = [-46.6333, -23.5505]


def _parede(fn, runs: int) -> tuple[float, float]:
    fn()  # aquece cache e conexão
    tempos = []
    for _ in range(runs):
        inicio = time.perf_counter()
        fn()
        tempos.append((time.perf_counter() - inicio) * 1000)
    tempos.sort()
    p95 = tempos[min(len(tempos) - 1, round(0.95 * (len(tempos) - 1)))]
    return statistics.median(tempos), p95


def _servidor_aggregate(colecao: str, pipeline: list[dict]) -> float | None:
    explain = geo.banco.command({
        "explain": {"aggregate": colecao, "pipeline": pipeline, "cursor": {}, "allowDiskUse": True},
        "verbosity": "executionStats",
    })
    estagios = explain.get("stages")
    if estagios:
        return estagios[-1].get("executionTimeMillisEstimate")
    return explain.get("executionStats", {}).get("executionTimeMillis")


def _servidor_find(filtro: dict) -> float | None:
    explain = geo.banco.command({
        "explain": {"find": geo.GEO_COLECAO, "filter": filtro},
        "verbosity": "executionStats",
    })
    return explain.get("executionStats", {}).get("executionTimeMillis")


CASOS_GEOCERCA = [("São Paulo", 8, False), ("São Paulo", 15, False), ("São Paulo", 60, False),
                  ("Sorocaba", 600, False), ("Sorocaba", 600, True)]
TAMANHOS_VARREDURA = (8, 60, 600)


def _centro(municipio: str) -> list[float]:
    """O mesmo centro que o select da tela usa (`GET /geo/municipios`)."""
    return next(m["centro"] for m in geo._municipios() if m["municipio"] == municipio)


def _poligono(municipio: str, raio: float, densificar: bool) -> dict:
    poligono = geo._poligono_geocerca(_centro(municipio), raio)
    return geo._densificar_anel(poligono) if densificar else poligono


def _servidor_mediana(pipeline: list[dict], runs: int) -> float:
    return statistics.median(_servidor_aggregate(geo.GEO_COLECAO, pipeline) for _ in range(runs))


def bench_geocerca(runs: int, categoria: str = "farmácia", termo: str = "drogaria") -> None:
    ok, msg = geo._estado_search_index(geo.GEO_GEOCERCA_INDEX)
    if not ok:
        print(f"geocerca: Search indisponível ({msg})")
        return
    print(f"\nGeocerca · categoria {categoria} · mesmo trabalho nos dois motores (sem texto) · "
          f"servidor = mediana de {runs} explains · parede p50 de {runs} execuções\n")
    print("| geocerca | vértices | terminais nativo / Search | mesma resposta | nativo servidor (ms) | "
          "Search servidor (ms) | Search ÷ nativo | nativo parede p50 (ms) | Search parede p50 (ms) | "
          f"relevância \"{termo}\" servidor (ms) |")
    print("|---|---:|---:|---|---:|---:|---:|---:|---:|---:|")
    for municipio, raio, densificar in CASOS_GEOCERCA:
        poligono = _poligono(municipio, raio, densificar)
        pipes = geo._pipelines_geocerca(poligono, categoria, termo)
        nativo = list(geo.colecao.aggregate(pipes["nativo"]))
        search = list(geo.colecao.aggregate(pipes["search"]))
        cmp = geo.comparar_terminais(nativo, search)
        p50_n, _ = _parede(lambda: list(geo.colecao.aggregate(pipes["nativo"])), runs)
        p50_s, _ = _parede(lambda: list(geo.colecao.aggregate(pipes["search"])), runs)
        srv_n = _servidor_mediana(pipes["nativo"], runs)
        srv_s = _servidor_mediana(pipes["search"], runs)
        srv_r = _servidor_mediana(pipes["relevancia"], runs)
        igual = "sim" if cmp["mesmas_compras"] else f"não ({len(cmp['so_search'])} só Search, {len(cmp['so_nativo'])} só nativo)"
        rotulo = f"{municipio} ≈ {raio} km" + (", densificada" if densificar else "")
        print(f"| {rotulo} | {len(poligono['coordinates'][0]) - 1} | {len(nativo)} / {len(search)} | {igual} | "
              f"{srv_n:.0f} | {srv_s:.0f} | {srv_s / max(srv_n, 1):.1f}× | {p50_n:.0f} | {p50_s:.0f} | {srv_r:.0f} |")


def varredura_geocerca(categoria: str = "farmácia") -> None:
    ok, msg = geo._estado_search_index(geo.GEO_GEOCERCA_INDEX)
    if not ok:  # sem índice READY o $search volta vazio e a varredura acusaria divergência falsa
        print(f"varredura: Search indisponível ({msg})")
        return
    municipios = [m["municipio"] for m in geo._municipios()]
    print(f"\nVarredura · {len(municipios)} municípios × {TAMANHOS_VARREDURA} km · categoria {categoria}\n")
    for densificar in (False, True):
        casos = divergentes = 0
        detalhes = []
        for municipio in municipios:
            for raio in TAMANHOS_VARREDURA:
                pipes = geo._pipelines_geocerca(_poligono(municipio, raio, densificar), categoria)
                cmp = geo.comparar_terminais(list(geo.colecao.aggregate(pipes["nativo"])),
                                             list(geo.colecao.aggregate(pipes["search"])))
                casos += 1
                if not cmp["mesmas_compras"]:
                    divergentes += 1
                    detalhes.append(f"{municipio} {raio} km: só Search {cmp['so_search']}, só nativo {cmp['so_nativo']}")
        print(f"- {'densificada' if densificar else 'sem densificar'}: mesma resposta em "
              f"{casos - divergentes}/{casos}" + (f"; divergentes: {'; '.join(detalhes)}" if detalhes else ""))


def main() -> int:
    parser = argparse.ArgumentParser(description="Latência dos fluxos Geo (somente leitura)")
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--geocerca", action="store_true", help="só a geocerca do painel 04")
    parser.add_argument("--varredura", action="store_true", help="compara a resposta em todos os municípios")
    args = parser.parse_args()

    geo.client.admin.command("ping")
    rtt, _ = _parede(lambda: geo.client.admin.command("ping"), args.runs)
    versao = geo.client.server_info().get("version")
    cliente = sorted(geo._clientes_plantados())[0]

    def it_colecao():
        return geo.impossible_travel(limiteKmh=900.0, clienteId=None, limite=50)

    def it_cliente():
        return geo.impossible_travel(limiteKmh=900.0, clienteId=cliente, limite=50)

    operadores = geo.OperadoresRequest(centro=SAO_PAULO, raioKm=50, limite=5)
    ponto = {"type": "Point", "coordinates": SAO_PAULO}
    busca = geo.SearchRequest(termo="padaria", centro=SAO_PAULO, raioKm=25, limite=10)
    within = {"local": {"$geoWithin": {"$geometry": geo._poligono_quadrado(SAO_PAULO, 50)}}}

    linhas = [
        ("impossible-travel · coleção inteira", it_colecao,
         lambda: _servidor_aggregate(geo.GEO_COLECAO, it_colecao()["pipeline"])),
        ("impossible-travel · um cliente", it_cliente,
         lambda: _servidor_aggregate(geo.GEO_COLECAO, it_cliente()["pipeline"])),
        ("$geoWithin · count 50 km (SP)", lambda: geo.colecao.count_documents(within),
         lambda: _servidor_find(within)),
        ("$geoNear · 50 km (SP)", lambda: geo._geo_near_resultado(ponto, 50, 5),
         lambda: _servidor_aggregate(geo.GEO_COLECAO, geo._geo_near_resultado(ponto, 50, 5)["query"])),
        ("operadores · 5 consultas", lambda: geo.operadores_geo(operadores), lambda: None),
        ("$search texto + raio · 25 km", lambda: geo.geo_search(busca),
         lambda: _servidor_aggregate(geo.GEO_COLECAO, geo.geo_search(busca)["pipeline"])),
    ]

    print(f"MongoDB {versao} · banco {geo.GEO_DB} · {args.runs} execuções quentes · RTT (ping) p50 {rtt:.0f} ms\n")
    if args.geocerca:
        bench_geocerca(args.runs)
        if args.varredura:
            varredura_geocerca()
        return 0
    print("| fluxo | parede p50 (ms) | parede p95 (ms) | servidor (ms, explain) |")
    print("|---|---:|---:|---:|")
    for nome, fn, servidor in linhas:
        p50, p95 = _parede(fn, args.runs)
        try:
            srv = servidor()
        except Exception as exc:  # noqa: BLE001 - explain de $search pode não expor tempo
            srv = f"n/d ({type(exc).__name__})"
        srv_txt = "—" if srv is None else (f"{srv:.0f}" if isinstance(srv, (int, float)) else srv)
        print(f"| {nome} | {p50:.0f} | {p95:.0f} | {srv_txt} |")
    bench_geocerca(args.runs)
    if args.varredura:
        varredura_geocerca()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
