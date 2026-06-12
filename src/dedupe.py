"""Layer 3 — deduplicación de alertas en incidentes.

Responsabilidades:
- Agrupar alertas del mismo fingerprint con gap ≤ ventana_rafaga_minutos
  en un único incidente.
- Calcular métricas del incidente: n_alertas, n_disparos, duracion_min,
  tasa_por_min, priority_max.
- Asignar incident_id determinista INC-NNNN (orden cronológico de inicio).

Nota de diseño (decisión documentada):
  La clave interna de agrupación usa service_original para que instancias de
  infraestructura distintas (i-058..., i-0d2...) generen incidentes separados.
  Esto produce los números de aceptación del EDA: 277 incidentes / 46 ráfagas /
  227 alertas en ráfagas. La columna fingerprint almacenada usa el nombre
  normalizado ({service}::{condition}) para display, per OUTPUTS.md.
"""
from __future__ import annotations

import math
from datetime import timedelta

import pandas as pd

# Orden de prioridad para calcular priority_max
_PRIORITY_RANK: dict[str | None, int] = {"critical": 2, "high": 1, None: 0}


def _priority_max(priorities: list[str | None]) -> str | None:
    """Devuelve la prioridad más alta del incidente."""
    ranked = [p if p in _PRIORITY_RANK else None for p in priorities]
    best = max(ranked, key=lambda p: _PRIORITY_RANK.get(p, 0))
    return best


def _n_disparos(incidents_raw_series: pd.Series) -> int:
    """Suma incidents_raw; NaN/None cuentan como 1."""
    return int(incidents_raw_series.fillna(1).sum())


def _dominant(values: list) -> str:
    """Valor más frecuente de la lista; '' si está vacía o todos son ''."""
    non_empty = [v for v in values if v and v != ""]
    if not non_empty:
        return ""
    from collections import Counter
    return Counter(non_empty).most_common(1)[0][0]


def dedupe(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    Transforma el DataFrame de alertas (normalize.py) en DataFrame de incidentes.

    Parámetros
    ----------
    df : DataFrame normalizado, una fila por alerta, ordenado por dt.
    config : dict de config.yaml.

    Retorna
    -------
    pd.DataFrame con una fila por incidente, ordenado por score descendente
    (score se rellena por score.py; aquí se ordena por inicio para que los
    INC-NNNN sean cronológicos).
    """
    ventana = timedelta(
        minutes=config["pipeline"]["ventana_rafaga_minutos"]
    )

    # Ordenar por (canal, service_original, condition, dt) — clave de agrupación
    df_s = df.sort_values(
        ["channel", "service_original", "condition", "dt"], kind="stable"
    ).reset_index(drop=True)

    # Barrer linealmente y agrupar
    raw_incidents: list[dict] = []
    current: dict | None = None

    for _, row in df_s.iterrows():
        group_key = (row["channel"], row["service_original"], row["condition"])
        gap_ok = (
            current is not None
            and group_key == current["_key"]
            and (row["dt"] - current["_last_dt"]) <= ventana
        )

        if not gap_ok:
            if current is not None:
                raw_incidents.append(current)
            current = _new_incident(row, group_key)
        else:
            _append_alert(current, row)

    if current is not None:
        raw_incidents.append(current)

    # Convertir a filas del DataFrame de incidentes
    rows = [_finalize(inc) for inc in raw_incidents]
    inc_df = pd.DataFrame(rows)

    # Asignar INC-NNNN por orden cronológico de inicio
    inc_df = inc_df.sort_values(
        ["inicio", "channel", "service", "condition"], kind="stable"
    ).reset_index(drop=True)
    inc_df.insert(
        0,
        "incident_id",
        [f"INC-{i + 1:04d}" for i in range(len(inc_df))],
    )

    return inc_df


# ---------------------------------------------------------------------------
# Helpers de construcción de incidente
# ---------------------------------------------------------------------------

def _new_incident(row: pd.Series, group_key: tuple) -> dict:
    return {
        "_key": group_key,
        "_last_dt": row["dt"],
        # Metadatos escalares (estables en el fingerprint)
        "channel": row["channel"],
        "source": row["source"],
        "service": row["service"],
        "service_original": row["service_original"],
        "grupo_criticidad": row["grupo_criticidad"],
        "condition": row["condition"],
        "policy": row["policy"],
        "tipo_regla": row["tipo_regla"],
        "direccion": row["direccion"],
        "ventana_eval": row["ventana_eval"],
        # Acumuladores
        "_inicio": row["dt"],
        "_fin": row["dt"],
        "_priorities": [row["priority"]],
        "_incidents_raw": [row["incidents_raw"]],
        "_error_types": [row["error_type"]],
        "_procesadores": [row["procesador"]],
        "_n_alertas": 1,
    }


def _append_alert(current: dict, row: pd.Series) -> None:
    current["_last_dt"] = row["dt"]
    current["_fin"] = row["dt"]
    current["_priorities"].append(row["priority"])
    current["_incidents_raw"].append(row["incidents_raw"])
    current["_error_types"].append(row["error_type"])
    current["_procesadores"].append(row["procesador"])
    current["_n_alertas"] += 1


def _finalize(inc: dict) -> dict:
    """Calcula las métricas del incidente y devuelve el dict de fila."""
    inicio = inc["_inicio"]
    fin = inc["_fin"]
    n_alertas = inc["_n_alertas"]
    n_disparos = _n_disparos(pd.Series(inc["_incidents_raw"]))
    duracion_min = (fin - inicio).total_seconds() / 60.0
    tasa_por_min = n_disparos / max(duracion_min, 1.0)

    return {
        # Escalares del fingerprint
        "channel": inc["channel"],
        "source": inc["source"],
        "fingerprint": f"{inc['service']}::{inc['condition']}",
        "service": inc["service"],
        "service_original": inc["service_original"],
        "grupo_criticidad": inc["grupo_criticidad"],
        "condition": inc["condition"],
        "policy": inc["policy"],
        "tipo_regla": inc["tipo_regla"],
        "direccion": inc["direccion"],
        "ventana_eval": inc["ventana_eval"],
        # Temporales
        "inicio": inicio,
        "fin": fin,
        "duracion_min": round(duracion_min, 2),
        # Métricas
        "n_alertas": n_alertas,
        "n_disparos": n_disparos,
        "tasa_por_min": round(tasa_por_min, 4),
        "priority_max": _priority_max(inc["_priorities"]),
        # CX-only
        "error_type": _dominant(inc["_error_types"]),
        "procesador": _dominant(inc["_procesadores"]),
    }
