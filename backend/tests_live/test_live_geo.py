"""Testes live contra um banco `*_test` real (somente leitura).

Fora do `testpaths` de propósito: a suíte offline (`backend/tests`) troca o
`MONGO_URI` por um stub antes de importar o driver. Rode à parte, com o banco
de teste já semeado (`GEO_DB=geo_test python scripts/seed_geo.py` e
`GEO_DB=geo_test ./scripts/create_search_index_geo.sh`):

    GEO_LIVE=1 GEO_DB=geo_test backend/venv/bin/python -m pytest backend/tests_live

Nenhum teste escreve: todos os endpoints da PoV são de leitura.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND / ".env")

if os.getenv("GEO_LIVE") != "1":
    pytest.skip("defina GEO_LIVE=1 para rodar contra o cluster", allow_module_level=True)
if not os.getenv("GEO_DB", "").endswith("_test"):
    pytest.skip("GEO_DB precisa ser um banco *_test", allow_module_level=True)
if not os.getenv("MONGO_URI"):
    pytest.skip("MONGO_URI ausente", allow_module_level=True)

sys.path.insert(0, str(BACKEND))
from routers import geo  # noqa: E402

SAO_PAULO = [-46.6333, -23.5505]


def test_explain_compare_usa_ixscan_e_o_composto_examina_menos_chaves():
    """A prova do IXSCAN sai do cluster, não do README."""
    cliente = sorted(geo._clientes_plantados())[0]
    r = geo.explain_compare(geo.ExplainRequest(clienteId=cliente, raioKm=2000, centro=SAO_PAULO))
    composto, puro = r["planos"]
    assert "IXSCAN" in composto["estagios"] and "IXSCAN" in puro["estagios"]
    assert "COLLSCAN" not in composto["estagios"] + puro["estagios"]
    assert composto["indice_usado"] == geo.INDICE_COMPOSTO
    assert puro["indice_usado"] == geo.INDICE_GEO_PURO
    assert composto["nReturned"] == puro["nReturned"]
    # Igualdade antes do geo: ordens de grandeza menos chaves examinadas.
    assert composto["totalKeysExamined"] * 100 < puro["totalKeysExamined"]


def test_geonear_roda_na_colecao_principal_e_bate_com_o_circulo():
    """`key: "local"` basta; contagem igual ao `$geoWithin` com `$centerSphere`."""
    raio_km = 50
    r = geo.operadores_geo(geo.OperadoresRequest(centro=SAO_PAULO, raioKm=raio_km, limite=5))
    por_operador = {x["operador"]: x for x in r["resultados"]}
    geonear = por_operador["$geoNear"]
    assert "erro" not in geonear, geonear.get("erro")
    assert geonear["colecao"] == geo.GEO_COLECAO
    circulo = geo.colecao.count_documents(
        {"local": {"$geoWithin": {"$centerSphere": [SAO_PAULO, raio_km / geo.RAIO_TERRA_KM]}}}
    )
    assert geonear["contagem"] == circulo > 0
    distancias = [a["distanciaMetros"] for a in geonear["amostra"]]
    assert distancias == sorted(distancias) and max(distancias) <= raio_km * 1000
    # Sobre pontos, conter e intersectar coincidem.
    assert por_operador["$geoWithin"]["contagem"] == por_operador["$geoIntersects"]["contagem"]
    # O quadrado contém o círculo inscrito.
    assert por_operador["$geoWithin"]["contagem"] >= circulo


def test_impossible_travel_acha_os_pares_plantados_a_900_kmh():
    r = geo.impossible_travel(limiteKmh=900.0, clienteId=None, limite=500)
    gab = r["gabarito_sintetico"]
    assert gab["plantados"] == 40
    assert gab["plantados_encontrados"] == 40
    assert gab["emergentes"] == 0
    assert r["seletividade"]["pares_avaliados"] == 148_000
    assert all(x["kmh"] > 900 for x in r["resultados"] if x["classificacao"] == "sinalizada")
    assert all(x["kmh"] <= 900 for x in r["resultados"] if x["classificacao"] == "nao_sinalizada")


def test_recorte_por_cliente_examina_so_o_cliente():
    cliente = sorted(geo._clientes_plantados())[0]
    r = geo.impossible_travel(limiteKmh=900.0, clienteId=cliente, limite=50)
    assert r["seletividade"]["pares_avaliados"] == 74  # 75 compras → 74 pares
    assert r["encontrados"] == 1
    assert r["gabarito_sintetico"] is None


def test_search_respeita_o_raio_e_devolve_facetas():
    raio_km = 25
    r = geo.geo_search(geo.SearchRequest(termo="padaria", centro=SAO_PAULO, raioKm=raio_km, limite=10))
    assert r["estado"] == "ok", r.get("mensagem")
    assert r["resultados"]
    for item in r["resultados"]:
        # O `geoWithin` do Search usa círculo; a distância vem do haversine em MQL.
        assert item["km_do_centro"] <= raio_km + 0.5
        assert "padaria" in item["estabelecimento"]["nome"].lower()
    facetas = r["meta"]["facet"]
    assert facetas["uf"]["buckets"][0]["_id"] == "SP"
    assert r["meta"]["count"]["lowerBound"] >= len(r["resultados"])


def test_rotas_separam_conter_de_intersectar():
    r = geo.comparar_rotas(lng=SAO_PAULO[0], lat=SAO_PAULO[1], raioKm=50)
    ids = {x["operador"]: x["ids"] for x in r["resultados"]}
    assert ids["$geoWithin"] == ["A"]
    assert set(ids["$geoIntersects"]) == {"A", "B"}
    assert math.isfinite(r["ms"])


def test_geocerca_nativo_e_search_dao_a_mesma_resposta():
    """Painel 04: mesma geocerca, os dois motores, terminal a terminal (ADR 0003)."""
    assert geo._estado_search_index(geo.GEO_GEOCERCA_INDEX)[0], "rode scripts/create_search_index_geo.sh"
    r = geo.geocerca_comparar(geo.GeocercaRequest(
        centro=SAO_PAULO, raioKm=15, categoria="farmácia", termo="drogaria", execucoes=1))
    assert r["nativo"]["n_terminais"] > 0
    assert r["comparacao"]["mesmas_compras"] is True
    assert r["nativo"]["plano"]["indice_usado"] == "categoria_local_idx"
    rel = r["search"]["relevancia"]
    assert rel["resultados"] and all(x["score"] > 0 for x in rel["resultados"])
    assert rel["plano"]["ms_servidor"] is not None


def test_geocerca_grande_densificada_alinha_os_dois_motores():
    """Borda cartesiana (Search) × geodésica (2dsphere): densificar alinha."""
    sorocaba = next(m for m in geo._municipios() if m["municipio"] == "Sorocaba")["centro"]
    r = geo.geocerca_comparar(geo.GeocercaRequest(
        centro=sorocaba, raioKm=600, categoria="farmácia", execucoes=1, densificar=True))
    assert r["vertices"] > 100
    assert r["comparacao"]["mesmas_compras"] is True
