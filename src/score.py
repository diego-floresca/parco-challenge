"""Layer 5 — scoring de incidentes (0-100) con 5 componentes.

Fórmula:
    score = round(100 * min(1.0, s_bruto + boosts))
    s_bruto = w_crit*s_criticidad + w_ficha*s_ficha + w_raf*s_rafaga
              + w_int*s_intensidad + w_nov*s_novedad

Componentes (todos en [0, 1]):
    s_criticidad  — importancia del servicio (config criticidad_servicios por grupo)
    s_ficha       — desviación de la recurrencia histórica del fingerprint:
                    0.9 → sin historial suficiente (días < recurrente_min_dias)
                    0.6 → recurrente pero fuera de horario típico
                    0.1 → en horario típico pero ráfaga mayor a la habitual
                    0.0 → completamente dentro del patrón habitual (recurrente + hora
                          típica + tamaño <= rafaga_tipica)
    s_rafaga      — log2(n_disparos+1) / 5, tapado en 1.0
    s_intensidad  — fuerza de la señal de origen (ver config score.intensidad):
                    null=0.3, high=0.5, critical_estatica=0.75, critical_anomalia=1.0
                    La distinción estatica/anomalia pertenece AQUÍ (fuerza de señal),
                    no en los boosts (para evitar double-counting).
    s_novedad     — fingerprint nunca/poco visto

Boosts (se suman al s_bruto, resultado tapado en 1.0):
    +0.05 si direccion == 'bajo'  (degradación silenciosa = semánticamente más grave)
    (el boost anomalia fue eliminado: ya está capturado en s_intensidad=critical_anomalia)

Bandas: P1 >= 70, P2 >= 40, P3 < 40.
Todos los parámetros numéricos viven en config.yaml.
"""
from __future__ import annotations

import math

import pandas as pd

from src.profiles import get_profile


# ---------------------------------------------------------------------------
# Helpers de clave interna (igual que en profiles y dedupe)
# ---------------------------------------------------------------------------

def _fp_key(service: str, service_original: str, condition: str) -> str:
    """Clave interna de fingerprint — matches profiles._fp_key."""
    svc = service_original if service == "infra" else service
    return f"{svc}::{condition}"


# ---------------------------------------------------------------------------
# Cálculo de componentes
# ---------------------------------------------------------------------------

def _s_criticidad(grupo_criticidad: str, config: dict) -> float:
    grupos = config["criticidad_servicios"]["grupos"]
    if grupo_criticidad in grupos:
        return float(grupos[grupo_criticidad]["valor"])
    return float(config["criticidad_servicios"]["default"])


def _s_ficha(
    profile: dict | None,
    inicio_hour: int,
    n_alertas: int,
    config: dict,
) -> float:
    """Desviación del incidente respecto a su patrón histórico.

    0.9 — sin historial suficiente (dias_visto < recurrente_min_dias).
    0.6 — recurrente PERO fuera de horario típico: algo cambió.
    0.1 — en horario típico PERO ráfaga mayor a la habitual: señal más intensa.
    0.0 — completamente dentro del patrón (recurrente + hora típica + tamaño ≤ rafaga_tipica).
    """
    rec_min = config["pipeline"]["recurrente_min_dias"]
    if profile is None or profile["dias_visto"] < rec_min:
        return 0.9
    if inicio_hour not in profile["horas_tipicas"]:
        return 0.6
    # hora típica: distinguir por tamaño de ráfaga
    if n_alertas <= profile["rafaga_tipica"]:
        return 0.0  # completamente habitual
    return 0.1  # mayor que lo habitual en este horario


def _s_rafaga(n_disparos: int, config: dict) -> float:
    """Intensidad de la ráfaga: log2(n_disparos+1) / log2(sat+1), tapado en 1.0.

    El punto de saturación (sat) viene de config.yaml (score.rafaga.saturacion_disparos).
    Con sat=31: log2(32)=5, idéntico al divisor fijo anterior.
    """
    sat = config["score"]["rafaga"]["saturacion_disparos"]
    divisor = math.log2(sat + 1)
    return min(1.0, math.log2(n_disparos + 1) / divisor)


def _s_intensidad(
    priority_max: str | None, tipo_regla: str | None, config: dict
) -> float:
    """Fuerza de la señal de origen.

    Los valores concretos viven en config.yaml (score.intensidad) para que Ops
    pueda ajustarlos sin tocar código. La distinción estatica/anomalia vive AQUÍ
    (no en los boosts) para evitar double-counting.
    """
    int_cfg = config["score"]["intensidad"]
    if priority_max is None:
        return float(int_cfg.get("null", 0.3))
    if priority_max == "high":
        return float(int_cfg["high"])
    # priority_max == "critical"
    if tipo_regla == "anomalia":
        return float(int_cfg.get("critical_anomalia", 1.0))
    return float(int_cfg.get("critical_estatica", 0.75))


def _s_novedad(profile: dict | None, config: dict) -> float:
    """Novedad del fingerprint: más raro = más urgente."""
    nov = config["score"]["novedad"]
    rec_min = config["pipeline"]["recurrente_min_dias"]
    if profile is None or profile["dias_visto"] <= 1:
        return nov["sin_historial"]
    if profile["dias_visto"] < rec_min:
        return nov["poco_visto"]
    return nov["conocido"]


def _boosts(direccion: str | None, config: dict) -> float:
    """Solo el boost de dirección-bajo queda; anomalia ya está en s_intensidad."""
    if direccion == "bajo":
        return float(config["score"]["boosts"]["direccion_bajo"])
    return 0.0


def _banda(score_val: int, config: dict) -> tuple[str, str]:
    bandas = config["score"]["bandas"]
    for name in ("P1", "P2", "P3"):
        if score_val >= bandas[name]["min"]:
            return name, bandas[name]["etiqueta"]
    return "P3", bandas["P3"]["etiqueta"]


# ---------------------------------------------------------------------------
# Plantillas de explicación (OUTPUTS.md §1, orden de prioridad)
# ---------------------------------------------------------------------------

def _explicacion(
    service: str,
    condition: str,
    channel: str,
    tipo_regla: str | None,
    direccion: str | None,
    es_recurrente: bool,
    horas_tipicas: list[int],
    inicio_hour: int,
    dias_visto: int,
    n_disparos: int,
    duracion_min: float,
    profile: dict | None,
) -> str:
    # 1. Primera vez o solo visto 1 día
    if profile is None or dias_visto <= 1:
        return f"Primera vez que se observa este comportamiento en {service}"
    # 2. Canal inusual: Payments rejected en sre (el KPI vive en cx)
    if "payment" in condition.lower() and channel == "sre":
        return (
            "Rechazos de pago en el canal de infraestructura, "
            "donde casi nunca se reportan"
        )
    # 3. Anomalía certificada por New Relic
    if tipo_regla == "anomalia":
        return f"Detectado por la regla de anomalías de New Relic sobre {service}"
    # 4. Degradación silenciosa (throughput cayendo)
    if direccion == "bajo":
        return (
            f"El tráfico de {service} CAYÓ por debajo de su mínimo: "
            "degradación silenciosa"
        )
    # 5. Patrón habitual en horario típico
    if es_recurrente and inicio_hour in horas_tipicas:
        return (
            f"Patrón habitual de {service}: visto {dias_visto} días, "
            f"típicamente a las {inicio_hour}h"
        )
    # 6. Default
    dur = int(round(duracion_min))
    return f"{condition} en {service}, {n_disparos} disparos en {dur} min"


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def score(
    df_inc: pd.DataFrame,
    profiles_df: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    """
    Añade columnas de scoring al DataFrame de incidentes.

    Parámetros
    ----------
    df_inc       : DataFrame de dedupe.py (una fila por incidente).
    profiles_df  : DataFrame de profiles.py (fichas de recurrencia).
    config       : dict de config.yaml.

    Retorna
    -------
    pd.DataFrame con todas las columnas de df_inc más:
        vista, s_criticidad, s_ficha, s_rafaga, s_intensidad, s_novedad,
        score, banda, banda_etiqueta, explicacion, es_recurrente, dias_visto,
        atendido, etiqueta
    Ordenado por score descendente.
    """
    pesos = config["score"]["pesos"]
    rec_min = config["pipeline"]["recurrente_min_dias"]

    scored_rows: list[dict] = []

    for _, row in df_inc.iterrows():
        fp_key = _fp_key(row["service"], row["service_original"], row["condition"])
        profile = get_profile(profiles_df, row["channel"], fp_key)

        inicio_hour = row["inicio"].hour

        sc = _s_criticidad(row["grupo_criticidad"], config)
        sf = _s_ficha(profile, inicio_hour, int(row["n_alertas"]), config)
        sr = _s_rafaga(int(row["n_disparos"]), config)
        si = _s_intensidad(row["priority_max"], row["tipo_regla"], config)
        sn = _s_novedad(profile, config)

        raw = (
            pesos["criticidad"] * sc
            + pesos["fuera_de_ficha"] * sf
            + pesos["rafaga"] * sr
            + pesos["intensidad"] * si
            + pesos["novedad"] * sn
        )
        boost = _boosts(row["direccion"], config)
        raw_boosted = min(1.0, raw + boost)
        score_val = round(100 * raw_boosted)

        banda_key, banda_etq = _banda(score_val, config)

        dias_visto = profile["dias_visto"] if profile else 0
        es_recurrente = dias_visto >= rec_min
        horas_tipicas: list[int] = profile["horas_tipicas"] if profile else []
        vista = "triage" if row["channel"] == "sre" else "composicion"

        expl = _explicacion(
            service=row["service"],
            condition=row["condition"],
            channel=row["channel"],
            tipo_regla=row["tipo_regla"],
            direccion=row["direccion"],
            es_recurrente=es_recurrente,
            horas_tipicas=horas_tipicas,
            inicio_hour=inicio_hour,
            dias_visto=dias_visto,
            n_disparos=int(row["n_disparos"]),
            duracion_min=float(row["duracion_min"]),
            profile=profile,
        )

        scored_rows.append({
            **row.to_dict(),
            "vista": vista,
            "s_criticidad": round(sc, 4),
            "s_ficha": round(sf, 4),
            "s_rafaga": round(sr, 4),
            "s_intensidad": round(si, 4),
            "s_novedad": round(sn, 4),
            "score": score_val,
            "banda": banda_key,
            "banda_etiqueta": banda_etq,
            "explicacion": expl,
            "es_recurrente": es_recurrente,
            "dias_visto": dias_visto,
            "atendido": "",
            "etiqueta": "",
        })

    df_scored = pd.DataFrame(scored_rows)
    df_scored = df_scored.sort_values(
        ["score", "incident_id"], ascending=[False, True]
    ).reset_index(drop=True)
    return df_scored
