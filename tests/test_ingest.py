"""Tests para src/ingest.py.

Cubre:
- Números de aceptación sobre el archivo real (EDA §1).
- Fixtures sintéticas: JSON roto, lista vacía, esquema desconocido.
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from src.ingest import load, validate, KNOWN_SCHEMAS

# Ruta al archivo real de entrada
RAW_JSON = Path(__file__).parents[1] / "data" / "raw" / "alerts_combined.json"


# ---------------------------------------------------------------------------
# Fixtures sintéticas
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_base_record():
    return {
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


@pytest.fixture
def minimal_cx_record():
    return {
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


@pytest.fixture
def minimal_paypal_record():
    return {
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


# ---------------------------------------------------------------------------
# Tests con el archivo real
# ---------------------------------------------------------------------------

class TestAcceptanceNumbers:
    """Afirma los números de aceptación del EDA sobre el JSON real."""

    @pytest.fixture(autouse=True)
    def load_real(self):
        self.records = load(RAW_JSON)
        self.report = validate(self.records)

    def test_total_records(self):
        assert self.report["total"] == 458

    def test_schema_counts(self):
        counts = self.report["schema_counts"]
        # 360 base, 95 cx, 3 paypal
        assert counts["base"] == 360
        assert counts["cx"] == 95
        assert counts["paypal"] == 3

    def test_channel_counts(self):
        ch = self.report["channel_counts"]
        assert ch["sre"] == 363
        assert ch["monitoring-ops-cx"] == 95

    def test_source_counts(self):
        src = self.report["source_counts"]
        assert src["New Relic"] == 455
        assert src["PayPal Status"] == 3

    def test_no_unknown_schemas(self):
        # validate() lanzaría ValueError si hubiera esquemas desconocidos;
        # si llegamos aquí, pasó sin excepción.
        assert self.report["total"] == 458


# ---------------------------------------------------------------------------
# Tests con fixtures sintéticas
# ---------------------------------------------------------------------------

class TestLoad:
    def test_load_returns_list(self, tmp_path, minimal_base_record):
        p = tmp_path / "test.json"
        p.write_text(json.dumps([minimal_base_record]))
        records = load(p)
        assert isinstance(records, list)
        assert len(records) == 1

    def test_load_raises_on_non_array(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps({"not": "an array"}))
        with pytest.raises(ValueError, match="array JSON"):
            load(p)

    def test_load_raises_on_invalid_json(self, tmp_path):
        p = tmp_path / "broken.json"
        p.write_text("{broken json[")
        with pytest.raises(Exception):
            load(p)

    def test_load_raises_on_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load(tmp_path / "nonexistent.json")


class TestValidate:
    def test_validate_accepts_known_schemas(
        self, minimal_base_record, minimal_cx_record, minimal_paypal_record
    ):
        records = [minimal_base_record, minimal_cx_record, minimal_paypal_record]
        report = validate(records)
        assert report["total"] == 3
        assert report["schema_counts"]["base"] == 1
        assert report["schema_counts"]["cx"] == 1
        assert report["schema_counts"]["paypal"] == 1

    def test_validate_raises_on_empty_list(self):
        with pytest.raises(ValueError, match="vacía"):
            validate([])

    def test_validate_raises_on_unknown_schema(self, minimal_base_record):
        bad_record = dict(minimal_base_record)
        bad_record["unknown_field"] = "surprise"
        with pytest.raises(ValueError, match="esquema desconocido"):
            validate([bad_record])

    def test_validate_channel_counts(
        self, minimal_base_record, minimal_cx_record, minimal_paypal_record
    ):
        records = [minimal_base_record, minimal_cx_record, minimal_paypal_record]
        report = validate(records)
        # base+paypal -> sre; cx -> monitoring-ops-cx
        assert report["channel_counts"]["sre"] == 2
        assert report["channel_counts"]["monitoring-ops-cx"] == 1

    def test_validate_source_counts(
        self, minimal_base_record, minimal_cx_record, minimal_paypal_record
    ):
        records = [minimal_base_record, minimal_cx_record, minimal_paypal_record]
        report = validate(records)
        assert report["source_counts"]["New Relic"] == 2
        assert report["source_counts"]["PayPal Status"] == 1
