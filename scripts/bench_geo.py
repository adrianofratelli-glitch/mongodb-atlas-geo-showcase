#!/usr/bin/env python3
"""Mede latência dos fluxos da PoV contra o cluster (somente leitura).

Para cada fluxo: tempo de parede (aplicação → Atlas → aplicação, p50/p95 em N
execuções quentes) e tempo no servidor lido do `explain("executionStats")`. A
diferença entre os dois é rede: medir só a parede faz um recorte de 2 ms no
servidor parecer lento quando o RTT é de centenas de ms.

    GEO_DB=geo_test backend/venv/bin/python scripts/bench_geo.py --runs 7

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


def main() -> int:
    parser = argparse.ArgumentParser(description="Latência dos fluxos Geo (somente leitura)")
    parser.add_argument("--runs", type=int, default=7)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
