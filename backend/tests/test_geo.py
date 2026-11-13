from __future__ import annotations

import importlib.util
import math
import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND = Path(__file__).resolve().parents[1]
RAIZ = BACKEND.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("MONGO_URI", "mongodb://127.0.0.1:27017")

from routers import geo  # noqa: E402


def _carregar_seed():
    """O seed vive em scripts/, fora do pacote do backend."""
    caminho = RAIZ / "scripts" / "seed_geo.py"
    spec = importlib.util.spec_from_file_location("seed_geo", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


seed_geo = _carregar_seed()


@pytest.fixture(autouse=True)
def _manifesto_isolado(monkeypatch):
    """Nenhum teste offline toca o banco para ler o manifesto de plantados."""
    monkeypatch.setattr(geo, "_manifesto_cache", None)
    monkeypatch.setattr(geo, "_manifesto", lambda: {})


# ── Demo A ──────────────────────────────────────────────────────────────────
def test_resumo_plano_le_o_plano_aninhado_do_sbe():
    explain = {
        "queryPlanner": {"winningPlan": {"queryPlan": {
            "stage": "FETCH",
            "inputStage": {"stage": "IXSCAN", "indexName": "cliente_status_local_idx"},
        }}},
        "executionStats": {
            "nReturned": 3, "executionTimeMillis": 7,
            "totalKeysExamined": 12, "totalDocsExamined": 3,
        },
    }
    resumo = geo._resumo_plano(explain)
    assert resumo["estagios"] == ["FETCH", "IXSCAN"]
    assert resumo["estagio_vencedor"] == "FETCH"
    assert resumo["indice_usado"] == "cliente_status_local_idx"
    assert resumo["totalKeysExamined"] == 12


def test_resumo_plano_percorre_inputstages_de_um_or():
    explain = {"queryPlanner": {"winningPlan": {
        "stage": "OR",
        "inputStages": [{"stage": "IXSCAN", "indexName": "local_2dsphere_idx"}],
    }}}
    assert geo._resumo_plano(explain)["indice_usado"] == "local_2dsphere_idx"


def test_explain_compare_rejeita_centro_fora_do_intervalo(monkeypatch):
    monkeypatch.setattr(geo, "_explain_find", lambda *_a, **_k: {})
    pedido = geo.ExplainRequest(clienteId="CLI00000", centro=[-200.0, 0.0])
    with pytest.raises(HTTPException) as exc:
        geo.explain_compare(pedido)
    assert exc.value.status_code == 422


def test_explain_compare_usa_os_dois_hints(monkeypatch):
    usados = []

    def falso_explain(filtro, hint):
        usados.append(hint)
        assert "$geoWithin" in filtro["local"]
        return {"totalKeysExamined": 1}

    monkeypatch.setattr(geo, "_explain_find", falso_explain)
    resposta = geo.explain_compare(
        geo.ExplainRequest(clienteId="CLI00000", raioKm=50, centro=[-46.63, -23.55])
    )
    assert usados == [geo.INDICE_COMPOSTO, geo.INDICE_GEO_PURO]
    assert len(resposta["planos"]) == 2


# ── Demo B ──────────────────────────────────────────────────────────────────
def test_impossible_travel_monta_setwindowfields_e_haversine(monkeypatch):
    capturado = {}

    class FalsaColecao:
        def aggregate(self, pipeline, **_kwargs):
            capturado["pipeline"] = pipeline
            return iter([])

        def estimated_document_count(self):
            return 150_000

    monkeypatch.setattr(geo, "colecao", FalsaColecao())
    resposta = geo.impossible_travel(limiteKmh=900, clienteId="CLI00007")
    pipeline = resposta["pipeline"]
    estagios = [chave for etapa in pipeline for chave in etapa]

    assert pipeline[0] == {"$match": {"clienteId": "CLI00007"}}
    assert "$setWindowFields" in estagios
    janela = next(e["$setWindowFields"] for e in pipeline if "$setWindowFields" in e)
    assert janela["partitionBy"] == "$clienteId"
    assert janela["sortBy"] == {"ts": 1}
    assert set(janela["output"]) == {
        "ts_ant", "coord_ant", "municipio_ant", "uf_ant", "dispositivo_ant", "localizacao_meta_ant",
    }
    # O cálculo tem de ficar no cluster: nada de $function.
    assert "$function" not in str(pipeline)
    assert "$degreesToRadians" in str(pipeline) and "$asin" in str(pipeline)
    assert resposta["limite_kmh"] == 900
    assert resposta["natureza"] == "sinal_de_risco_retrospectivo"
    assert resposta["decisao_fraude"] is False


def test_haversine_cabe_em_uma_unica_stage():
    """Quatro $addFields encadeados custavam quatro passadas sobre a janela."""
    stages = geo._haversine_stages("km", 1, 2, 3, 4)
    assert len(stages) == 1
    externo = stages[0]["$addFields"]["km"]["$let"]
    assert set(externo["vars"]) == {"phi1", "phi2", "dphi", "dlmb"}
    interno = externo["in"]["$let"]
    assert interno["in"]["$multiply"][0] == pytest.approx(2 * geo.RAIO_TERRA_KM)
    # $min contra 1 evita que arredondamento estoure o domínio do $asin.
    assert interno["in"]["$multiply"][1]["$asin"]["$sqrt"] == {"$min": ["$$a", 1]}


def test_impossible_travel_corta_pelo_limite_geometrico(monkeypatch):
    """Nenhum par na Terra dista mais que meia circunferência: intervalos longos
    não podem violar o limite, e são descartados antes do haversine."""

    class FalsaColecao:
        def aggregate(self, pipeline, **_kwargs):
            return iter([])

        def estimated_document_count(self):
            return 150_000

    monkeypatch.setattr(geo, "colecao", FalsaColecao())
    pipeline = geo.impossible_travel(limiteKmh=900, clienteId=None)["pipeline"]

    # O corte vive no ramo de sinais do $facet: o ramo `avaliados` precisa contar
    # os pares ANTES dele, senão o denominador da taxa de sinalização seria o
    # subconjunto que já passou pelo filtro — e a taxa daria sempre alta.
    facet = next(e["$facet"] for e in pipeline if "$facet" in e)
    assert facet["avaliados"] == [{"$count": "pares"}]
    ramo = facet["sinais"]

    corte = next(e["$match"]["minutos"] for e in ramo
                 if "$match" in e and "minutos" in e["$match"])
    esperado = (math.pi * geo.RAIO_TERRA_KM / 900) * 60
    assert corte["$gt"] == 0
    assert corte["$lt"] == pytest.approx(esperado)
    # O corte precisa vir antes da parte cara.
    indice_corte = next(i for i, e in enumerate(ramo)
                        if "$match" in e and "minutos" in e["$match"])
    indice_haversine = next(i for i, e in enumerate(ramo)
                            if "$addFields" in e and "km" in e["$addFields"])
    assert indice_corte < indice_haversine
    # O $setWindowFields, que é a parte cara, roda uma vez só — antes do $facet.
    assert any("$setWindowFields" in e for e in pipeline)
    assert not any("$setWindowFields" in e for e in ramo)


# ── Demo C ──────────────────────────────────────────────────────────────────
def test_search_degrada_sem_index(monkeypatch):
    monkeypatch.setattr(geo, "_search_disponivel", lambda: (False, "índice ausente"))
    resposta = geo.geo_search(geo.SearchRequest(termo="padaria", centro=[-46.63, -23.55]))
    assert resposta["estado"] == "nao_configurado"
    assert "resultados" not in resposta


def test_search_filtra_por_geowithin_em_metros(monkeypatch):
    capturado = []

    class FalsaColecao:
        def aggregate(self, pipeline, **_kwargs):
            capturado.append(pipeline)
            return iter([])

    monkeypatch.setattr(geo, "_search_disponivel", lambda: (True, "ok"))
    monkeypatch.setattr(geo, "colecao", FalsaColecao())
    resposta = geo.geo_search(geo.SearchRequest(
        termo="padaria", centro=[-46.63, -23.55], raioKm=25, categorias=["alimentação"],
    ))

    search = resposta["pipeline"][0]["$search"]
    filtros = search["compound"]["filter"]
    circulo = filtros[0]["geoWithin"]["circle"]
    assert circulo["radius"] == 25_000  # o operador usa metros, a UI fala em km
    assert circulo["center"]["coordinates"] == [-46.63, -23.55]
    assert filtros[1]["in"]["value"] == ["alimentação"]
    assert search["compound"]["must"][0]["text"]["fuzzy"] == {"maxEdits": 1}
    # A distância volta calculada para o raio ser verificável sem confiar no operador.
    assert "km_do_centro" in str(resposta["pipeline"])
    grupo = next(e["$group"] for e in resposta["pipeline"] if "$group" in e)
    assert grupo["_id"] == "$dispositivo.id"
    assert next(i for i, e in enumerate(resposta["pipeline"]) if "$group" in e) < next(
        i for i, e in enumerate(resposta["pipeline"]) if "$limit" in e
    )
    assert "$searchMeta" in resposta["pipeline_meta"][0]


def test_search_rejeita_centro_invalido(monkeypatch):
    monkeypatch.setattr(geo, "_search_disponivel", lambda: (True, "ok"))
    with pytest.raises(HTTPException) as exc:
        geo.geo_search(geo.SearchRequest(termo="x", centro=[0.0, 999.0]))
    assert exc.value.status_code == 422


# ── Seed ────────────────────────────────────────────────────────────────────
def test_seed_e_deterministico():
    """Idempotência depende disso: mesmo endToEndId a cada execução."""
    a, _ = seed_geo.gerar(clientes=5, por_cliente=8, fraudes=2)
    b, _ = seed_geo.gerar(clientes=5, por_cliente=8, fraudes=2)
    assert [d["endToEndId"] for d in a] == [d["endToEndId"] for d in b]
    assert len({d["endToEndId"] for d in a}) == len(a) == 40
    assert all(d["datasetVersion"] == seed_geo.VERSAO_DATASET for d in a)
    # A coordenada é do terminal do adquirente, não do aparelho: é isso que
    # torna o impossible travel um sinal forte em vez de um palpite sobre GPS.
    assert all(d["dispositivo"]["canal"] == "POS_PRESENCIAL" for d in a)
    assert all(d["localizacaoMeta"]["origem"] == "TERMINAL_ADQUIRENTE" for d in a)
    assert all(d["localizacaoMeta"]["qualidade"] == "CADASTRAL" for d in a)
    assert all("precisaoMetros" not in d["localizacaoMeta"] for d in a)
    assert all(d["tipo"].startswith("CARTAO_") for d in a)
    assert all(d["localizacaoMeta"]["capturadaEm"] <= d["ts"] for d in a)
    # Um terminal cadastrado é entidade estável: quando reaparece, localização
    # e estabelecimento não podem mudar de uma compra para outra.
    terminais = {}
    for documento in a:
        chave = documento["dispositivo"]["id"]
        identidade = (documento["estabelecimento"]["nome"], documento["local"]["coordinates"])
        assert terminais.setdefault(chave, identidade) == identidade


def test_dataset_atual_exige_volume_e_versao(monkeypatch):
    class FalsaColecao:
        def __init__(self, total, divergente):
            self.total = total
            self.divergente = divergente

        def count_documents(self, _filtro):
            return self.total

        def find_one(self, filtro, projecao):
            assert filtro == {"datasetVersion": {"$ne": seed_geo.VERSAO_DATASET}}
            assert projecao == {"_id": 1}
            return self.divergente

    class ManifestoPresente:
        @staticmethod
        def exists():
            return True

        @staticmethod
        def read_text(encoding):
            assert encoding == "utf-8"
            return ('{"dataset_version": %d, "semente": 20260726}'
                        % seed_geo.VERSAO_DATASET)

    monkeypatch.setattr(seed_geo, "ARQUIVO_FRAUDES", ManifestoPresente())
    assert seed_geo.dataset_atual(FalsaColecao(40, None), 40)[0] is True
    assert seed_geo.dataset_atual(FalsaColecao(39, None), 40)[0] is False
    assert seed_geo.dataset_atual(FalsaColecao(40, {"_id": 1}), 40)[0] is False


def test_preflight_geo_e_read_only_e_exige_search_ready(monkeypatch):
    class Metadata:
        def find_one(self, filtro):
            assert filtro == {"_id": seed_geo.ID_METADATA}
            return {
                "datasetVersion": seed_geo.VERSAO_DATASET,
                "semente": seed_geo.SEMENTE,
                "documentos": 40,
            }

    class Banco:
        def __getitem__(self, nome):
            # Só o metadata: a antiga cópia transacoes_geonear não é mais exigida.
            assert nome == "demo_metadata"
            return Metadata()

    class Colecao:
        def estimated_document_count(self):
            return 40

        def list_indexes(self):
            return [{"name": nome} for nome in seed_geo.INDICES_OBRIGATORIOS]

        def list_search_indexes(self, nome):
            assert nome in {"idx_geo_estabelecimento", "idx_geo_geocerca"}
            return [{"name": nome, "status": "READY", "queryable": True}]

    monkeypatch.delenv("GEO_SEARCH_INDEX", raising=False)
    monkeypatch.delenv("GEO_GEOCERCA_INDEX", raising=False)
    pronto, problemas = seed_geo.verificar_prontidao(Banco(), Colecao(), 40)
    assert pronto is True
    assert problemas == []


def test_seed_planta_pares_acima_do_limite():
    documentos, plantados = seed_geo.gerar(clientes=40, por_cliente=10, fraudes=40)
    assert len(plantados) == 40

    por_cliente: dict[str, list[dict]] = {}
    for doc in documentos:
        por_cliente.setdefault(doc["clienteId"], []).append(doc)

    for cliente in plantados:
        transacoes = sorted(por_cliente[cliente], key=lambda d: d["ts"])
        velocidades = []
        for anterior, atual in zip(transacoes, transacoes[1:]):
            horas = (atual["ts"] - anterior["ts"]).total_seconds() / 3600
            (lng1, lat1) = anterior["local"]["coordinates"]
            (lng2, lat2) = atual["local"]["coordinates"]
            km = seed_geo.haversine_km(lat1, lng1, lat2, lng2)
            velocidades.append(km / horas if horas > 0 else 0)
        assert max(velocidades) > 900, f"{cliente} não tem par acima de 900 km/h"


def test_seed_mantem_pontos_dentro_dos_clusters():
    """Coordenada uniforme no bounding box do país destruiria a credibilidade."""
    documentos, _ = seed_geo.gerar(clientes=30, por_cliente=10, fraudes=0)
    centros = {nome: (lat, lng) for nome, _uf, lat, lng, _peso in seed_geo.MUNICIPIOS}
    for doc in documentos:
        lat_c, lng_c = centros[doc["municipio"]]
        lng, lat = doc["local"]["coordinates"]
        assert seed_geo.haversine_km(lat_c, lng_c, lat, lng) < 40


def test_municipio_distante_respeita_o_minimo():
    for origem in range(len(seed_geo.MUNICIPIOS)):
        destino = seed_geo.municipio_distante(origem)
        _, _, lat1, lng1, _ = seed_geo.MUNICIPIOS[origem]
        _, _, lat2, lng2, _ = seed_geo.MUNICIPIOS[destino]
        assert seed_geo.haversine_km(lat1, lng1, lat2, lng2) >= 700


def test_haversine_km_bate_com_distancia_conhecida():
    # São Paulo ↔ Rio de Janeiro: ~357 km em linha reta.
    distancia = seed_geo.haversine_km(-23.5505, -46.6333, -22.9068, -43.1729)
    assert 350 < distancia < 365
    assert math.isclose(seed_geo.haversine_km(0, 0, 0, 0), 0, abs_tol=1e-9)


def test_impossible_travel_calcula_seletividade(monkeypatch):
    """Contar sinais sem denominador não responde "quantos alertas por dia"."""
    class FalsaColecao:
        def aggregate(self, _pipeline, **_kwargs):
            return iter([{
                "avaliados": [{"pares": 148_000}],
                "total_sinais": [{"total": 2}],
                "sinais": [
                    {"clienteId": "CLI00001", "km": 2691.6, "minutos": 5.0, "kmh": 32299.0, "ts": 2},
                    {"clienteId": "CLI99999", "km": 1200.0, "minutos": 12.0, "kmh": 6000.0, "ts": 1},
                ],
                "aprovados": [],
            }])

        def estimated_document_count(self):
            return 150_000

    monkeypatch.setattr(geo, "colecao", FalsaColecao())

    # `clienteId=None` explícito: chamada direta não passa pelo FastAPI, e o
    # default é um objeto `Query`, que é truthy.
    resposta = geo.impossible_travel(limiteKmh=900, clienteId=None)

    assert {r["clienteId"] for r in resposta["resultados"]} == {"CLI00001", "CLI99999"}
    assert all(r["classificacao"] == "sinalizada" for r in resposta["resultados"])
    assert "origem" not in resposta

    sel = resposta["seletividade"]
    assert sel["pares_avaliados"] == 148_000
    assert sel["sinalizados"] == 2
    assert sel["taxa_pct"] == pytest.approx(0.0014, abs=1e-4)
    # Arredondado para duas casas: a tela mostra "alertas por dia", não fração.
    assert sel["alertas_por_dia"] == round(2 / geo.DIAS_DATASET, 2)


def test_seletividade_por_cliente_nao_reporta_alertas_por_dia(monkeypatch):
    """Um recorte de um cliente não é base para volume operacional diário."""
    class FalsaColecao:
        def aggregate(self, _pipeline, **_kwargs):
            return iter([{"avaliados": [{"pares": 74}], "sinais": []}])

        def estimated_document_count(self):
            return 150_000

    monkeypatch.setattr(geo, "colecao", FalsaColecao())
    monkeypatch.setattr(geo, "_clientes_plantados", set)

    sel = geo.impossible_travel(limiteKmh=900, clienteId="CLI00007")["seletividade"]

    assert sel["pares_avaliados"] == 74
    assert sel["alertas_por_dia"] is None
    assert sel["janela_dias"] is None


class _BancoMetadata:
    def __init__(self, documento=None, erro=None):
        self.documento, self.erro = documento, erro

    def __getitem__(self, nome):
        assert nome == "demo_metadata"
        return self

    def find_one(self, filtro):
        assert filtro == {"_id": geo.ID_METADATA}
        if self.erro:
            raise self.erro
        return self.documento


def _manifesto_real(monkeypatch):
    """Desfaz o stub autouse para exercitar a leitura de verdade."""
    monkeypatch.setattr(geo, "_manifesto", _MANIFESTO_ORIGINAL)
    monkeypatch.setattr(geo, "_manifesto_cache", None)


_MANIFESTO_ORIGINAL = geo._manifesto


def test_clientes_plantados_sem_arquivo_nao_quebra(monkeypatch, tmp_path):
    _manifesto_real(monkeypatch)
    monkeypatch.setattr(geo, "banco", _BancoMetadata(None))
    monkeypatch.setattr(geo, "ARQUIVO_FRAUDES", tmp_path / "inexistente.json")
    assert geo._clientes_plantados() == set()


def test_manifesto_prefere_o_banco_ao_arquivo(monkeypatch, tmp_path):
    _manifesto_real(monkeypatch)
    arquivo = tmp_path / "fraud_seeds.json"
    arquivo.write_text('{"clientes": ["CLI_ARQUIVO"], "limite_kmh": 900}', encoding="utf-8")
    monkeypatch.setattr(geo, "ARQUIVO_FRAUDES", arquivo)
    monkeypatch.setattr(geo, "banco", _BancoMetadata({"clientesPlantados": ["CLI_BANCO"], "limiteKmh": 900}))
    assert geo._clientes_plantados() == {"CLI_BANCO"}
    assert geo._manifesto()["origem"] == "banco"


def test_manifesto_cai_no_arquivo_sem_banco(monkeypatch, tmp_path):
    _manifesto_real(monkeypatch)
    arquivo = tmp_path / "fraud_seeds.json"
    arquivo.write_text('{"clientes": ["CLI_ARQUIVO"], "limite_kmh": 900}', encoding="utf-8")
    monkeypatch.setattr(geo, "ARQUIVO_FRAUDES", arquivo)
    monkeypatch.setattr(geo, "banco", _BancoMetadata(erro=RuntimeError("sem cluster")))
    assert geo._clientes_plantados() == {"CLI_ARQUIVO"}
    assert geo._manifesto()["origem"] == "arquivo"


def test_impossible_travel_confere_o_gabarito_sintetico(monkeypatch):
    """Plantados encontrados e emergentes vêm do ramo sem corte da tabela."""
    capturado = {}

    class FalsaColecao:
        def aggregate(self, pipeline, **_kwargs):
            capturado["facet"] = pipeline[-1]["$facet"]
            return iter([{
                "avaliados": [{"pares": 1000}],
                "total_sinais": [{"total": 3}],
                # A tabela mostra só um, mas o gabarito usa os três clientes.
                "sinais": [{"clienteId": "CLI1", "kmh": 5000.0}],
                "clientes_sinalizados": [{"ids": ["CLI1", "CLI2", "CLI9"]}],
                "aprovados": [],
            }])

        def estimated_document_count(self):
            return 1000

    monkeypatch.setattr(geo, "colecao", FalsaColecao())
    monkeypatch.setattr(geo, "_clientes_plantados", lambda: {"CLI1", "CLI2", "CLI3"})

    r = geo.impossible_travel(limiteKmh=900, clienteId=None, limite=1)

    gab = r["gabarito_sintetico"]
    assert (gab["plantados"], gab["plantados_encontrados"], gab["emergentes"]) == (3, 2, 1)
    assert "não é precisão nem recall" in gab["nota"]
    assert r["resultados"][0]["plantado"] is True
    ramo = capturado["facet"]["clientes_sinalizados"]
    assert ramo[-1] == {"$group": {"_id": None, "ids": {"$addToSet": "$clienteId"}}}
    assert not any("$limit" in etapa or "$sort" in etapa for etapa in ramo)


def test_gabarito_nao_se_aplica_ao_recorte_por_cliente():
    assert geo._gabarito({"CLI1"}, {"CLI1"}, "CLI1") is None
    assert geo._gabarito({"CLI1"}, set(), None) is None


def test_search_sem_termo_pergunta_o_entorno_e_ordena_por_distancia(monkeypatch):
    """A investigação começa numa compra, não num termo.

    Sem consulta textual todos os documentos empatam no score, então "os mais
    relevantes" seria uma ordem arbitrária — a pergunta, aí, é geográfica.
    """
    class FalsaColecao:
        def aggregate(self, _pipeline, **_kwargs):
            return iter([])

    monkeypatch.setattr(geo, "_search_disponivel", lambda: (True, "ok"))
    monkeypatch.setattr(geo, "colecao", FalsaColecao())

    resposta = geo.geo_search(geo.SearchRequest(termo="", centro=[-46.63, -23.55], raioKm=10))

    compound = resposta["pipeline"][0]["$search"]["compound"]
    # Um compound só de `filter` devolveria tudo com score zero: precisa de ao
    # menos uma cláusula pontuável.
    assert compound["must"] == [{"exists": {"path": "estabelecimento.nome"}}]
    ordens = [e["$sort"] for e in resposta["pipeline"] if "$sort" in e]
    assert all("km_do_centro" in o for o in ordens)
    assert resposta["ordenacao"] == "distância do terminal"


def test_search_com_termo_mantem_fuzzy_e_ordena_por_relevancia(monkeypatch):
    class FalsaColecao:
        def aggregate(self, _pipeline, **_kwargs):
            return iter([])

    monkeypatch.setattr(geo, "_search_disponivel", lambda: (True, "ok"))
    monkeypatch.setattr(geo, "colecao", FalsaColecao())

    resposta = geo.geo_search(geo.SearchRequest(termo="padaria", centro=[-46.63, -23.55]))

    assert resposta["pipeline"][0]["$search"]["compound"]["must"][0]["text"]["fuzzy"] == {"maxEdits": 1}
    assert resposta["ordenacao"] == "relevância textual + proximidade (near)"


def test_search_ancorado_na_compra_usa_a_coordenada_do_terminal(monkeypatch):
    """O centro sai do terminal da compra contestada, não de um município."""
    ancora = {
        "endToEndId": "E1", "estabelecimento": {"nome": "Auto Posto", "categoria": "combustível"},
        "municipio": "Manaus", "uf": "AM", "local": {"type": "Point", "coordinates": [-60.02, -3.10]},
        "dispositivo": {"id": "POS060107"}, "valor": "40.31",
    }

    class FalsaColecao:
        def find_one(self, filtro, _projecao):
            assert filtro == {"endToEndId": "E1"}
            return dict(ancora)

        def aggregate(self, _pipeline, **_kwargs):
            return iter([{"terminalId": "POS060107", "estabelecimento": {"nome": "Auto Posto"}},
                         {"terminalId": "POS999999", "estabelecimento": {"nome": "Vizinho"}}])

    monkeypatch.setattr(geo, "_search_disponivel", lambda: (True, "ok"))
    monkeypatch.setattr(geo, "colecao", FalsaColecao())

    resposta = geo.geo_search(geo.SearchRequest(endToEndId="E1", raioKm=25))

    circulo = resposta["pipeline"][0]["$search"]["compound"]["filter"][0]["geoWithin"]["circle"]
    assert circulo["center"]["coordinates"] == [-60.02, -3.10]
    assert resposta["centro"] == [-60.02, -3.10]
    # O terminal da própria compra aparece na vizinhança e vem marcado.
    assert [r["e_a_ancora"] for r in resposta["resultados"]] == [True, False]


def test_search_sem_ancora_nem_centro_e_rejeitado(monkeypatch):
    monkeypatch.setattr(geo, "_search_disponivel", lambda: (True, "ok"))
    with pytest.raises(HTTPException) as erro:
        geo.geo_search(geo.SearchRequest(termo="padaria"))
    assert erro.value.status_code == 422


def test_ancora_inexistente_devolve_404(monkeypatch):
    class FalsaColecao:
        def find_one(self, *_a, **_k):
            return None

    monkeypatch.setattr(geo, "_search_disponivel", lambda: (True, "ok"))
    monkeypatch.setattr(geo, "colecao", FalsaColecao())
    with pytest.raises(HTTPException) as erro:
        geo.geo_search(geo.SearchRequest(endToEndId="NAO-EXISTE"))
    assert erro.value.status_code == 404


@pytest.mark.parametrize("total,esperado", [(50, False), (120, True), (0, False)])
def test_seletividade_conta_antes_do_limite_da_tabela(monkeypatch, total, esperado):
    class Colecao:
        def aggregate(self, pipeline, **kwargs):
            facet = pipeline[-1]["$facet"]
            assert not any("$limit" in stage for stage in facet["total_sinais"])
            assert facet["total_sinais"][-1] == {"$count": "total"}
            assert facet["total_sinais"][-2] == {"$match": {"kmh": {"$gt": 900}}}
            assert facet["aprovados"][0] == {"$match": {"minutos": {"$gt": 0}}}
            return iter([{"avaliados": [{"pares": 1000}],
                          "total_sinais": [{"total": total}],
                          "sinais": [{"endToEndId": str(i)} for i in range(min(total, 50))]}])
        def estimated_document_count(self):
            return 1200
    monkeypatch.setattr(geo, "colecao", Colecao())
    r = geo.impossible_travel(limiteKmh=900, clienteId=None, limite=50)
    assert r["truncado"] is esperado
    assert r["encontrados"] == min(total, 50)
    assert r["seletividade"]["sinalizados"] == total
    assert r["seletividade"]["taxa_pct"] == total / 10
    assert r["seletividade"]["alertas_por_dia"] == round(total / 90, 2)


def test_geonear_amostra_terminais_sem_reduzir_total_de_transacoes(monkeypatch):
    class Colecao:
        def aggregate(self, pipeline):
            # Coleção principal: `key` escolhe entre os índices 2dsphere de `local`.
            assert pipeline[0]['$geoNear']['key'] == 'local'
            facet = pipeline[1]['$facet']
            assert facet['total'] == [{'$count': 'n'}]
            sample = facet['amostra']
            assert sample[0]['$group']['_id'] == '$dispositivo.id'
            assert next(i for i, stage in enumerate(sample) if '$group' in stage) < next(i for i, stage in enumerate(sample) if '$limit' in stage)
            assert sample[2] == {'$sort': {'distanciaMetros': 1, 'dispositivo.id': 1}}
            return iter([{'total': [{'n': 20}], 'amostra': [{'endToEndId': 'E1', 'distanciaMetros': 250}]}])
    monkeypatch.setattr(geo, 'colecao', Colecao())
    result = geo._geo_near_resultado({'type': 'Point', 'coordinates': [-46, -23]}, 50, 5)
    assert result['colecao'] == geo.GEO_COLECAO
    assert result['contagem'] == 20
    assert result['amostra_por_terminal'] is True
    assert result['amostra'][0]['distanciaMetros'] == 250


def test_comparacao_rotas_exibe_somente_resultados_retornados_pelo_banco(monkeypatch):
    class Banco:
        def aggregate(self, pipeline, **kwargs):
            assert kwargs['maxTimeMS'] == 10000
            assert pipeline[0]['$documents'][1]['local']['type'] == 'LineString'
            # Resposta propositalmente diferente do cenário usual: não pode
            # haver classificação geométrica nem resultado fixo na aplicação.
            return iter([{'geoWithin': [], 'geoIntersects': [{'id': 'C'}]}])
    monkeypatch.setattr(geo, 'banco', Banco())
    r = geo.comparar_rotas()
    assert r['resultados'][0]['ids'] == []
    assert r['resultados'][1]['ids'] == ['C']
    assert len(r['rotas']) == 3


@pytest.mark.parametrize('centro', [[-46.6333, -23.5505], [-38.5267, -3.7319], [-60.02, -3.1], [-51.23, -30.03]])
def test_rotas_acompanham_centro_mas_nao_escalam_com_raio(monkeypatch, centro):
    class Banco:
        def aggregate(self, pipeline, **kwargs):
            return iter([{}])
    monkeypatch.setattr(geo, 'banco', Banco())
    menor = geo.comparar_rotas(*centro, raioKm=10)
    maior = geo.comparar_rotas(*centro, raioKm=200)
    assert menor['centro'] == centro
    assert menor['rotas'] == maior['rotas']
    assert menor['poligono'] != maior['poligono']
    assert menor['rotas'][0]['local']['coordinates'][1][0] == centro[0]
    assert menor['pipeline'][0]['$documents'] == menor['rotas']
    for resultado in maior['resultados']:
        assert resultado['query']['local'][resultado['operador']]['$geometry'] == maior['poligono']


def test_seed_recusa_banco_da_demo_sem_flag(monkeypatch):
    seed = _carregar_seed()
    monkeypatch.delenv("ALLOW_DEMO_DB_WRITE", raising=False)
    with pytest.raises(RuntimeError, match="ALLOW_DEMO_DB_WRITE"):
        seed.assert_writable_db("geo")


def test_seed_aceita_banco_test_e_flag_explicita(monkeypatch):
    seed = _carregar_seed()
    monkeypatch.delenv("ALLOW_DEMO_DB_WRITE", raising=False)
    seed.assert_writable_db("geo_test")
    monkeypatch.setenv("ALLOW_DEMO_DB_WRITE", "1")
    seed.assert_writable_db("geo")


def test_geonear_recusado_degrada_so_o_proprio_card(monkeypatch):
    from pymongo.errors import OperationFailure

    class Colecao:
        def aggregate(self, _pipeline):
            raise OperationFailure("x", code=27, details={"errmsg": "more than one 2dsphere index"})

    monkeypatch.setattr(geo, "colecao", Colecao())
    r = geo._geo_near_resultado({"type": "Point", "coordinates": [-46, -23]}, 50, 5)
    assert r["erro"] == "more than one 2dsphere index"
    assert r["contagem"] is None and r["amostra"] == []
    assert r["query"][0]["$geoNear"]["key"] == "local"


def test_dataset_atual_aceita_manifesto_no_banco(monkeypatch, tmp_path):
    class Colecao:
        def count_documents(self, _filtro):
            return 40

        def find_one(self, *_a):
            return None

    monkeypatch.setattr(seed_geo, "ARQUIVO_FRAUDES", tmp_path / "ausente.json")
    meta = {"clientesPlantados": ["CLI1"], "datasetVersion": seed_geo.VERSAO_DATASET, "semente": seed_geo.SEMENTE}
    assert seed_geo.dataset_atual(Colecao(), 40, meta)[0] is True
    # Sem manifesto no banco nem arquivo, o dataset não é considerado atual.
    assert seed_geo.dataset_atual(Colecao(), 40, {})[0] is False


def test_registrar_dataset_grava_plantados_no_banco():
    gravado = {}

    class Metadata:
        def replace_one(self, filtro, documento, upsert):
            gravado.update(filtro=filtro, documento=documento, upsert=upsert)

    seed_geo.registrar_dataset({"demo_metadata": Metadata()}, 40, ["CLI2", "CLI1"])
    assert gravado["upsert"] is True
    assert gravado["documento"]["clientesPlantados"] == ["CLI1", "CLI2"]
    assert gravado["documento"]["limiteKmh"] == seed_geo.LIMITE_KMH_PLANTADO


def test_seed_nao_reescreve_manifesto_versionado_em_banco_test():
    assert seed_geo.banco_de_teste("geo_test") is True
    assert seed_geo.banco_de_teste("geo") is False


def test_search_com_termo_desempata_pela_proximidade_no_proprio_search(monkeypatch):
    """Nomes iguais empatam no texto; o `near` do Search soma score por proximidade."""
    capturado = []

    class Colecao:
        def aggregate(self, pipeline):
            capturado.append(pipeline)
            return iter([])

    monkeypatch.setattr(geo, "_search_disponivel", lambda: (True, "ok"))
    monkeypatch.setattr(geo, "colecao", Colecao())
    geo.geo_search(geo.SearchRequest(termo="padaria", centro=[-46.6, -23.5], raioKm=20))
    compound = capturado[0][0]["$search"]["compound"]
    near = compound["should"][0]["near"]
    assert near["path"] == "local" and near["pivot"] == 10_000
    assert near["origin"]["coordinates"] == [-46.6, -23.5]
    # Sem termo a ordem já é a distância calculada; não há `should`.
    capturado.clear()
    geo.geo_search(geo.SearchRequest(termo="", centro=[-46.6, -23.5], raioKm=20))
    assert "should" not in capturado[0][0]["$search"]["compound"]


def test_fallback_do_arquivo_nao_fica_em_cache(monkeypatch, tmp_path):
    """Banco fora do ar cai no arquivo; quando volta, o banco passa a valer."""
    _manifesto_real(monkeypatch)
    arquivo = tmp_path / "fraud_seeds.json"
    arquivo.write_text('{"clientes": ["CLI_ARQUIVO"]}', encoding="utf-8")
    monkeypatch.setattr(geo, "ARQUIVO_FRAUDES", arquivo)
    monkeypatch.setattr(geo, "banco", _BancoMetadata(erro=RuntimeError("sem cluster")))
    assert geo._clientes_plantados() == {"CLI_ARQUIVO"}
    assert geo._manifesto_cache is None

    monkeypatch.setattr(geo, "banco", _BancoMetadata({"clientesPlantados": ["CLI_BANCO"]}))
    assert geo._clientes_plantados() == {"CLI_BANCO"}
    assert geo._manifesto_cache["origem"] == "banco"

    # Em cache: o banco não é consultado de novo.
    monkeypatch.setattr(geo, "banco", _BancoMetadata(erro=AssertionError("não devia consultar")))
    assert geo._clientes_plantados() == {"CLI_BANCO"}


def test_explain_compare_mostra_o_hint_real_de_cada_plano(monkeypatch):
    monkeypatch.setattr(geo, "_explain_find", lambda _f, hint: {"indice_usado": hint})
    r = geo.explain_compare(geo.ExplainRequest(clienteId="CLI1", centro=[-46.6, -23.5]))
    assert "<índice>" not in r["query"]
    for plano in r["planos"]:
        assert f'.hint("{plano["hint"]}")' in plano["comando"]
        assert plano["comando"] in r["query"]
    assert {p["hint"] for p in r["planos"]} == {geo.INDICE_COMPOSTO, geo.INDICE_GEO_PURO}


def test_explain_find_monta_o_texto_do_comando_enviado(monkeypatch):
    enviados = []

    class Banco:
        def command(self, comando):
            enviados.append(comando)
            return {"queryPlanner": {"winningPlan": {"stage": "IXSCAN", "indexName": "x"}}}

    monkeypatch.setattr(geo, "banco", Banco())
    r = geo._explain_find({"clienteId": "CLI1"}, geo.INDICE_COMPOSTO)
    assert enviados[0]["explain"]["hint"] == geo.INDICE_COMPOSTO
    assert f'.hint("{geo.INDICE_COMPOSTO}")' in r["comando"]
    assert '"clienteId": "CLI1"' in r["comando"]


# ── Demo D · geocerca: 2dsphere nativo × Atlas Search (ADR 0003) ─────────────
def _area_assinada(anel):
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(anel, anel[1:])) / 2


def test_poligono_geocerca_fecha_o_anel_no_sentido_anti_horario():
    anel = geo._poligono_geocerca([-46.63, -23.55], 15)["coordinates"][0]
    assert anel[0] == anel[-1]
    assert len(anel) == len(geo._FATORES_GEOCERCA) + 1
    assert _area_assinada(anel) > 0


def test_densificar_mantem_os_vertices_e_encurta_as_arestas():
    original = geo._poligono_geocerca([-47.45, -23.5], 600)
    denso = geo._densificar_anel(original)["coordinates"][0]
    for vertice in original["coordinates"][0]:
        assert vertice in denso
    assert denso[0] == denso[-1]
    passos = [max(abs(x2 - x1), abs(y2 - y1)) for (x1, y1), (x2, y2) in zip(denso, denso[1:])]
    assert max(passos) <= 0.05 + 1e-6


def test_estado_search_index_exige_ready(monkeypatch):
    class Colecao:
        def __init__(self, indices):
            self.indices = indices

        def list_search_indexes(self, nome):
            return [i for i in self.indices if i["name"] == nome]

    monkeypatch.setattr(geo, "colecao", Colecao([{"name": "x", "status": "BUILDING", "queryable": False}]))
    ok, msg = geo._estado_search_index("x")
    assert ok is False and "BUILDING" in msg
    monkeypatch.setattr(geo, "colecao", Colecao([]))
    assert geo._estado_search_index("x")[0] is False
    monkeypatch.setattr(geo, "colecao", Colecao([{"name": "x", "status": "READY", "queryable": True}]))
    assert geo._estado_search_index("x") == (True, "disponível")


def test_resumo_explain_agregacao_com_e_sem_stages():
    com_stages = {"stages": [
        {"$cursor": {
            "queryPlanner": {"winningPlan": {"stage": "FETCH", "inputStage": {
                "stage": "IXSCAN", "indexName": "categoria_local_idx"}}},
            "executionStats": {"nReturned": 9, "executionTimeMillis": 5,
                               "totalKeysExamined": 11, "totalDocsExamined": 10},
        }, "nReturned": 9, "executionTimeMillisEstimate": 4},
        {"$group": {}, "nReturned": 2, "executionTimeMillisEstimate": 6},
    ]}
    r = geo._resumo_explain_agregacao(com_stages)
    assert r["primeiro_estagio"] == "$cursor"
    assert r["ms_servidor"] == 6
    assert r["indice_usado"] == "categoria_local_idx"
    assert r["totalKeysExamined"] == 11

    search = {"stages": [
        {"$_internalDocumentResultsAndMetadata": {"source": {"explain": {"metadata": {"mongotHostName": "h"}}}},
         "nReturned": 9, "executionTimeMillisEstimate": 30},
        {"$facet": {}, "executionTimeMillisEstimate": 31},
    ]}
    r = geo._resumo_explain_agregacao(search)
    assert r["ms_servidor"] == 31 and r["docs_do_primeiro_estagio"] == 9
    assert "h" not in str(r)  # o host do mongot não vai para a tela

    sem_stages = {"queryPlanner": {"winningPlan": {"stage": "IXSCAN", "indexName": "i"}},
                  "executionStats": {"executionTimeMillis": 3}}
    assert geo._resumo_explain_agregacao(sem_stages)["ms_servidor"] == 3


class _ColecaoGeocerca:
    """Registra cada pipeline enviado e responde conforme o primeiro estágio."""

    def __init__(self, nativo, search, status="READY"):
        self.nativo, self.search, self.status = nativo, search, status
        self.executados: list[list[dict]] = []

    def list_search_indexes(self, nome):
        return [{"name": nome, "status": self.status, "queryable": self.status == "READY"}]

    def aggregate(self, pipeline, **_kw):
        self.executados.append(pipeline)
        if "$search" in pipeline[0]:
            if "should" in pipeline[0]["$search"]["compound"]:
                return [{"terminalId": "POS1", "nome": "Drogaria", "municipio": "X", "score": 1.2}]
            return list(self.search)
        return list(self.nativo)


class _BancoExplain:
    def __init__(self, falha_no_search=False):
        self.explicados: list[list[dict]] = []
        self.falha_no_search = falha_no_search

    def command(self, comando):
        pipeline = comando["explain"]["pipeline"]
        self.explicados.append(pipeline)
        if self.falha_no_search and "$search" in pipeline[0]:
            raise geo.OperationFailure("mongot fora", details=None)
        return {"stages": [{"$x": {}, "nReturned": 1, "executionTimeMillisEstimate": 1}]}


def _pedido_geocerca(**kw):
    base = {"centro": [-46.63, -23.55], "raioKm": 15, "categoria": "farmácia", "termo": "drogaria", "execucoes": 2}
    return geo.GeocercaRequest(**{**base, **kw})


def test_geocerca_recusa_categoria_fora_do_dataset_e_centro_invalido():
    with pytest.raises(HTTPException) as exc:
        geo.geocerca_comparar(_pedido_geocerca(categoria="cassino"))
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        geo.geocerca_comparar(_pedido_geocerca(centro=[0.0, 95.0]))
    assert exc.value.status_code == 422


def test_geocerca_exibe_os_pipelines_executados_e_compara_terminal_a_terminal(monkeypatch):
    terminais = [{"_id": "POS1", "compras": 3}, {"_id": "POS2", "compras": 1}]
    colecao = _ColecaoGeocerca(terminais, terminais)
    banco = _BancoExplain()
    monkeypatch.setattr(geo, "colecao", colecao)
    monkeypatch.setattr(geo, "banco", banco)

    r = geo.geocerca_comparar(_pedido_geocerca())

    relevancia = r["search"]["relevancia"]
    # A MQL na tela é exatamente a enviada ao servidor (execuções e explain).
    assert colecao.executados == [r["nativo"]["pipeline"], r["search"]["pipeline"]] * 2 + [relevancia["pipeline"]]
    assert banco.explicados == [r["nativo"]["pipeline"], r["search"]["pipeline"], relevancia["pipeline"]]
    busca = r["search"]["pipeline"][0]["$search"]
    assert busca["index"] == geo.GEO_GEOCERCA_INDEX and busca["returnStoredSource"] is True
    # Comparação justa: mesmo filtro e mesmo $group nos dois, sem pontuação.
    assert busca["compound"] == {"filter": busca["compound"]["filter"]}
    assert busca["compound"]["filter"][0]["geoWithin"]["geometry"] == r["poligono"]
    assert r["nativo"]["pipeline"][0]["$match"]["local"]["$geoWithin"]["$geometry"] == r["poligono"]
    assert r["nativo"]["pipeline"][1:] == r["search"]["pipeline"][1:]
    # O texto só no pipeline de relevância, como `should`, medido à parte.
    rel = relevancia["pipeline"][0]["$search"]["compound"]
    assert rel["should"][0]["text"]["query"] == "drogaria" and "must" not in rel
    assert rel["filter"] == busca["compound"]["filter"]
    assert relevancia["plano"]["ms_servidor"] == 1 and relevancia["resultados"][0]["terminalId"] == "POS1"
    assert r["comparacao"]["mesmas_compras"] is True
    assert r["nativo"]["compras"] == 4 and len(r["nativo"]["ms_parede"]) == 2


def test_geocerca_mostra_a_divergencia_sem_ajustar(monkeypatch):
    colecao = _ColecaoGeocerca([{"_id": "POS1", "compras": 3}],
                               [{"_id": "POS1", "compras": 3}, {"_id": "POS9", "compras": 2}])
    monkeypatch.setattr(geo, "colecao", colecao)
    monkeypatch.setattr(geo, "banco", _BancoExplain())
    r = geo.geocerca_comparar(_pedido_geocerca(termo=""))
    assert r["comparacao"]["mesmo_conjunto"] is False
    assert r["comparacao"]["so_search"] == ["POS9"] and r["comparacao"]["so_nativo"] == []
    assert r["search"]["relevancia"] is None
    assert all("should" not in p[0].get("$search", {}).get("compound", {}) for p in colecao.executados)


def test_geocerca_explain_do_search_falha_e_so_o_search_degrada(monkeypatch):
    colecao = _ColecaoGeocerca([{"_id": "POS1", "compras": 3}], [{"_id": "POS1", "compras": 3}])
    monkeypatch.setattr(geo, "colecao", colecao)
    monkeypatch.setattr(geo, "banco", _BancoExplain(falha_no_search=True))
    r = geo.geocerca_comparar(_pedido_geocerca())
    assert r["nativo"]["n_terminais"] == 1 and r["nativo"]["plano"]["ms_servidor"] == 1
    assert r["search"]["estado"] == "erro" and "mongot fora" in r["search"]["mensagem"]
    assert r["comparacao"] is None


def test_geocerca_sem_indice_ready_nao_roda_search_e_mede_o_nativo(monkeypatch):
    colecao = _ColecaoGeocerca([{"_id": "POS1", "compras": 3}], [], status="BUILDING")
    monkeypatch.setattr(geo, "colecao", colecao)
    monkeypatch.setattr(geo, "banco", _BancoExplain())
    r = geo.geocerca_comparar(_pedido_geocerca())
    assert all("$search" not in p[0] for p in colecao.executados)
    assert r["search"]["estado"] == "nao_configurado" and r["comparacao"] is None
    assert r["nativo"]["n_terminais"] == 1


def test_geocerca_densificada_envia_o_poligono_denso(monkeypatch):
    monkeypatch.setattr(geo, "colecao", _ColecaoGeocerca([], []))
    monkeypatch.setattr(geo, "banco", _BancoExplain())
    r = geo.geocerca_comparar(_pedido_geocerca(raioKm=600, densificar=True))
    assert r["densificado"] is True and r["vertices"] > 100
    assert r["nativo"]["pipeline"][0]["$match"]["local"]["$geoWithin"]["$geometry"] == r["poligono"]
