"""Layer 4 — fichas de recurrencia por fingerprint y canal.

Responsabilidades:
- Calcular la ficha histórica de cada fingerprint DENTRO DE SU CANAL.
- sre y cx nunca se mezclan: sus períodos son disjuntos (mayo-junio 2025 vs
  marzo 2026) y sus patrones de carga son distintos.

Ficha por (channel, fingerprint):
  dias_visto     : int   — días calendario distintos con al menos un incidente.
  horas_tipicas  : list[int] — horas (0-23) de inicio de incidentes ordenadas.
  sello_finde    : bool  — algún incidente inició en sábado (5) o domingo (6).
  rafaga_tipica  : float — mediana de n_alertas por incidente del fingerprint.

Diseño deliberado:
  - Se usan las horas de INICIO del incidente (no de las alertas individuales),
    para que la ficha sea estable ante ráfagas de distinto tamaño.
  - NO se usan z-scores (n=458, decisión documentada en docs/decisiones.md).
  - La ficha se calcula del propio histórico; no hay train/test split.
"""
from __future__ import annotations

import statistics
from collections import Counter

import pandas as pd


def build_profiles(inc_df: pd.DataFrame) -> pd.DataFrame:
    """
    Construye las fichas de recurrencia a partir del DataFrame de incidentes.

    Parámetros
    ----------
    inc_df : DataFrame producido por dedupe.py (una fila por incidente).

    Retorna
    -------
    pd.DataFrame con columnas:
        channel, fingerprint, dias_visto, horas_tipicas, sello_finde, rafaga_tipica

    Indexado de forma que se puede hacer un join con inc_df por
    (channel, fingerprint).
    """
    rows: list[dict] = []

    for (channel, fingerprint), group in inc_df.groupby(
        ["channel", "fingerprint"], sort=False
    ):
        inicio_series = group["inicio"]

        # Días calendario distintos
        dias = {dt.date() for dt in inicio_series}
        dias_visto = len(dias)

        # Horas de inicio
        horas = sorted({dt.hour for dt in inicio_series})

        # ¿Algún incidente inició en fin de semana? (weekday: Mon=0 … Sun=6)
        sello_finde = any(dt.weekday() >= 5 for dt in inicio_series)

        # Mediana de n_alertas (representatividad de ráfaga típica)
        n_alertas_list = group["n_alertas"].tolist()
        rafaga_tipica = (
            statistics.median(n_alertas_list) if n_alertas_list else 1.0
        )

        rows.append({
            "channel": channel,
            "fingerprint": fingerprint,
            "dias_visto": dias_visto,
            "horas_tipicas": horas,
            "sello_finde": sello_finde,
            "rafaga_tipica": float(rafaga_tipica),
        })

    profiles_df = pd.DataFrame(rows)
    return profiles_df


def get_profile(
    profiles_df: pd.DataFrame, channel: str, fingerprint: str
) -> dict | None:
    """
    Devuelve el dict de ficha para un (channel, fingerprint) específico,
    o None si no existe en el histórico.
    """
    mask = (profiles_df["channel"] == channel) & (
        profiles_df["fingerprint"] == fingerprint
    )
    subset = profiles_df[mask]
    if subset.empty:
        return None
    row = subset.iloc[0]
    return {
        "dias_visto": int(row["dias_visto"]),
        "horas_tipicas": list(row["horas_tipicas"]),
        "sello_finde": bool(row["sello_finde"]),
        "rafaga_tipica": float(row["rafaga_tipica"]),
    }
