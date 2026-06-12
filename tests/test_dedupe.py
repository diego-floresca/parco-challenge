"""Tests para src/dedupe.py.

Cubre:
- Ley de conservación: sum(n_alertas) == 458.
- Números de aceptación del EDA: 277 incidentes, 46 ráfagas, 227 alertas en ráfagas.
- sum(n_disparos) == 667.
- Determinismo: dos corridas producen incident_ids idénticos.
- Fixtures sintéticas: ráfaga obvia, alerta solitaria, break por ventana,
  gap exactamente en el límite, registro PayPal (incidents null).
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import yaml
import pandas as pd

from src.ingest import load
from src.normalize import normalize
from src.dedupe import dedupe, _priority_max, _n_disparos, _group_service

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
def df_inc(df_norm, config):
    return dedupe(df_norm, config)


# ---------------------------------------------------------------------------
# Fixtures sintéticas
# ---------------------------------------------------------------------------

def _make_alert(
    dt: datetime,
    service: str = "Orchestrator",
    condition: str = "high request count with status 500",
    channel: str = "sre",
    priority: str = "high",
    incidents_raw: float | None = 1.0,
    error_type: str = "",
    procesador: str = "",
    service_original: str | None = None,
    grupo_criticidad: str = "nucleo",
    source: str = "New Relic",
    policy: str = "Golden Signals",
    tipo_regla: str = "estatica",
    direccion: str = "sobre",
    ventana_eval: str = "5min",
) -> dict:
    return {
        "dt": dt,
        "channel": channel,
        "source": source,
        "service": service,
        "service_original": service_original or service,
        "grupo_criticidad": grupo_criticidad,
        "condition": condition,
        "policy": policy,
        "priority": priority,
        "incidents_raw": incidents_raw,
        "threshold": ">55/5min",
        "tipo_regla": tipo_regla,
        "direccion": direccion,
        "ventana_eval": ventana_eval,
        "error_type": error_type,
        "error_message": "",
        "procesador": procesador,
    }


def _df_from_alerts(alerts: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(alerts)
    df = df.sort_values("dt", kind="stable").reset_index(drop=True)
    return df


def _cfg(ventana_min: int = 30) -> dict:
    return {"pipeline": {"ventana_rafaga_minutos": ventana_min}}


# ---------------------------------------------------------------------------
# Tests de helpers internos
# ---------------------------------------------------------------------------

class TestGroupService:
    """Verifica la lógica de clave de agrupación: typos corregidos, infra separado."""

    def _row(self, service: str, service_original: str) -> pd.Series:
        return pd.Series({"service": service, "service_original": service_original})

    def test_typo_uses_normalized_name(self):
        """Princes (service_original) → Princess (service) → clave = Princess."""
        row = self._row("Princess", "Princes")
        assert _group_service(row) == "Princess"

    def test_known_service_uses_service(self):
        """Servicio sin typo ni infra → clave = service."""
        row = self._row("Orchestrator", "Orchestrator")
        assert _group_service(row) == "Orchestrator"

    def test_infra_uses_service_original(self):
        """i-* normalizado a infra → clave = service_original (EC2 separados)."""
        row = self._row("infra", "i-058689de5ec046291")
        assert _group_service(row) == "i-058689de5ec046291"

    def test_infra_new_parco_uses_service_original(self):
        row = self._row("infra", "new-parco-instance-1")
        assert _group_service(row) == "new-parco-instance-1"


class TestHelpers:
    def test_priority_max_critical_wins(self):
        assert _priority_max(["high", "critical", "high"]) == "critical"

    def test_priority_max_high(self):
        assert _priority_max(["high", None, "high"]) == "high"

    def test_priority_max_all_none(self):
        assert _priority_max([None, None]) is None

    def test_n_disparos_null_counts_as_one(self):
        s = pd.Series([1.0, float("nan"), 2.0])
        assert _n_disparos(s) == 4

    def test_n_disparos_no_nulls(self):
        s = pd.Series([2.0, 3.0, 1.0])
        assert _n_disparos(s) == 6


# ---------------------------------------------------------------------------
# Tests con fixtures sintéticas
# ---------------------------------------------------------------------------

class TestDedupeBasic:
    def test_single_alert_is_one_incident(self):
        t0 = datetime(2025, 6, 1, 12, 0, tzinfo=_TZ)
        alerts = [_make_alert(t0)]
        df = dedupe(_df_from_alerts(alerts), _cfg())
        assert len(df) == 1
        assert df.iloc[0]["n_alertas"] == 1
        assert df.iloc[0]["duracion_min"] == 0.0

    def test_rafaga_obvia_merged(self):
        """Tres alertas del mismo fingerprint con 5 min de gap -> 1 incidente."""
        base = datetime(2025, 6, 1, 12, 0, tzinfo=_TZ)
        alerts = [
            _make_alert(base),
            _make_alert(base + timedelta(minutes=5)),
            _make_alert(base + timedelta(minutes=10)),
        ]
        df = dedupe(_df_from_alerts(alerts), _cfg(30))
        assert len(df) == 1
        assert df.iloc[0]["n_alertas"] == 3
        assert df.iloc[0]["n_disparos"] == 3

    def test_gap_over_window_creates_two_incidents(self):
        """Gap de 31 min > ventana de 30 min -> 2 incidentes."""
        base = datetime(2025, 6, 1, 12, 0, tzinfo=_TZ)
        alerts = [
            _make_alert(base),
            _make_alert(base + timedelta(minutes=31)),
        ]
        df = dedupe(_df_from_alerts(alerts), _cfg(30))
        assert len(df) == 2

    def test_gap_exactly_at_window_is_same_incident(self):
        """Gap de exactamente 30 min -> mismo incidente (<=)."""
        base = datetime(2025, 6, 1, 12, 0, tzinfo=_TZ)
        alerts = [
            _make_alert(base),
            _make_alert(base + timedelta(minutes=30)),
        ]
        df = dedupe(_df_from_alerts(alerts), _cfg(30))
        assert len(df) == 1

    def test_different_fingerprint_different_incident(self):
        """Mismo tiempo pero distinto service -> 2 incidentes."""
        t0 = datetime(2025, 6, 1, 12, 0, tzinfo=_TZ)
        alerts = [
            _make_alert(t0, service="Orchestrator"),
            _make_alert(t0, service="Carts", condition="Carts Throughput high"),
        ]
        df = dedupe(_df_from_alerts(alerts), _cfg())
        assert len(df) == 2

    def test_same_service_diff_condition_diff_incident(self):
        t0 = datetime(2025, 6, 1, 12, 0, tzinfo=_TZ)
        alerts = [
            _make_alert(t0, condition="condicion_A"),
            _make_alert(t0, condition="condicion_B"),
        ]
        df = dedupe(_df_from_alerts(alerts), _cfg())
        assert len(df) == 2

    def test_infra_different_original_is_separate(self):
        """Dos i-* distintos normalizados a infra pero service_original diferente
        → 2 incidentes. Son entidades distintas de la misma clase."""
        base = datetime(2025, 6, 1, 12, 0, tzinfo=_TZ)
        alerts = [
            _make_alert(
                base,
                service="infra",
                service_original="i-aaaa",
                condition="Parco 2.0 Nodes CPU Usage",
            ),
            _make_alert(
                base + timedelta(minutes=1),
                service="infra",
                service_original="i-bbbb",
                condition="Parco 2.0 Nodes CPU Usage",
            ),
        ]
        df = dedupe(_df_from_alerts(alerts), _cfg())
        assert len(df) == 2

    def test_typo_corrected_service_merges_in_window(self):
        """Princes y Princess con la misma condition dentro de ventana
        → 1 incidente (corrección de identidad, la misma entidad)."""
        base = datetime(2025, 6, 1, 12, 0, tzinfo=_TZ)
        alerts = [
            _make_alert(
                base,
                service="Princess",
                service_original="Princes",       # typo
                condition="High App Error percentage",
            ),
            _make_alert(
                base + timedelta(minutes=10),
                service="Princess",
                service_original="Princess",      # correcto
                condition="High App Error percentage",
            ),
        ]
        df = dedupe(_df_from_alerts(alerts), _cfg())
        assert len(df) == 1
        assert df.iloc[0]["n_alertas"] == 2

    def test_paypal_null_incidents(self):
        """incidents_raw=null (PayPal) cuenta como 1 para n_disparos."""
        t0 = datetime(2025, 6, 1, 12, 0, tzinfo=_TZ)
        alerts = [
            _make_alert(t0, incidents_raw=None, priority=None, service="Chargehound",
                        condition="Intermittent Disruption - RESOLVED",
                        policy=None, tipo_regla=None, direccion=None, ventana_eval=None),
        ]
        df = dedupe(_df_from_alerts(alerts), _cfg())
        assert df.iloc[0]["n_disparos"] == 1

    def test_n_disparos_sum_in_rafaga(self):
        """Ráfaga con incidents 2, 3, null -> n_disparos = 6."""
        base = datetime(2025, 6, 1, 12, 0, tzinfo=_TZ)
        alerts = [
            _make_alert(base, incidents_raw=2.0),
            _make_alert(base + timedelta(minutes=5), incidents_raw=3.0),
            _make_alert(base + timedelta(minutes=10), incidents_raw=None),
        ]
        df = dedupe(_df_from_alerts(alerts), _cfg())
        assert df.iloc[0]["n_disparos"] == 6

    def test_duracion_min(self):
        base = datetime(2025, 6, 1, 12, 0, tzinfo=_TZ)
        alerts = [
            _make_alert(base),
            _make_alert(base + timedelta(minutes=15)),
        ]
        df = dedupe(_df_from_alerts(alerts), _cfg())
        assert df.iloc[0]["duracion_min"] == 15.0

    def test_tasa_por_min_single_alert(self):
        """Incidente de 1 alerta: tasa = n_disparos / 1 (duracion_min=0, fuerza mínimo 1)."""
        t0 = datetime(2025, 6, 1, 12, 0, tzinfo=_TZ)
        df = dedupe(_df_from_alerts([_make_alert(t0, incidents_raw=3.0)]), _cfg())
        assert df.iloc[0]["tasa_por_min"] == pytest.approx(3.0, rel=0.01)

    def test_priority_max_in_incident(self):
        base = datetime(2025, 6, 1, 12, 0, tzinfo=_TZ)
        alerts = [
            _make_alert(base, priority="high"),
            _make_alert(base + timedelta(minutes=5), priority="critical"),
        ]
        df = dedupe(_df_from_alerts(alerts), _cfg())
        assert df.iloc[0]["priority_max"] == "critical"


class TestIncidentId:
    def test_ids_are_sequential(self):
        t0 = datetime(2025, 6, 1, 12, 0, tzinfo=_TZ)
        alerts = [
            _make_alert(t0, service="A", condition="c1"),
            _make_alert(t0 + timedelta(hours=1), service="B", condition="c2"),
            _make_alert(t0 + timedelta(hours=2), service="C", condition="c3"),
        ]
        df = dedupe(_df_from_alerts(alerts), _cfg())
        assert list(df["incident_id"]) == ["INC-0001", "INC-0002", "INC-0003"]

    def test_ids_are_chronological(self):
        """INC-0001 debe tener el inicio más temprano."""
        t0 = datetime(2025, 6, 1, 12, 0, tzinfo=_TZ)
        alerts = [
            _make_alert(t0 + timedelta(hours=2), service="Late", condition="c"),
            _make_alert(t0, service="Early", condition="c"),
        ]
        df = dedupe(_df_from_alerts(alerts), _cfg())
        # Ordenado por inicio: Early primero
        assert df.iloc[0]["incident_id"] == "INC-0001"
        assert df.iloc[0]["service"] == "Early"

    def test_fingerprint_column_uses_normalized_service(self):
        """fingerprint = '{service}::{condition}' con nombre normalizado."""
        t0 = datetime(2025, 6, 1, 12, 0, tzinfo=_TZ)
        alerts = [
            _make_alert(t0, service="infra", service_original="i-abc123",
                        condition="Parco 2.0 Nodes CPU Usage"),
        ]
        df = dedupe(_df_from_alerts(alerts), _cfg())
        assert df.iloc[0]["fingerprint"] == "infra::Parco 2.0 Nodes CPU Usage"


# ---------------------------------------------------------------------------
# Tests de aceptación sobre el archivo real
# ---------------------------------------------------------------------------

class TestAcceptanceDedupe:
    """Afirma los números de aceptación del EDA."""

    def test_total_incidents(self, df_inc):
        """[ACEPTACIÓN] 277 incidentes con ventana 30 min."""
        assert len(df_inc) == 277

    def test_conservation_law(self, df_inc):
        """[INVARIANTE] sum(n_alertas) == 458 — ninguna alerta se pierde."""
        assert df_inc["n_alertas"].sum() == 458

    def test_n_disparos_total(self, df_inc):
        """sum(n_disparos) == 667 (incidents_raw con null->1)."""
        assert df_inc["n_disparos"].sum() == 667

    def test_rafagas_count(self, df_inc):
        """[ACEPTACIÓN] 46 ráfagas (incidentes con n_alertas > 1)."""
        rafagas = df_inc[df_inc["n_alertas"] > 1]
        assert len(rafagas) == 46

    def test_alertas_en_rafagas(self, df_inc):
        """[ACEPTACIÓN] 227 alertas en ráfagas."""
        rafagas = df_inc[df_inc["n_alertas"] > 1]
        assert rafagas["n_alertas"].sum() == 227

    def test_incident_ids_are_unique(self, df_inc):
        assert df_inc["incident_id"].nunique() == len(df_inc)

    def test_incident_ids_format(self, df_inc):
        """Todos los IDs siguen el patrón INC-NNNN."""
        import re
        pattern = re.compile(r"^INC-\d{4}$")
        assert df_inc["incident_id"].apply(lambda x: bool(pattern.match(x))).all()

    def test_channel_distribution(self, df_inc):
        """sre tiene más incidentes que cx."""
        counts = df_inc["channel"].value_counts()
        assert counts["sre"] > counts["monitoring-ops-cx"]

    def test_inicio_before_fin(self, df_inc):
        assert (df_inc["fin"] >= df_inc["inicio"]).all()

    def test_duracion_non_negative(self, df_inc):
        assert (df_inc["duracion_min"] >= 0).all()

    def test_n_alertas_positive(self, df_inc):
        assert (df_inc["n_alertas"] >= 1).all()

    def test_n_disparos_positive(self, df_inc):
        assert (df_inc["n_disparos"] >= 1).all()

    def test_fingerprint_format(self, df_inc):
        """fingerprint = '{service}::{condition}'"""
        malformed = df_inc[~df_inc["fingerprint"].str.contains("::", regex=False)]
        assert len(malformed) == 0

    def test_paypal_incidents_have_null_priority(self, df_inc):
        paypal = df_inc[df_inc["source"] == "PayPal Status"]
        assert len(paypal) == 3
        assert paypal["priority_max"].isna().all()

    def test_sre_cx_incidents_only(self, df_inc):
        channels = set(df_inc["channel"].unique())
        assert channels == {"sre", "monitoring-ops-cx"}

    def test_cx_error_type_present(self, df_inc):
        cx = df_inc[df_inc["channel"] == "monitoring-ops-cx"]
        assert (cx["error_type"] != "").all()

    def test_sre_error_type_empty(self, df_inc):
        sre = df_inc[df_inc["channel"] == "sre"]
        assert (sre["error_type"] == "").all()


class TestDeterminism:
    """Correr dos veces -> incident_ids idénticos."""

    def test_same_ids_on_two_runs(self, df_norm, config):
        inc1 = dedupe(df_norm.copy(), config)
        inc2 = dedupe(df_norm.copy(), config)
        assert list(inc1["incident_id"]) == list(inc2["incident_id"])

    def test_same_inicio_on_two_runs(self, df_norm, config):
        inc1 = dedupe(df_norm.copy(), config)
        inc2 = dedupe(df_norm.copy(), config)
        assert list(inc1["inicio"]) == list(inc2["inicio"])
