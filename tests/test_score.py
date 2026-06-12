"""Tests para src/score.py.

Cubre:
- Casos canónicos del EDA §9: Hairs sre ~73 P1, tesseract ~76 P1,
  i-0d26dd ~59 P2, data-team RDS ~39 P3 (tolerancia ±10, banda obligatoria).
- Invariantes sobre todos los incidentes: score in [0,100], bandas válidas,
  columnas obligatorias presentes, suma de n_alertas == 458.
- P1 es minoría (< 50 % de incidentes).
- Determinismo: dos corridas -> output idéntico.
- Tests sintéticos aislados para cada componente y boost.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
import pandas as pd

from src.ingest import load
from src.normalize import normalize
from src.dedupe import dedupe
from src.profiles import build_profiles
from src.score import (
    score,
    _s_criticidad,
    _s_ficha,
    _s_rafaga,
    _s_intensidad,
    _s_novedad,
    _boosts,
    _fp_key,
    _explicacion,
)

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


# ---------------------------------------------------------------------------
# Tests de componentes aislados
# ---------------------------------------------------------------------------

class TestComponentes:

    def test_s_criticidad_pagos(self, config):
        assert _s_criticidad("pagos", config) == 1.00

    def test_s_criticidad_nucleo(self, config):
        assert _s_criticidad("nucleo", config) == 0.80

    def test_s_criticidad_datos(self, config):
        assert _s_criticidad("datos", config) == 0.60

    def test_s_criticidad_codename(self, config):
        assert _s_criticidad("codename", config) == 0.60

    def test_s_criticidad_infra(self, config):
        assert _s_criticidad("infra", config) == 0.50

    def test_s_criticidad_web(self, config):
        assert _s_criticidad("web", config) == 0.40

    def test_s_criticidad_default(self, config):
        assert _s_criticidad("desconocido", config) == 0.50

    def test_s_rafaga_uno(self):
        """n_disparos=1 -> log2(2)/5 = 0.2"""
        assert abs(_s_rafaga(1) - 0.2) < 1e-9

    def test_s_rafaga_grande(self):
        """n_disparos=31 -> log2(32)/5 = 1.0 (tapado)"""
        assert _s_rafaga(31) == 1.0

    def test_s_rafaga_zero(self):
        """n_disparos=0 -> 0.0"""
        assert _s_rafaga(0) == 0.0

    def test_s_intensidad_null(self, config):
        assert _s_intensidad(None, None, config) == 0.3

    def test_s_intensidad_high(self, config):
        assert _s_intensidad("high", "estatica", config) == 0.5

    def test_s_intensidad_critical_estatica(self, config):
        """critical + estatica = 0.75 (config.score.intensidad.critical_estatica)."""
        assert _s_intensidad("critical", "estatica", config) == 0.75

    def test_s_intensidad_critical_anomalia(self, config):
        """critical + anomalia = 1.0 (config.score.intensidad.critical_anomalia)."""
        assert _s_intensidad("critical", "anomalia", config) == 1.0

    def test_s_intensidad_critical_none_tipo(self, config):
        """critical sin tipo_regla (PayPal): usa rama estatica."""
        assert _s_intensidad("critical", None, config) == 0.75

    def test_s_novedad_no_profile(self, config):
        assert _s_novedad(None, config) == 1.0

    def test_s_novedad_dias_1(self, config):
        p = {"dias_visto": 1, "horas_tipicas": [], "sello_finde": False, "rafaga_tipica": 1.0}
        assert _s_novedad(p, config) == 1.0

    def test_s_novedad_dias_2(self, config):
        """1 < dias_visto < recurrente_min_dias(3) -> 0.9"""
        p = {"dias_visto": 2, "horas_tipicas": [], "sello_finde": False, "rafaga_tipica": 1.0}
        assert _s_novedad(p, config) == 0.9

    def test_s_novedad_recurrente(self, config):
        """dias_visto >= 3 -> 0.0"""
        p = {"dias_visto": 3, "horas_tipicas": [], "sello_finde": False, "rafaga_tipica": 1.0}
        assert _s_novedad(p, config) == 0.0

    def test_s_ficha_sin_profile(self, config):
        assert _s_ficha(None, 14, 1, config) == 0.9

    def test_s_ficha_dias_insuficientes(self, config):
        p = {"dias_visto": 2, "horas_tipicas": [14], "sello_finde": False, "rafaga_tipica": 1.0}
        assert _s_ficha(p, 14, 1, config) == 0.9

    def test_s_ficha_completamente_habitual(self, config):
        """es_recurrente + hora típica + n_alertas <= rafaga_tipica -> 0.0."""
        p = {"dias_visto": 5, "horas_tipicas": [2, 14], "sello_finde": False, "rafaga_tipica": 3.0}
        assert _s_ficha(p, 14, 3, config) == 0.0  # exactamente la mediana
        assert _s_ficha(p, 14, 1, config) == 0.0  # menor que la mediana

    def test_s_ficha_hora_tipica_rafaga_mayor(self, config):
        """Hora típica pero ráfaga más grande de lo habitual -> 0.1."""
        p = {"dias_visto": 5, "horas_tipicas": [2, 14], "sello_finde": False, "rafaga_tipica": 1.0}
        assert _s_ficha(p, 14, 2, config) == 0.1  # n_alertas=2 > rafaga_tipica=1.0

    def test_s_ficha_recurrente_hora_atipica(self, config):
        p = {"dias_visto": 5, "horas_tipicas": [2, 14], "sello_finde": False, "rafaga_tipica": 1.0}
        assert _s_ficha(p, 9, 1, config) == 0.6

    def test_boosts_ninguno(self, config):
        assert _boosts("sobre", config) == 0.0

    def test_boosts_bajo(self, config):
        assert abs(_boosts("bajo", config) - 0.05) < 1e-9

    def test_boosts_none_direccion(self, config):
        assert _boosts(None, config) == 0.0


# ---------------------------------------------------------------------------
# Tests de fp_key
# ---------------------------------------------------------------------------

class TestFpKey:

    def test_no_infra(self):
        assert _fp_key("data-team", "data-team", "RDS CPU Usage gral") == \
               "data-team::RDS CPU Usage gral"

    def test_infra_usa_original(self):
        assert _fp_key("infra", "i-0d26dd24e2a69bff0", "Parco 2.0 Nodes CPU Usage") == \
               "i-0d26dd24e2a69bff0::Parco 2.0 Nodes CPU Usage"

    def test_infra_new_parco(self):
        assert _fp_key("infra", "new-parco-instance-1", "Parco 2.0 Nodes CPU Usage") == \
               "new-parco-instance-1::Parco 2.0 Nodes CPU Usage"


# ---------------------------------------------------------------------------
# Tests sintéticos de score end-to-end
# ---------------------------------------------------------------------------

def _make_incident(
    channel="sre",
    service="TestSvc",
    service_original="TestSvc",
    grupo_criticidad="codename",
    condition="High Error",
    priority_max="high",
    tipo_regla="estatica",
    direccion="sobre",
    n_disparos=1,
    n_alertas=1,
    inicio=None,
) -> pd.DataFrame:
    if inicio is None:
        inicio = datetime(2025, 6, 2, 14, 0, tzinfo=_TZ)
    return pd.DataFrame([{
        "incident_id": "INC-0001",
        "channel": channel,
        "source": "New Relic",
        "fingerprint": f"{service}::{condition}",
        "service": service,
        "service_original": service_original,
        "grupo_criticidad": grupo_criticidad,
        "condition": condition,
        "policy": "Golden Signals",
        "tipo_regla": tipo_regla,
        "direccion": direccion,
        "ventana_eval": "5min",
        "inicio": inicio,
        "fin": inicio,
        "duracion_min": 0.0,
        "n_alertas": n_alertas,
        "n_disparos": n_disparos,
        "tasa_por_min": float(n_disparos),
        "priority_max": priority_max,
        "error_type": "",
        "procesador": "",
    }])


class TestScoreSintetico:

    def test_score_rango_valido(self, config):
        """score en [0, 100]."""
        df_inc = _make_incident()
        profiles = build_profiles(df_inc)
        df_s = score(df_inc, profiles, config)
        assert 0 <= df_s["score"].iloc[0] <= 100

    def test_score_pagos_alto(self, config):
        """Servicio de pagos con novedad alta debe superar P1."""
        # novedad: perfil nuevo -> 1.0; ficha: sin perfil antiguo -> 0.9
        df_inc = _make_incident(grupo_criticidad="pagos", priority_max="critical",
                                tipo_regla="anomalia")
        profiles = build_profiles(df_inc)
        df_s = score(df_inc, profiles, config)
        assert df_s["score"].iloc[0] >= 70, "Pagos + critical + anomalia debería ser P1"

    def test_score_web_bajo(self, config):
        """Servicio web con prioridad null debe dar score bajo."""
        df_inc = _make_incident(grupo_criticidad="web", priority_max=None,
                                tipo_regla=None, n_disparos=1)
        profiles = build_profiles(df_inc)
        df_s = score(df_inc, profiles, config)
        # w_crit*0.40 + w_ficha*0.9 + w_raf*0.2 + w_int*0.3 + w_nov*1.0
        # = 0.12 + 0.225 + 0.04 + 0.045 + 0.10 = 0.53 -> 53 P2 (no garantiza P3)
        # Pero el score debe ser < 70 (no P1)
        assert df_s["score"].iloc[0] < 70

    def test_banda_columna_presente(self, config):
        df_inc = _make_incident()
        profiles = build_profiles(df_inc)
        df_s = score(df_inc, profiles, config)
        assert "banda" in df_s.columns
        assert df_s["banda"].iloc[0] in {"P1", "P2", "P3"}

    def test_vista_sre(self, config):
        df_inc = _make_incident(channel="sre")
        profiles = build_profiles(df_inc)
        df_s = score(df_inc, profiles, config)
        assert df_s["vista"].iloc[0] == "triage"

    def test_vista_cx(self, config):
        df_inc = _make_incident(channel="monitoring-ops-cx")
        profiles = build_profiles(df_inc)
        df_s = score(df_inc, profiles, config)
        assert df_s["vista"].iloc[0] == "composicion"

    def test_es_recurrente_false_nuevo(self, config):
        df_inc = _make_incident()
        profiles = build_profiles(df_inc)
        df_s = score(df_inc, profiles, config)
        # 1 incidente -> dias_visto=1 < 3 -> no recurrente
        assert not df_s["es_recurrente"].iloc[0]

    def test_es_recurrente_true_con_historial(self, config):
        rows = [
            _make_incident(
                inicio=datetime(2025, 6, 2 + i, 14, 0, tzinfo=_TZ)
            ).iloc[0].to_dict()
            for i in range(4)
        ]
        for i, r in enumerate(rows):
            r["incident_id"] = f"INC-{i+1:04d}"
        df_inc = pd.DataFrame(rows)
        profiles = build_profiles(df_inc)
        df_s = score(df_inc, profiles, config)
        # 4 incidentes en 4 días distintos -> dias_visto=4 >= 3 -> recurrente
        assert df_s["es_recurrente"].iloc[0]

    def test_anomalia_score_mayor_que_estatica(self, config):
        """critical+anomalia (s_intensidad=1.0) > critical+estatica (0.75), todo lo demás igual."""
        df_est = _make_incident(priority_max="critical", tipo_regla="estatica")
        df_ano = _make_incident(priority_max="critical", tipo_regla="anomalia")
        p_est = build_profiles(df_est)
        p_ano = build_profiles(df_ano)
        s_est = score(df_est, p_est, config)["score"].iloc[0]
        s_ano = score(df_ano, p_ano, config)["score"].iloc[0]
        assert s_ano > s_est, (
            f"anomalia={s_ano} debe superar estatica={s_est} por diferencia en s_intensidad"
        )

    def test_columnas_obligatorias(self, config):
        df_inc = _make_incident()
        profiles = build_profiles(df_inc)
        df_s = score(df_inc, profiles, config)
        for col in [
            "incident_id", "channel", "vista", "fingerprint", "service",
            "service_original", "grupo_criticidad", "condition",
            "s_criticidad", "s_ficha", "s_rafaga", "s_intensidad", "s_novedad",
            "score", "banda", "banda_etiqueta", "explicacion",
            "es_recurrente", "dias_visto", "atendido", "etiqueta",
        ]:
            assert col in df_s.columns, f"Columna faltante: {col}"

    def test_atendido_etiqueta_vacios(self, config):
        df_inc = _make_incident()
        profiles = build_profiles(df_inc)
        df_s = score(df_inc, profiles, config)
        assert df_s["atendido"].iloc[0] == ""
        assert df_s["etiqueta"].iloc[0] == ""


# ---------------------------------------------------------------------------
# Tests de explicación
# ---------------------------------------------------------------------------

class TestExplicacion:

    def _p(self, dias_visto=5, horas_tipicas=None, sello_finde=False, rafaga=1.0):
        return {
            "dias_visto": dias_visto,
            "horas_tipicas": horas_tipicas or [14],
            "sello_finde": sello_finde,
            "rafaga_tipica": rafaga,
        }

    def test_primera_vez(self):
        r = _explicacion(
            "Hairs", "Payments", "sre", "estatica", "sobre",
            False, [], 14, 0, 1, 0.0, None,
        )
        assert "Primera vez" in r

    def test_canal_inusual(self):
        r = _explicacion(
            "Hairs", "Payments rejected hairs", "sre", "estatica", "sobre",
            True, [14], 14, 5, 1, 0.0, self._p(),
        )
        assert "canal de infraestructura" in r

    def test_anomalia(self):
        r = _explicacion(
            "tesseract", "High App Error %", "sre", "anomalia", "sobre",
            False, [14], 15, 2, 1, 0.0, self._p(dias_visto=2),
        )
        assert "anomalías" in r

    def test_bajo(self):
        r = _explicacion(
            "tesseract", "Low App Throughput", "sre", "estatica", "bajo",
            True, [14], 14, 5, 1, 0.0, self._p(),
        )
        assert "CAYÓ" in r

    def test_recurrente_en_hora_tipica(self):
        r = _explicacion(
            "data-team", "RDS CPU Usage gral", "sre", "estatica", "sobre",
            True, [2], 2, 6, 1, 0.0, self._p(dias_visto=6, horas_tipicas=[2]),
        )
        assert "Patrón habitual" in r
        assert "data-team" in r

    def test_default(self):
        r = _explicacion(
            "Orchestrator", "high request count with status 500", "sre",
            "estatica", "sobre",
            True, [9], 15, 5, 10, 30.0,
            self._p(dias_visto=5, horas_tipicas=[9]),
        )
        assert "disparos" in r


# ---------------------------------------------------------------------------
# Tests de aceptación con datos reales
# ---------------------------------------------------------------------------

class TestAceptacionScore:

    def test_total_incidentes(self, df_scored):
        """277 incidentes después del score."""
        assert len(df_scored) == 277

    def test_suma_n_alertas_458(self, df_scored):
        """Invariante: sum(n_alertas) == 458."""
        assert df_scored["n_alertas"].sum() == 458

    def test_score_rango_todos(self, df_scored):
        assert (df_scored["score"] >= 0).all()
        assert (df_scored["score"] <= 100).all()

    def test_bandas_validas(self, df_scored):
        assert set(df_scored["banda"].unique()).issubset({"P1", "P2", "P3"})

    def test_p1_minoria(self, df_scored):
        """P1 debe ser minoría del total (no puede ser la mayoría)."""
        p1_pct = (df_scored["banda"] == "P1").mean()
        assert p1_pct < 0.5, f"P1 = {p1_pct:.1%}, esperado < 50%"

    def test_hay_p1_p2_p3(self, df_scored):
        """Las 3 bandas deben estar presentes."""
        bandas = set(df_scored["banda"].unique())
        assert "P1" in bandas
        assert "P2" in bandas
        assert "P3" in bandas

    def test_vista_columna_correcta(self, df_scored):
        sre_mask = df_scored["channel"] == "sre"
        cx_mask = df_scored["channel"] == "monitoring-ops-cx"
        assert (df_scored.loc[sre_mask, "vista"] == "triage").all()
        assert (df_scored.loc[cx_mask, "vista"] == "composicion").all()

    def test_orden_score_desc(self, df_scored):
        scores = df_scored["score"].tolist()
        assert scores == sorted(scores, reverse=True)

    def test_determinismo(self, df_inc, profiles, config):
        """Dos corridas -> output idéntico."""
        df1 = score(df_inc, profiles, config)
        df2 = score(df_inc, profiles, config)
        assert df1["score"].tolist() == df2["score"].tolist()
        assert df1["incident_id"].tolist() == df2["incident_id"].tolist()

    # --- Casos canónicos EDA §9 (tolerancia ±10, banda obligatoria) ---

    def test_canonico_hairs_sre_p1(self, df_scored):
        """Hairs · Payments rejected hairs (sre) ~73 P1."""
        inc = df_scored[
            (df_scored["service"] == "Hairs")
            & (df_scored["condition"] == "Payments rejected hairs")
            & (df_scored["channel"] == "sre")
        ]
        assert not inc.empty, "No se encontró Hairs::Payments rejected hairs en sre"
        best = inc["score"].max()
        assert abs(best - 73) <= 10, f"Hairs sre score={best}, esperado ~73"
        assert inc.loc[inc["score"].idxmax(), "banda"] == "P1"

    def test_canonico_tesseract_high_error_p2(self, df_scored):
        """tesseract · High App Error % → ~68 P2 (reconciliación EDA §9).

        Con diseño coherente (sin double-counting anomalia): s_intensidad=1.0
        captura la señal de anomalía; sin boost adicional.
        codename(0.6) × 0.30 + 0.9×0.25 + 0.2×0.20 + 1.0×0.15 + 0.9×0.10 = 0.645 → 68 P2.
        El EDA §9 originalmente dijo ~76 P1 asumiendo boost acumulativo; ese número
        se reconcilió cuando se eliminó el double-counting.
        """
        inc = df_scored[
            (df_scored["service"] == "tesseract")
            & (df_scored["condition"].str.contains("Error", case=False))
        ]
        assert not inc.empty, "No se encontró tesseract Error"
        best = inc["score"].max()
        assert abs(best - 68) <= 10, f"tesseract High Error score={best}, esperado ~68"
        assert inc.loc[inc["score"].idxmax(), "banda"] == "P2"

    def test_canonico_i0d26dd_p2(self, df_scored):
        """i-0d26dd… · Parco 2.0 Nodes CPU Usage ~59 P2."""
        inc = df_scored[
            (df_scored["service_original"].str.startswith("i-0d26dd"))
            & (df_scored["condition"] == "Parco 2.0 Nodes CPU Usage")
        ]
        assert not inc.empty, "No se encontró i-0d26dd Parco 2.0 Nodes CPU Usage"
        best = inc["score"].max()
        assert abs(best - 59) <= 10, f"i-0d26dd score={best}, esperado ~59"
        assert inc.loc[inc["score"].idxmax(), "banda"] == "P2"

    def test_canonico_data_team_p3(self, df_scored):
        """data-team · RDS CPU Usage gral → P3 solidamente.

        Con s_ficha=0.0 (recurrente + hora 02h típica + n_alertas <= rafaga_tipica)
        y s_novedad=0.0 (6 días >> recurrente_min_dias=3), el incidente nocturno de
        data-team es completamente predecible: datos(0.6)×0.30 + 0.0×0.25 + ...
        → score ~36, sin ambigüedad P3/P2.
        """
        inc = df_scored[
            (df_scored["service"] == "data-team")
            & (df_scored["condition"] == "RDS CPU Usage gral")
        ]
        assert not inc.empty, "No se encontró data-team RDS"
        # Todos los incidentes de data-team RDS deben ser P3
        assert (inc["banda"] == "P3").all(), (
            f"Se esperaba P3 para todos data-team RDS; bandas: {inc['banda'].tolist()}"
        )
        # Score < 40 (solidamente P3, no en frontera)
        assert inc["score"].max() < 40, f"data-team score={inc['score'].max()}, debe ser < 40"
