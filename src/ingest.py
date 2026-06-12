"""Layer 1 — carga y validación del JSON de entrada.

Responsabilidades:
- Leer el archivo JSON y devolver una lista de dicts crudos.
- Verificar que cada registro tiene uno de los 3 esquemas conocidos.
- Reportar conteos de canal, source y esquema (usados por tests de aceptación).

NO hace ninguna transformación de valores ni lógica de negocio.
"""
from __future__ import annotations

import json
from pathlib import Path


# Los tres esquemas de llaves que existen en alerts_combined.json (EDA §1).
# Se comparan como frozensets para que el orden de keys no importe.
_SCHEMA_BASE = frozenset({
    "ts", "timestamp", "source", "priority", "service", "condition",
    "threshold", "policy", "incidents", "channel",
})
_SCHEMA_CX = frozenset({
    "ts", "timestamp", "source", "priority", "service", "condition",
    "threshold", "policy", "incidents", "channel",
    "error_type", "error_message",
})
_SCHEMA_PAYPAL = frozenset({
    "ts", "timestamp", "source", "priority", "service", "condition",
    "policy", "incidents", "channel",
    # sin threshold — los 3 registros de PayPal Status (EDA §1, regla 8)
})

KNOWN_SCHEMAS: frozenset[frozenset] = frozenset({_SCHEMA_BASE, _SCHEMA_CX, _SCHEMA_PAYPAL})


def load(path: Path | str) -> list[dict]:
    """Carga alerts_combined.json y devuelve la lista de registros crudos."""
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        records = json.load(f)
    if not isinstance(records, list):
        raise ValueError(f"Se esperaba un array JSON; se recibió {type(records).__name__}")
    return records


def validate(records: list[dict]) -> dict:
    """
    Verifica invariantes estructurales.

    Devuelve un dict de reporte con conteos.
    Lanza ValueError si hay registros con esquema desconocido.
    """
    if not records:
        raise ValueError("La lista de registros está vacía")

    unknown: list[tuple[int, list[str]]] = []
    schema_counts: dict[str, int] = {}
    channel_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}

    for i, rec in enumerate(records):
        keys = frozenset(rec.keys())
        if keys not in KNOWN_SCHEMAS:
            unknown.append((i, sorted(keys)))

        # Clave de esquema legible para el reporte
        schema_key = _schema_label(keys)
        schema_counts[schema_key] = schema_counts.get(schema_key, 0) + 1

        ch = rec.get("channel", "<missing>")
        channel_counts[ch] = channel_counts.get(ch, 0) + 1

        src = rec.get("source", "<missing>")
        source_counts[src] = source_counts.get(src, 0) + 1

    if unknown:
        sample = unknown[:3]
        raise ValueError(
            f"Registros con esquema desconocido (mostrando hasta 3): {sample}"
        )

    return {
        "total": len(records),
        "schema_counts": schema_counts,
        "channel_counts": channel_counts,
        "source_counts": source_counts,
    }


def _schema_label(keys: frozenset) -> str:
    """Devuelve una etiqueta legible para identificar el esquema."""
    if keys == _SCHEMA_CX:
        return "cx"
    if keys == _SCHEMA_PAYPAL:
        return "paypal"
    return "base"
