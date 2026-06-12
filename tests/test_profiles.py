"""Tests para src/profiles.py.

Cubre:
- Ficha de (data-team, RDS CPU Usage gral) en sre:
    dias_visto ≈ 6, horas_tipicas incluye la hora 2 (pico nocturno).
- Separación de canales: sre y cx nunca mezclan fichas.
- Fixtures sintéticas: fingerprint nunca visto (None), sello_finde.
- rafaga_tipica: mediana de n_alertas.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import yaml
import pandas as pd

from src.ingest import load
from src.normalize import normalize
from src.dedupe import dedupe
from src.profiles import build_profiles, get_profile

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
def df_inc(config):
    records = load(RAW_JSON)
    df_norm = normalize(records, config)
    return dedupe(df_norm, config)


@pytest.fixture(scope="session")
def profiles(df_inc):
    return build_profiles(df_inc)


# ---------------------------------------------------------------------------
# Fixtures sintéticas
# ---------------------------------------------------------------------------

def _incident_row(
    channel: str,
    fingerprint: str,
    inicio: datetime,
    n_alertas: int = 1,
) -> dict:
    return {
        "incident_id": "INC-0001",
        "channel": channel,
        "fingerprint": fingerprint,
        "service": fingerprint.split("::")[0],
        "service_original": fingerprint.split("::")[0],
        "condition": fingerprint.split("::", 1)[1],
        "inicio": inicio,
        "fin": inicio,
        "n_alertas": n_alertas,
        "n_disparos": n_alertas,
        "duracion_min": 0.0,
    }


def _df_inc(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Tests de casos canónicos con datos reales
# ---------------------------------------------------------------------------

class TestDataTeamRDSProfile:
    """Caso canónico: data-team / RDS CPU Usage gral en sre."""

    @pytest.fixture(autouse=True)
    def _profile(self, profiles):
        self.p = get_profile(profiles, "sre", "data-team::RDS CPU Usage gral")

    def test_profile_exists(self):
        assert self.p is not None

    def test_dias_visto(self):
        """~6 días distintos de actividad (EDA §8 + checkpoint)."""
        assert self.p["dias_visto"] == 6

    def test_hora_dos_en_tipicas(self):
        """El pico de 02h debe estar en horas_tipicas (EDA §8: pico nocturno ~02h)."""
        assert 2 in self.p["horas_tipicas"]

    def test_sello_finde(self):
        """data-team RDS tiene actividad en fin de semana."""
        assert isinstance(self.p["sello_finde"], bool)

    def test_rafaga_tipica(self):
        """rafaga_tipica es float positiva."""
        assert self.p["rafaga_tipica"] > 0


class TestCanalSeparation:
    """sre y cx nunca mezclan fichas."""

    def test_cx_fingerprint_not_in_sre(self, profiles):
        """El fingerprint de cx no debe aparecer con channel=sre."""
        cx_fps = set(
            profiles[profiles["channel"] == "monitoring-ops-cx"]["fingerprint"]
        )
        sre_fps = set(profiles[profiles["channel"] == "sre"]["fingerprint"])
        # Los fingerprints de cx (Hairs::Payments rejected hairs CX) no están en sre
        overlap = cx_fps & sre_fps
        assert len(overlap) == 0, f"Overlap inesperado: {overlap}"

    def test_distinct_channels(self, profiles):
        channels = set(profiles["channel"].unique())
        assert "sre" in channels
        assert "monitoring-ops-cx" in channels


class TestGetProfile:
    def test_unknown_fingerprint_returns_none(self, profiles):
        result = get_profile(profiles, "sre", "servicio_fantasma::condicion_x")
        assert result is None

    def test_wrong_channel_returns_none(self, profiles):
        """Un fingerprint que existe en sre no se encuentra en cx."""
        # Tomamos un fingerprint conocido de sre
        sre_fp = profiles[profiles["channel"] == "sre"]["fingerprint"].iloc[0]
        result = get_profile(profiles, "monitoring-ops-cx", sre_fp)
        assert result is None


# ---------------------------------------------------------------------------
# Tests con fixtures sintéticas
# ---------------------------------------------------------------------------

class TestBuildProfilesSynthetic:

    def test_single_incident_profile(self):
        t = datetime(2025, 6, 1, 14, 30, tzinfo=_TZ)
        rows = [_incident_row("sre", "Foo::bar_condition", t, n_alertas=3)]
        profiles = build_profiles(_df_inc(rows))
        p = get_profile(profiles, "sre", "Foo::bar_condition")
        assert p is not None
        assert p["dias_visto"] == 1
        assert 14 in p["horas_tipicas"]
        assert p["rafaga_tipica"] == 3.0
        # 2025-06-01 es domingo (weekday=6) → sello_finde=True
        assert p["sello_finde"] is True

    def test_sello_finde_weekday(self):
        # 2025-06-02 es lunes (weekday=0)
        t = datetime(2025, 6, 2, 10, 0, tzinfo=_TZ)
        rows = [_incident_row("sre", "X::y", t)]
        profiles = build_profiles(_df_inc(rows))
        p = get_profile(profiles, "sre", "X::y")
        assert p["sello_finde"] is False

    def test_sello_finde_true(self):
        # 2025-05-31 es sábado (weekday=5)
        t = datetime(2025, 5, 31, 20, 0, tzinfo=_TZ)
        rows = [_incident_row("sre", "X::y", t)]
        profiles = build_profiles(_df_inc(rows))
        p = get_profile(profiles, "sre", "X::y")
        assert p["sello_finde"] is True

    def test_dias_visto_multiple_same_day(self):
        """Dos incidentes en el mismo día cuentan como 1 día."""
        t1 = datetime(2025, 6, 2, 10, 0, tzinfo=_TZ)
        t2 = datetime(2025, 6, 2, 15, 0, tzinfo=_TZ)
        rows = [
            _incident_row("sre", "X::y", t1),
            _incident_row("sre", "X::y", t2),
        ]
        profiles = build_profiles(_df_inc(rows))
        p = get_profile(profiles, "sre", "X::y")
        assert p["dias_visto"] == 1

    def test_dias_visto_multiple_days(self):
        days = [
            datetime(2025, 6, 2, 10, 0, tzinfo=_TZ),
            datetime(2025, 6, 3, 10, 0, tzinfo=_TZ),
            datetime(2025, 6, 4, 10, 0, tzinfo=_TZ),
        ]
        rows = [_incident_row("sre", "X::y", d) for d in days]
        profiles = build_profiles(_df_inc(rows))
        p = get_profile(profiles, "sre", "X::y")
        assert p["dias_visto"] == 3

    def test_horas_tipicas_unique_sorted(self):
        """Dos incidentes a la misma hora -> horas_tipicas contiene esa hora una vez."""
        t1 = datetime(2025, 6, 2, 2, 0, tzinfo=_TZ)
        t2 = datetime(2025, 6, 3, 2, 0, tzinfo=_TZ)
        rows = [
            _incident_row("sre", "X::y", t1),
            _incident_row("sre", "X::y", t2),
        ]
        profiles = build_profiles(_df_inc(rows))
        p = get_profile(profiles, "sre", "X::y")
        assert p["horas_tipicas"] == [2]

    def test_horas_tipicas_multiple_hours(self):
        hours = [2, 14, 22]
        rows = [
            _incident_row("sre", "X::y", datetime(2025, 6, 2 + i, h, 0, tzinfo=_TZ))
            for i, h in enumerate(hours)
        ]
        profiles = build_profiles(_df_inc(rows))
        p = get_profile(profiles, "sre", "X::y")
        assert p["horas_tipicas"] == sorted(hours)

    def test_rafaga_tipica_median(self):
        """Mediana de [1, 3, 5] = 3."""
        t = datetime(2025, 6, 2, 10, 0, tzinfo=_TZ)
        rows = [
            _incident_row("sre", "X::y", t + timedelta(hours=i), n_alertas=v)
            for i, v in enumerate([1, 3, 5])
        ]
        profiles = build_profiles(_df_inc(rows))
        p = get_profile(profiles, "sre", "X::y")
        assert p["rafaga_tipica"] == 3.0

    def test_channel_isolation_synthetic(self):
        """Mismo fingerprint en canales distintos -> perfiles distintos."""
        t = datetime(2025, 6, 2, 10, 0, tzinfo=_TZ)
        rows = [
            _incident_row("sre", "X::y", t, n_alertas=5),
            _incident_row("monitoring-ops-cx", "X::y", t + timedelta(days=300), n_alertas=1),
        ]
        profiles = build_profiles(_df_inc(rows))
        p_sre = get_profile(profiles, "sre", "X::y")
        p_cx = get_profile(profiles, "monitoring-ops-cx", "X::y")
        assert p_sre is not None
        assert p_cx is not None
        assert p_sre["rafaga_tipica"] == 5.0
        assert p_cx["rafaga_tipica"] == 1.0


# ---------------------------------------------------------------------------
# Tests de aceptación sobre el archivo real
# ---------------------------------------------------------------------------

class TestAcceptanceProfiles:

    def test_profiles_exist(self, profiles):
        assert len(profiles) > 0

    def test_channels_are_separate(self, profiles):
        """Cada fila tiene exactamente un canal; los canales son los dos conocidos."""
        valid_channels = {"sre", "monitoring-ops-cx"}
        assert set(profiles["channel"].unique()).issubset(valid_channels)

    def test_all_incidents_have_profile(self, df_inc, profiles):
        """Cada incidente tiene una ficha para su (channel, fingerprint)."""
        profile_keys = set(
            zip(profiles["channel"], profiles["fingerprint"])
        )
        incident_keys = set(zip(df_inc["channel"], df_inc["fingerprint"]))
        assert incident_keys.issubset(profile_keys)

    def test_dias_visto_positive(self, profiles):
        assert (profiles["dias_visto"] >= 1).all()

    def test_rafaga_tipica_positive(self, profiles):
        assert (profiles["rafaga_tipica"] >= 1.0).all()

    def test_sello_finde_is_bool(self, profiles):
        assert profiles["sello_finde"].dtype == bool

    def test_horas_tipicas_is_list(self, profiles):
        assert profiles["horas_tipicas"].apply(lambda x: isinstance(x, list)).all()

    def test_orchestrator_profile_exists(self, profiles):
        p = get_profile(
            profiles, "sre",
            "Orchestrator::high request count with status 500"
        )
        assert p is not None
        assert p["dias_visto"] >= 1

    def test_cx_profile_exists(self, profiles):
        p = get_profile(
            profiles,
            "monitoring-ops-cx",
            "Hairs::Payments rejected hairs CX",
        )
        assert p is not None
