"""Tests para src/views.py.

Cubre:
- vista_triage: solo incidentes sre, orden score descendente.
- vista_composicion: conteos de alertas (NIVEL ALERTA, no incidente):
    INSUFFICIENT_FUNDS=28, IMPOSSIBLE_TO_CHARGE=25, CARD_DECLINED=23,
    BANK_REJECTED=12 (EDA §7 [ACEPTACIÓN]).
- KPI % de INSUFFICIENT_FUNDS.
- vista_patrones: agrupación por fingerprint, crónicos activos.
    Crónico activo = es_recurrente=True AND n_incidentes >= 5.
    Caso canónico: Orchestrator::high request count con 45 episodios.
- Determinismo de las tres vistas.
- Fixtures sintéticas para aislamiento.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
import pandas as pd

from src.ingest import load
from src.normalize import normalize
from src.dedupe import dedupe
from src.profiles import build_profiles
from src.score import score
from src.views import vista_triage, vista_composicion, vista_patrones

RAW_JSON = Path(__file__).parents[1] / "data" / "raw" / "alerts_combined.json"
CONFIG_PATH = Path(__file__).parents[1] / "config.yaml"

_TZ = timezone(timedelta(hours=-6))


# ---------------------------------------------------------------------------
# Fixtures de sesión
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def config():
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def df_norm(config):
    records = load(RAW_JSON)
    return normalize(records, config)


@pytest.fixture(scope="session")
def df_inc(config, df_norm):
    return dedupe(df_norm, config)


@pytest.fixture(scope="session")
def profiles(df_inc):
    return build_profiles(df_inc)


@pytest.fixture(scope="session")
def df_scored(df_inc, profiles, config):
    return score(df_inc, profiles, config)


@pytest.fixture(scope="session")
def triage(df_scored):
    return vista_triage(df_scored)


@pytest.fixture(scope="session")
def composicion(df_norm):
    return vista_composicion(df_norm)


@pytest.fixture(scope="session")
def patrones(df_scored, config):
    return vista_patrones(df_scored, config)


# ---------------------------------------------------------------------------
# Tests de vista_triage con datos reales
# ---------------------------------------------------------------------------

class TestVistaTriage:

    def test_solo_sre(self, triage):
        """La vista triage contiene solo incidentes del canal sre."""
        assert (triage["channel"] == "sre").all()

    def test_orden_score_descendente(self, triage):
        scores = triage["score"].tolist()
        assert scores == sorted(scores, reverse=True), \
            "Triage no está ordenado por score descendente"

    def test_vista_columna_triage(self, triage):
        assert (triage["vista"] == "triage").all()

    def test_columnas_obligatorias(self, triage):
        for col in [
            "incident_id", "score", "banda", "banda_etiqueta", "service",
            "condition", "explicacion", "n_disparos", "duracion_min", "inicio",
            "s_criticidad", "s_ficha", "s_rafaga", "s_intensidad", "s_novedad",
        ]:
            assert col in triage.columns, f"Columna faltante en triage: {col}"

    def test_no_cx_en_triage(self, triage):
        assert "monitoring-ops-cx" not in triage["channel"].values

    def test_tiene_p1(self, triage):
        assert "P1" in triage["banda"].values

    def test_determinismo(self, df_scored):
        t1 = vista_triage(df_scored)
        t2 = vista_triage(df_scored)
        assert t1["incident_id"].tolist() == t2["incident_id"].tolist()


# ---------------------------------------------------------------------------
# Tests de vista_triage sintéticos
# ---------------------------------------------------------------------------

class TestVistaTriage_Sintetico:

    def _scored_df(self, rows):
        return pd.DataFrame(rows)

    def test_filtra_solo_sre(self):
        df = pd.DataFrame([
            {"channel": "sre", "score": 80, "incident_id": "INC-0001", "vista": "triage"},
            {"channel": "monitoring-ops-cx", "score": 90, "incident_id": "INC-0002", "vista": "composicion"},
        ])
        result = vista_triage(df)
        assert len(result) == 1
        assert result["channel"].iloc[0] == "sre"

    def test_orden_score(self):
        df = pd.DataFrame([
            {"channel": "sre", "score": 50, "incident_id": "INC-0002", "vista": "triage"},
            {"channel": "sre", "score": 80, "incident_id": "INC-0001", "vista": "triage"},
            {"channel": "sre", "score": 30, "incident_id": "INC-0003", "vista": "triage"},
        ])
        result = vista_triage(df)
        assert result["score"].tolist() == [80, 50, 30]


# ---------------------------------------------------------------------------
# Tests de vista_composicion con datos reales
# ---------------------------------------------------------------------------

class TestVistaComposicion:

    def test_total_cx_95(self, composicion):
        """95 alertas cx en total."""
        assert composicion["total"] == 95

    def test_insufficient_funds_28(self, composicion):
        """INSUFFICIENT_FUNDS: 28 alertas (EDA §7 [ACEPTACIÓN])."""
        assert composicion["por_error_type"].get("INSUFFICIENT_FUNDS", 0) == 28

    def test_impossible_to_charge_25(self, composicion):
        """IMPOSSIBLE_TO_CHARGE: 25 alertas (EDA §7 [ACEPTACIÓN])."""
        assert composicion["por_error_type"].get("IMPOSSIBLE_TO_CHARGE", 0) == 25

    def test_card_declined_23(self, composicion):
        """CARD_DECLINED: 23 alertas (EDA §7 [ACEPTACIÓN])."""
        assert composicion["por_error_type"].get("CARD_DECLINED", 0) == 23

    def test_bank_rejected_12(self, composicion):
        """BANK_REJECTED: 12 alertas (EDA §7 [ACEPTACIÓN])."""
        assert composicion["por_error_type"].get("BANK_REJECTED", 0) == 12

    def test_suma_error_types_es_95(self, composicion):
        total_et = sum(composicion["por_error_type"].values())
        assert total_et == 95

    def test_kpi_insufficient_funds_pct(self, composicion):
        """INSUFFICIENT_FUNDS = 28/95 ≈ 29.5%."""
        pct = composicion["kpi_pct"].get("INSUFFICIENT_FUNDS", 0.0)
        assert abs(pct - 29.5) <= 0.5, f"INSUFFICIENT_FUNDS kpi_pct={pct}"

    def test_por_procesador_no_vacio(self, composicion):
        """Debe haber al menos un procesador identificado."""
        assert len(composicion["por_procesador"]) > 0

    def test_procesadores_conocidos(self, composicion):
        """Los procesadores identificados son Conekta, Mercadopago o PayPal."""
        for proc in composicion["por_procesador"].keys():
            assert proc in {"Conekta", "Mercadopago", "PayPal"}, \
                f"Procesador inesperado: {proc}"

    def test_por_dia_tiene_4_dias(self, composicion):
        """El período cx abarca 4 días (24-27 mar 2026)."""
        assert len(composicion["por_dia"]) == 4

    def test_dia_24_mar_57_alertas(self, composicion):
        """El día con más alertas es 2026-03-24 con 57 (EDA §3)."""
        dia_counts = composicion["por_dia"]
        assert dia_counts.get("2026-03-24", 0) == 57

    def test_determinismo(self, df_norm):
        c1 = vista_composicion(df_norm)
        c2 = vista_composicion(df_norm)
        assert c1["por_error_type"] == c2["por_error_type"]
        assert c1["por_dia"] == c2["por_dia"]


# ---------------------------------------------------------------------------
# Tests sintéticos de vista_composicion
# ---------------------------------------------------------------------------

class TestVistaComposicion_Sintetico:

    def _cx_df(self, rows: list[dict]) -> pd.DataFrame:
        return pd.DataFrame(rows)

    def _row(self, error_type="CARD_DECLINED", procesador="Conekta",
             dt=None):
        if dt is None:
            dt = datetime(2026, 3, 24, 14, 0, tzinfo=_TZ)
        return {
            "channel": "monitoring-ops-cx",
            "error_type": error_type,
            "procesador": procesador,
            "dt": dt,
        }

    def test_conteo_error_types(self):
        df = self._cx_df([
            self._row("INSUFFICIENT_FUNDS"),
            self._row("INSUFFICIENT_FUNDS"),
            self._row("CARD_DECLINED"),
        ])
        result = vista_composicion(df)
        assert result["por_error_type"]["INSUFFICIENT_FUNDS"] == 2
        assert result["por_error_type"]["CARD_DECLINED"] == 1

    def test_kpi_pct_calculo(self):
        df = self._cx_df([self._row("INSUFFICIENT_FUNDS")] * 3
                         + [self._row("CARD_DECLINED")] * 1)
        result = vista_composicion(df)
        # 3/4 = 75%
        assert result["kpi_pct"]["INSUFFICIENT_FUNDS"] == 75.0

    def test_procesador_vacio_excluido(self):
        df = self._cx_df([
            self._row(procesador="Conekta"),
            self._row(procesador=""),
        ])
        result = vista_composicion(df)
        assert "" not in result["por_procesador"]
        assert result["por_procesador"].get("Conekta", 0) == 1

    def test_por_dia_agrupacion(self):
        d1 = datetime(2026, 3, 24, 10, 0, tzinfo=_TZ)
        d2 = datetime(2026, 3, 25, 10, 0, tzinfo=_TZ)
        df = self._cx_df([
            self._row(dt=d1),
            self._row(dt=d1),
            self._row(dt=d2),
        ])
        result = vista_composicion(df)
        assert result["por_dia"]["2026-03-24"] == 2
        assert result["por_dia"]["2026-03-25"] == 1

    def test_total_correcto(self):
        df = self._cx_df([self._row()] * 5)
        result = vista_composicion(df)
        assert result["total"] == 5


# ---------------------------------------------------------------------------
# Tests de vista_patrones con datos reales
# ---------------------------------------------------------------------------

class TestVistaPatrones:

    def test_columnas_obligatorias(self, patrones):
        for col in [
            "channel", "fingerprint", "service", "n_incidentes",
            "score_medio", "score_max", "n_disparos_total",
            "es_recurrente", "es_cronico", "primera", "ultima",
        ]:
            assert col in patrones.columns, f"Columna faltante: {col}"

    def test_total_fingerprints(self, patrones):
        """43 fingerprints distintos sobre 277 incidentes."""
        assert len(patrones) == 43

    def test_suma_n_incidentes_es_277(self, patrones):
        """Todos los incidentes están asignados a exactamente un patrón."""
        assert patrones["n_incidentes"].sum() == 277

    def test_cronicos_activos_son_19(self, patrones):
        """19 fingerprints cumplen es_recurrente=True AND n_incidentes >= 5."""
        assert patrones["es_cronico"].sum() == 19

    def test_orden_cronicos_primero(self, patrones):
        """Primeras filas son crónicos; las no-crónicas van al final."""
        es_cronico = patrones["es_cronico"].tolist()
        # Todos los True deben preceder a cualquier False
        ultimo_true = max((i for i, v in enumerate(es_cronico) if v), default=-1)
        primer_false = next((i for i, v in enumerate(es_cronico) if not v), len(es_cronico))
        assert ultimo_true < primer_false, "Crónicos no están al inicio del DataFrame"

    def test_orchestrator_500_es_cronico(self, patrones):
        """Orchestrator::high request count con 45 episodios debe ser crónico."""
        row = patrones[
            patrones["fingerprint"] == "Orchestrator::high request count with status 500"
        ]
        assert not row.empty
        assert row.iloc[0]["n_incidentes"] == 45
        assert row.iloc[0]["es_cronico"]
        assert abs(row.iloc[0]["score_medio"] - 43.9) <= 1.0

    def test_tesseract_high_error_no_cronico(self, patrones):
        """tesseract High App Error % tiene 7 incidentes pero es_recurrente=False -> no crónico."""
        row = patrones[
            patrones["fingerprint"] == "tesseract::High Application Error percentage"
        ]
        assert not row.empty
        assert not row.iloc[0]["es_recurrente"]
        assert not row.iloc[0]["es_cronico"]

    def test_n_disparos_total_positivo(self, patrones):
        assert (patrones["n_disparos_total"] >= 1).all()

    def test_primera_antes_de_ultima(self, patrones):
        """primera <= ultima para todos los patrones."""
        assert (patrones["primera"] <= patrones["ultima"]).all()

    def test_cronicos_incluyen_cx(self, patrones):
        """Hairs::Payments rejected hairs CX es crónico activo (cx también tiene crónicos)."""
        row = patrones[
            (patrones["fingerprint"] == "Hairs::Payments rejected hairs CX")
            & (patrones["channel"] == "monitoring-ops-cx")
        ]
        assert not row.empty
        assert row.iloc[0]["es_cronico"]

    def test_determinismo(self, df_scored, config):
        p1 = vista_patrones(df_scored, config)
        p2 = vista_patrones(df_scored, config)
        assert p1["fingerprint"].tolist() == p2["fingerprint"].tolist()
        assert p1["n_incidentes"].tolist() == p2["n_incidentes"].tolist()

    def test_score_max_gte_score_medio(self, patrones):
        assert (patrones["score_max"] >= patrones["score_medio"]).all()


# ---------------------------------------------------------------------------
# Tests sintéticos de vista_patrones
# ---------------------------------------------------------------------------

class TestVistaPatrones_Sintetico:

    def _make_df(self, rows: list[dict]) -> pd.DataFrame:
        """Crea un DataFrame mínimo de incidentes scoreados."""
        return pd.DataFrame(rows)

    def _inc(
        self,
        fingerprint="Foo::bar",
        channel="sre",
        service="Foo",
        score_val=50,
        n_disparos=1,
        n_alertas=1,
        es_recurrente=False,
        inicio=None,
        fin=None,
    ) -> dict:
        t = inicio or datetime(2025, 6, 2, 14, 0, tzinfo=_TZ)
        return {
            "incident_id": "INC-0001",
            "channel": channel,
            "fingerprint": fingerprint,
            "service": service,
            "score": score_val,
            "n_disparos": n_disparos,
            "n_alertas": n_alertas,
            "es_recurrente": es_recurrente,
            "inicio": t,
            "fin": fin or t,
        }

    def test_un_fingerprint(self, config):
        df = self._make_df([self._inc(score_val=60, n_disparos=3)])
        p = vista_patrones(df, config)
        assert len(p) == 1
        assert p.iloc[0]["n_incidentes"] == 1
        assert p.iloc[0]["score_medio"] == 60.0
        assert p.iloc[0]["n_disparos_total"] == 3

    def test_dos_fingerprints_distintos(self, config):
        df = self._make_df([
            self._inc("A::cond1", score_val=70),
            self._inc("B::cond2", score_val=40),
        ])
        p = vista_patrones(df, config)
        assert len(p) == 2
        assert p["n_incidentes"].sum() == 2

    def test_score_medio_correcto(self, config):
        """Dos incidentes del mismo fingerprint con scores 40 y 60 -> medio=50."""
        df = self._make_df([
            self._inc("X::y", score_val=40),
            self._inc("X::y", score_val=60),
        ])
        p = vista_patrones(df, config)
        assert len(p) == 1
        assert p.iloc[0]["score_medio"] == 50.0

    def test_es_cronico_false_poco_incidentes(self, config):
        """4 incidentes recurrentes: menos que cronico_min_incidentes=5 -> no crónico."""
        rows = [self._inc("X::y", es_recurrente=True) for _ in range(4)]
        df = self._make_df(rows)
        p = vista_patrones(df, config)
        assert not bool(p.iloc[0]["es_cronico"])

    def test_es_cronico_true(self, config):
        """5 incidentes recurrentes = exactamente el umbral -> crónico."""
        rows = [self._inc("X::y", es_recurrente=True) for _ in range(5)]
        df = self._make_df(rows)
        p = vista_patrones(df, config)
        assert bool(p.iloc[0]["es_cronico"])

    def test_es_cronico_false_no_recurrente(self, config):
        """10 incidentes pero es_recurrente=False -> no crónico (es nuevo ruidoso)."""
        rows = [self._inc("X::y", es_recurrente=False) for _ in range(10)]
        df = self._make_df(rows)
        p = vista_patrones(df, config)
        assert not bool(p.iloc[0]["es_cronico"])

    def test_primera_ultima(self, config):
        t1 = datetime(2025, 6, 2, 10, 0, tzinfo=_TZ)
        t2 = datetime(2025, 6, 5, 18, 0, tzinfo=_TZ)
        df = self._make_df([
            self._inc("X::y", inicio=t1, fin=t1),
            self._inc("X::y", inicio=t2, fin=t2),
        ])
        p = vista_patrones(df, config)
        assert p.iloc[0]["primera"] == t1
        assert p.iloc[0]["ultima"] == t2

    def test_cronicos_primero_en_orden(self, config):
        """Crónicos ordenados antes que no-crónicos."""
        rows = (
            [self._inc("A::cond", score_val=40, es_recurrente=False)] +
            [self._inc("B::cond", score_val=50, es_recurrente=True) for _ in range(6)]
        )
        df = self._make_df(rows)
        p = vista_patrones(df, config)
        assert p.iloc[0]["fingerprint"] == "B::cond"
        assert bool(p.iloc[0]["es_cronico"])
        assert p.iloc[-1]["fingerprint"] == "A::cond"
        assert not bool(p.iloc[-1]["es_cronico"])
