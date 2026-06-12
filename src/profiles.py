"""Layer 4 — fichas de recurrencia por fingerprint y canal.

Responsabilidades:
- Calcular la ficha histórica de cada fingerprint DENTRO DE SU CANAL.
- sre y cx nunca se mezclan: sus períodos son disjuntos (mayo-junio 2025 vs
  marzo 2026) y sus patrones de carga son distintos.

Clave interna de agrupación — igual que dedupe._group_service:
  Para servicios infra (service=='infra') se usa service_original para que
  cada instancia EC2 (i-058..., i-0d2...) tenga su propia ficha independiente.
  Para el resto se usa service (nombre normalizado, con typo corregido).
  Resultado: i-0d26dd tiene dias_visto=2 (< recurrente_min_dias=3) -> s_ficha=0.9
  y el incidente aterriza en P2 como esperado (EDA §9).

Ficha por (channel, fingerprint_key):
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

import pandas as pd


def _fp_key(service: str, service_original: str, condition: str) -> str:
    """Internal grouping key — mirrors dedupe._group_service logic.

    Infra instances (service == 'infra') use their original name so each
    EC2 instance gets a separate profile. All other services use the
    normalised name (typo-corrected, e.g. Princes -> Princess).
    """
    svc = service_original if service == "infra" else service
    return f"{svc}::{condition}"


def build_profiles(inc_df: pd.DataFrame) -> pd.DataFrame:
    """
    Construye las fichas de recurrencia a partir del DataFrame de incidentes.

    Parámetros
    ----------
    inc_df : DataFrame producido por dedupe.py (una fila por incidente).

    Retorna
    -------
    pd.DataFrame con columnas:
        channel, fingerprint_key, fingerprint, dias_visto, horas_tipicas,
        sello_finde, rafaga_tipica

    fingerprint_key  — clave interna de agrupación (por instancia para infra).
    fingerprint      — clave de display normalizada ({service}::{condition}).
    """
    inc = inc_df.copy()
    inc["_fp_key"] = inc.apply(
        lambda r: _fp_key(r["service"], r["service_original"], r["condition"]),
        axis=1,
    )

    rows: list[dict] = []

    for (channel, fp_key), group in inc.groupby(
        ["channel", "_fp_key"], sort=False
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

        # fingerprint normalizado para display (de la primera fila del grupo)
        fingerprint = group["fingerprint"].iloc[0]

        rows.append({
            "channel": channel,
            "fingerprint_key": fp_key,
            "fingerprint": fingerprint,
            "dias_visto": dias_visto,
            "horas_tipicas": horas,
            "sello_finde": sello_finde,
            "rafaga_tipica": float(rafaga_tipica),
        })

    profiles_df = pd.DataFrame(rows)
    return profiles_df


def get_profile(
    profiles_df: pd.DataFrame, channel: str, fingerprint_key: str
) -> dict | None:
    """
    Devuelve el dict de ficha para un (channel, fingerprint_key) específico,
    o None si no existe en el histórico.

    Parámetros
    ----------
    fingerprint_key : clave interna — usa service_original para infra,
                      service normalizado para el resto. Idéntica a la que
                      computa score._fp_key().
    """
    mask = (profiles_df["channel"] == channel) & (
        profiles_df["fingerprint_key"] == fingerprint_key
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
