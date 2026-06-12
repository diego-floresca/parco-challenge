"""Layer 6 — vistas sobre los incidentes y alertas.

Tres perspectivas sobre una única fuente de verdad (incidents.csv no cambia):

vista_triage(df_scored)
    Canal sre. Orden: score descendente.
    Pregunta: ¿qué atiendo primero?

vista_composicion(df_norm_cx)
    Canal monitoring-ops-cx. Agrega a nivel de ALERTA (no de incidente)
    porque la composición de error_type es el KPI de Payments.
    Pregunta: ¿de qué se componen mis errores de pago?

vista_patrones(df_scored, config)
    Todos los canales. Agrega por (channel, fingerprint): n_incidentes,
    score_medio, n_disparos_total, primera/última aparición, es_cronico.
    Crónico activo = es_recurrente=True AND n_incidentes >= cronico_min_incidentes.
    Pregunta: ¿qué patrones debo gestionar como caso, no como alerta individual?
"""
from __future__ import annotations

import pandas as pd


def vista_triage(df_scored: pd.DataFrame) -> pd.DataFrame:
    """Incidentes del canal sre ordenados por score descendente.

    Parámetros
    ----------
    df_scored : DataFrame producido por score.py.

    Retorna
    -------
    pd.DataFrame con los incidentes sre, orden score desc.
    (El DataFrame ya viene ordenado de score.py, este filtro es defensivo.)
    """
    sre = df_scored[df_scored["channel"] == "sre"].copy()
    return sre.sort_values(
        ["score", "incident_id"], ascending=[False, True]
    ).reset_index(drop=True)


def vista_composicion(df_norm_cx: pd.DataFrame) -> dict:
    """Agrega alertas cx en 3 dimensiones para el KPI de Payments.

    Parámetros
    ----------
    df_norm_cx : subset del DataFrame de normalize.py con
                 channel == 'monitoring-ops-cx'.
                 Se usa el nivel de ALERTA (no de incidente) porque los
                 28/25/23/12 de EDA §7 son conteos de alertas crudas.

    Retorna
    -------
    dict con:
        por_error_type : dict[str, int]   — conteo de alertas por error_type
        por_procesador : dict[str, int]   — conteo excluyendo procesador vacío
        por_dia        : dict[str, int]   — conteo por fecha ISO yyyy-mm-dd
        kpi_pct        : dict[str, float] — % por error_type sobre total cx
        total          : int              — alertas cx totales
    """
    cx = df_norm_cx[df_norm_cx["channel"] == "monitoring-ops-cx"].copy()
    total = len(cx)

    # Por error_type (conteo de alertas)
    et_counts: dict[str, int] = (
        cx["error_type"]
        .value_counts()
        .to_dict()
    )

    # Por procesador (excluir '' — sólo cx con procesador identificado)
    proc_counts: dict[str, int] = {}
    if "procesador" in cx.columns:
        proc_counts = (
            cx[cx["procesador"] != ""]["procesador"]
            .value_counts()
            .to_dict()
        )

    # Por día (fecha de dt, en string yyyy-mm-dd)
    fecha_series = cx["dt"].dt.date.astype(str)
    dia_counts: dict[str, int] = (
        fecha_series.groupby(fecha_series)
        .count()
        .sort_index()
        .to_dict()
    )

    # KPI %: porcentaje de cada error_type sobre el total cx
    kpi_pct: dict[str, float] = {
        et: round(100.0 * cnt / total, 1) if total > 0 else 0.0
        for et, cnt in et_counts.items()
    }

    return {
        "por_error_type": et_counts,
        "por_procesador": proc_counts,
        "por_dia": dia_counts,
        "kpi_pct": kpi_pct,
        "total": total,
    }


def vista_patrones(df_scored: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Agrega incidentes por (channel, fingerprint) para revelar patrones crónicos.

    Un fingerprint es **crónico activo** cuando cumple ambas condiciones:
      - es_recurrente = True  (dias_visto >= recurrente_min_dias en su perfil)
      - n_incidentes >= cronico_min_incidentes  (suficientes episodios en el período)

    La distinción entre «el 500 de siempre de Orchestrator» y «algo que apareció hoy»
    es de gestión, no de score: ambos merecen acción, pero acciones distintas.
    Los crónicos se gestionan como caso abierto; los noveles como alerta individual.

    Parámetros
    ----------
    df_scored : DataFrame producido por score.py (una fila por incidente).
    config    : dict de config.yaml.

    Retorna
    -------
    pd.DataFrame con columnas:
        channel          : canal
        fingerprint      : {service}::{condition}
        service          : servicio normalizado
        n_incidentes     : episodios en el período
        score_medio      : media de score (float redondeado a 1 decimal)
        score_max        : score más alto del período
        n_disparos_total : suma de n_disparos de todos los episodios
        es_recurrente    : True si el fingerprint tiene historial >= recurrente_min_dias
        es_cronico       : True si es_recurrente AND n_incidentes >= cronico_min_incidentes
        primera          : timestamp del inicio del primer incidente
        ultima           : timestamp del fin del último incidente
    Orden: es_cronico desc, n_incidentes desc.
    """
    cronico_min = config["pipeline"]["cronico_min_incidentes"]

    rows: list[dict] = []

    for (channel, fingerprint), group in df_scored.groupby(
        ["channel", "fingerprint"], sort=False
    ):
        n_incidentes = len(group)
        score_medio = round(float(group["score"].mean()), 1)
        score_max = int(group["score"].max())
        n_disparos_total = int(group["n_disparos"].sum())
        # es_recurrente: True si algún incidente del fingerprint está marcado recurrente
        # (todos deberían coincidir, pero any() es robusto ante posibles transiciones)
        es_recurrente = bool(group["es_recurrente"].any())
        es_cronico = es_recurrente and n_incidentes >= cronico_min
        primera = group["inicio"].min()
        ultima = group["fin"].max()
        service = group["service"].iloc[0]

        rows.append({
            "channel": channel,
            "fingerprint": fingerprint,
            "service": service,
            "n_incidentes": n_incidentes,
            "score_medio": score_medio,
            "score_max": score_max,
            "n_disparos_total": n_disparos_total,
            "es_recurrente": es_recurrente,
            "es_cronico": es_cronico,
            "primera": primera,
            "ultima": ultima,
        })

    df_pat = pd.DataFrame(rows)
    if df_pat.empty:
        return df_pat

    return df_pat.sort_values(
        ["es_cronico", "n_incidentes"], ascending=[False, False]
    ).reset_index(drop=True)
