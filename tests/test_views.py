"""Tests para src/views.py.

Cubre:
- vista_triage: solo incidentes sre, orden score descendente.
- vista_composicion: conteos de alertas (NIVEL ALERTA, no incidente):
    INSUFFICIENT_FUNDS=28, IMPOSSIBLE_TO_CHARGE=25, CARD_DECLINED=23,
    BANK_REJECTED=12 (EDA §7 [ACEPTACIÓN]).
- KPI % de INSUFFICIENT_FUNDS.
- Determinismo de ambas vistas.
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
from src.views import vista_triage, vista_composicion

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
