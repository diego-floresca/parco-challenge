"""Tests para src/normalize.py.

Cubre:
- Regla de relojes por canal (sre -> ts epoch, cx -> timestamp ISO).
- Normalización de service: typo Princes->Princess, grupo infra.
- Números de aceptación sobre el archivo real (28 services crudos, 23 conditions, etc.).
- Fixtures sintéticas: timestamp roto, servicio desconocido, registro PayPal.
- Derivados de threshold (tipo_regla, direccion, ventana_eval).
- Extracción de procesador de error_message.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from src.ingest import load, validate
from src.normalize import (
    normalize,
    normalize_service,
    get_grupo_criticidad,
    parse_threshold,
    extract_procesador,
)
import yaml

# Rutas
RAW_JSON = Path(__file__).parents[1] / "data" / "raw" / "alerts_combined.json"
CONFIG_PATH = Path(__file__).parents[1] / "config.yaml"

_TZ_MINUS6 = timezone(timedelta(hours=-6))


# ---------------------------------------------------------------------------
# Fixture: config real
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def config():
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def real_records():
    return load(RAW_JSON)


@pytest.fixture(scope="session")
def df_normalized(real_records, config):
    return normalize(real_records, config)


# ---------------------------------------------------------------------------
# Fixtures sintéticas reutilizables
# ---------------------------------------------------------------------------

def _sre_record(**kwargs):
    base = {
        "ts": "1749647379.517959",
        "timestamp": "2025-06-11T07:09:39-06:00",
        "source": "New Relic",
        "priority": "high",
        "service": "Princess",
        "condition": "High Application Response Time gral",
        "threshold": ">1800ms/5min",
        "policy": "Golden Signals",
        "incidents": 1,
        "channel": "sre",
    }
    base.update(kwargs)
    return base


def _cx_record(**kwargs):
    base = {
        "ts": "1742028200",
        "timestamp": "2026-03-24T12:54:07-06:00",
        "channel": "monitoring-ops-cx",
        "source": "New Relic",
        "priority": "high",
        "service": "Hairs",
        "condition": "Payments rejected hairs CX",
        "threshold": ">=5/5min",
        "policy": "CX",
        "error_type": "IMPOSSIBLE_TO_CHARGE",
        "error_message": "IMPOSSIBLE_TO_CHARGE",
        "incidents": 1,
    }
    base.update(kwargs)
    return base


def _paypal_record(**kwargs):
    base = {
        "ts": "1749625354.706079",
        "timestamp": "2025-06-11T01:02:34-06:00",
        "source": "PayPal Status",
        "priority": None,
        "service": "Chargehound",
        "condition": "Intermittent Disruption - RESOLVED",
        "policy": None,
        "incidents": None,
        "channel": "sre",
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Tests de reloj por canal
# ---------------------------------------------------------------------------

class TestClockByChannel:
    """La regla operativa: sre usa ts epoch; cx usa timestamp ISO."""

    def test_sre_uses_ts_epoch(self, config):
        # ts epoch 1749647379.517959 -> 2025-06-11T07:09:39.517959-06:00
        rec = _sre_record(ts="1749647379.517959", timestamp="2025-06-11T00:00:00-06:00")
        df = normalize([rec], config)
        dt = df["dt"].iloc[0]
        assert dt.year == 2025
        assert dt.month == 6
        assert dt.day == 11
        assert dt.hour == 7
        assert dt.minute == 9

    def test_cx_uses_iso_timestamp(self, config):
        # timestamp ISO 2026-03-24T12:54:07-06:00 (ts sintético ignorado)
        rec = _cx_record(ts="9999999999", timestamp="2026-03-24T12:54:07-06:00")
        df = normalize([rec], config)
        dt = df["dt"].iloc[0]
        assert dt.year == 2026
        assert dt.month == 3
        assert dt.day == 24
        assert dt.hour == 12
        assert dt.minute == 54

    def test_dt_is_tz_aware(self, config):
        df = normalize([_sre_record()], config)
        assert df["dt"].iloc[0].tzinfo is not None

    def test_sre_ts_with_decimals(self, config):
        """201 de 363 registros sre tienen decimales en ts."""
        rec = _sre_record(ts="1749630998.335369")
        df = normalize([rec], config)
        dt = df["dt"].iloc[0]
        assert dt.year == 2025

    def test_sre_ts_as_integer_string(self, config):
        """257 registros sre tienen ts sin decimales."""
        rec = _sre_record(ts="1749647379")
        df = normalize([rec], config)
        assert df["dt"].iloc[0].year == 2025


# ---------------------------------------------------------------------------
# Tests de normalización de service
# ---------------------------------------------------------------------------

class TestNormalizeService:
    def test_princes_becomes_princess(self, config):
        service, original = normalize_service("Princes", config)
        assert service == "Princess"
        assert original == "Princes"

    def test_princess_stays_princess(self, config):
        service, original = normalize_service("Princess", config)
        assert service == "Princess"
        assert original == "Princess"

    def test_ec2_instance_becomes_infra(self, config):
        for raw in ["i-058689de5ec046291", "i-0d26dd24e2a69bff0",
                    "i-04acbab68c9357917", "i-0d568d70a0847d5b6"]:
            service, original = normalize_service(raw, config)
            assert service == "infra", f"{raw} debería ser infra"
            assert original == raw

    def test_new_parco_instance_becomes_infra(self, config):
        for raw in ["new-parco-instance-1", "new-parco-instance-5"]:
            service, original = normalize_service(raw, config)
            assert service == "infra", f"{raw} debería ser infra"
            assert original == raw

    def test_known_service_unchanged(self, config):
        for svc in ["Orchestrator", "Hairs", "Carts", "data-team"]:
            service, original = normalize_service(svc, config)
            assert service == svc
            assert original == svc

    def test_unknown_service_unchanged(self, config):
        service, original = normalize_service("ServicioNuevo", config)
        assert service == "ServicioNuevo"
        assert original == "ServicioNuevo"


class TestNormalizeInDataFrame:
    """Verifica normalización dentro de normalize() completo."""

    def test_princes_in_df(self, config):
        rec = _sre_record(service="Princes")
        df = normalize([rec], config)
        assert df["service"].iloc[0] == "Princess"
        assert df["service_original"].iloc[0] == "Princes"

    def test_infra_in_df(self, config):
        rec = _sre_record(service="i-058689de5ec046291")
        df = normalize([rec], config)
        assert df["service"].iloc[0] == "infra"
        assert df["service_original"].iloc[0] == "i-058689de5ec046291"


# ---------------------------------------------------------------------------
# Tests de grupo_criticidad
# ---------------------------------------------------------------------------

class TestGrupoCriticidad:
    def test_hairs_is_pagos(self, config):
        assert get_grupo_criticidad("Hairs", config) == "pagos"

    def test_orchestrator_is_nucleo(self, config):
        assert get_grupo_criticidad("Orchestrator", config) == "nucleo"

    def test_data_team_is_datos(self, config):
        assert get_grupo_criticidad("data-team", config) == "datos"

    def test_infra_group(self, config):
        assert get_grupo_criticidad("infra", config) == "infra"

    def test_wiki_is_web(self, config):
        assert get_grupo_criticidad("Wiki", config) == "web"

    def test_tesseract_is_codename(self, config):
        assert get_grupo_criticidad("tesseract", config) == "codename"

    def test_unknown_returns_default(self, config):
        assert get_grupo_criticidad("ServicioDesconocido", config) == "default"


# ---------------------------------------------------------------------------
# Tests de parse_threshold
# ---------------------------------------------------------------------------

class TestParseThreshold:
    def test_static_greater_than(self):
        tipo, dir_, ventana = parse_threshold(">1800ms/5min")
        assert tipo == "estatica"
        assert dir_ == "sobre"
        assert ventana == "5min"

    def test_static_less_than(self):
        tipo, dir_, ventana = parse_threshold("<0.5/3min")
        assert tipo == "estatica"
        assert dir_ == "bajo"
        assert ventana == "3min"

    def test_baseline_is_anomalia(self):
        tipo, dir_, ventana = parse_threshold("baseline/10min")
        assert tipo == "anomalia"
        assert ventana == "10min"

    def test_threshold_with_percent(self):
        tipo, dir_, ventana = parse_threshold(">55%/10min")
        assert tipo == "estatica"
        assert dir_ == "sobre"
        assert ventana == "10min"

    def test_null_threshold(self):
        tipo, dir_, ventana = parse_threshold(None)
        assert tipo is None
        assert dir_ is None
        assert ventana is None

    def test_empty_string_threshold(self):
        tipo, dir_, ventana = parse_threshold("")
        assert tipo is None

    def test_gte_operator_is_sobre(self):
        """>=5/5min contiene > -> 'sobre'."""
        tipo, dir_, ventana = parse_threshold(">=5/5min")
        assert dir_ == "sobre"


# ---------------------------------------------------------------------------
# Tests de extract_procesador
# ---------------------------------------------------------------------------

class TestExtractProcesador:
    def test_conekta_detected(self):
        msg = "El banco emisor rechazó el pago sin más detalles (Conekta)"
        assert extract_procesador(msg, ["Conekta", "Mercadopago", "PayPal"]) == "Conekta"

    def test_mercadopago_detected(self):
        msg = "Error from Mercadopago"
        assert extract_procesador(msg, ["Conekta", "Mercadopago", "PayPal"]) == "Mercadopago"

    def test_paypal_case_insensitive(self):
        msg = "PAYPAL_UNAVAILABLE"
        assert extract_procesador(msg, ["Conekta", "Mercadopago", "PayPal"]) == "PayPal"

    def test_no_processor_returns_empty(self):
        msg = "INSUFFICIENT_FUNDS"
        assert extract_procesador(msg, ["Conekta", "Mercadopago", "PayPal"]) == ""

    def test_none_returns_empty(self):
        assert extract_procesador(None, ["Conekta", "Mercadopago", "PayPal"]) == ""


# ---------------------------------------------------------------------------
# Tests de registros PayPal Status
# ---------------------------------------------------------------------------

class TestPayPalRecords:
    def test_paypal_record_processed(self, config):
        rec = _paypal_record()
        df = normalize([rec], config)
        row = df.iloc[0]
        # PayPal Status está en sre -> usa ts epoch
        assert row["source"] == "PayPal Status"
        assert row["channel"] == "sre"
        # Sin threshold -> todos los derivados son None
        assert row["tipo_regla"] is None
        assert row["direccion"] is None
        assert row["ventana_eval"] is None
        # incidents_raw es null (se guarda sin imputar)
        assert row["incidents_raw"] is None
        # No hay error_type/procesador (es sre)
        assert row["error_type"] == ""
        assert row["procesador"] == ""

    def test_paypal_chargehound_criticidad(self, config):
        rec = _paypal_record(service="Chargehound")
        df = normalize([rec], config)
        assert df["grupo_criticidad"].iloc[0] == "pagos"


# ---------------------------------------------------------------------------
# Tests de aceptación sobre el archivo real
# ---------------------------------------------------------------------------

class TestAcceptanceNormalize:
    """Afirma invariantes del EDA sobre el DataFrame normalizado completo."""

    def test_total_rows(self, df_normalized):
        assert len(df_normalized) == 458

    def test_no_row_lost(self, df_normalized):
        """Invariante: ninguna alerta se pierde."""
        assert len(df_normalized) == 458

    def test_channel_distribution(self, df_normalized):
        counts = df_normalized["channel"].value_counts()
        assert counts["sre"] == 363
        assert counts["monitoring-ops-cx"] == 95

    def test_princess_unification(self, df_normalized):
        """Princes (1 raw) + Princess (11 raw) = 12 Princess normalizados."""
        princess_rows = df_normalized[df_normalized["service"] == "Princess"]
        assert len(princess_rows) == 12  # 1 Princes + 11 Princess originales

    def test_princes_gone_from_service_column(self, df_normalized):
        assert "Princes" not in df_normalized["service"].values

    def test_princes_preserved_in_service_original(self, df_normalized):
        assert "Princes" in df_normalized["service_original"].values

    def test_infra_group_count(self, df_normalized):
        """i-* (22) + new-parco-instance-* (8) = 30 infra."""
        infra_rows = df_normalized[df_normalized["service"] == "infra"]
        assert len(infra_rows) == 30

    def test_infra_originals_preserved(self, df_normalized):
        infra_rows = df_normalized[df_normalized["service"] == "infra"]
        originals = set(infra_rows["service_original"].unique())
        expected = {
            "i-058689de5ec046291", "i-0d26dd24e2a69bff0",
            "i-04acbab68c9357917", "i-0d568d70a0847d5b6",
            "new-parco-instance-1", "new-parco-instance-5",
        }
        assert originals == expected

    def test_unique_conditions(self, df_normalized):
        assert df_normalized["condition"].nunique() == 23

    def test_cx_has_error_type(self, df_normalized):
        cx = df_normalized[df_normalized["channel"] == "monitoring-ops-cx"]
        assert len(cx) == 95
        assert (cx["error_type"] != "").all(), "Todos los cx deben tener error_type"

    def test_sre_has_no_error_type(self, df_normalized):
        sre = df_normalized[df_normalized["channel"] == "sre"]
        assert (sre["error_type"] == "").all()

    def test_cx_error_type_composition(self, df_normalized):
        cx = df_normalized[df_normalized["channel"] == "monitoring-ops-cx"]
        et = cx["error_type"].value_counts()
        assert et["INSUFFICIENT_FUNDS"] == 28
        assert et["IMPOSSIBLE_TO_CHARGE"] == 25
        assert et["CARD_DECLINED"] == 23
        assert et["BANK_REJECTED"] == 12

    def test_incidents_raw_null_count(self, df_normalized):
        """3 registros de PayPal Status tienen incidents null."""
        null_count = df_normalized["incidents_raw"].isna().sum()
        assert null_count == 3

    def test_incidents_sum(self, df_normalized):
        """Suma de incidents_raw (null->1) = 667.
        EDA dice '≈ 664' (aproximado); el valor exacto calculado es 667.
        Distribución: 1->298, 2->131, 3->14, 4->6, 6->4, 7->2, null->3.
        """
        total = df_normalized["incidents_raw"].fillna(1).sum()
        assert total == 667

    def test_paypal_count(self, df_normalized):
        paypal_rows = df_normalized[df_normalized["source"] == "PayPal Status"]
        assert len(paypal_rows) == 3

    def test_dt_sorted_ascending(self, df_normalized):
        dts = df_normalized["dt"].tolist()
        assert dts == sorted(dts)

    def test_dt_all_tz_aware(self, df_normalized):
        assert df_normalized["dt"].apply(lambda x: x.tzinfo is not None).all()

    def test_baseline_thresholds_are_anomalia(self, df_normalized):
        baseline = df_normalized[
            df_normalized["threshold"].fillna("").str.contains("baseline")
        ]
        assert (baseline["tipo_regla"] == "anomalia").all()
        assert len(baseline) == 53

    def test_direction_bajo_for_less_than(self, df_normalized):
        """Thresholds con '<' deben tener direccion='bajo'."""
        lt = df_normalized[
            df_normalized["threshold"].fillna("").str.startswith("<")
        ]
        assert (lt["direccion"] == "bajo").all()

    def test_paypal_null_threshold_derivados(self, df_normalized):
        paypal_rows = df_normalized[df_normalized["source"] == "PayPal Status"]
        assert paypal_rows["tipo_regla"].isna().all()
        assert paypal_rows["direccion"].isna().all()
        assert paypal_rows["ventana_eval"].isna().all()
