"""Layer 2 — adaptadores por source/canal al esquema canónico.

Responsabilidades:
- Aplicar la regla de reloj por canal (sre -> ts epoch, cx -> timestamp ISO).
- Normalizar service: typos (Princes->Princess) e infra (i-*/new-parco-instance-*).
- Derivar grupo_criticidad de config.yaml.
- Parsear threshold -> (tipo_regla, direccion, ventana_eval).
- Extraer procesador de error_message por regex (solo cx).

No hace deduplicación ni scoring — eso es responsabilidad de capas posteriores.
Produce un DataFrame con una fila por alerta cruda, ordenado por dt ascendente.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Any

import pandas as pd


_TZ_MINUS6 = timezone(timedelta(hours=-6))


# ---------------------------------------------------------------------------
# Parseo de tiempo
# ---------------------------------------------------------------------------

def _parse_dt_sre(ts_raw: str) -> datetime:
    """sre: epoch string (con o sin decimales) -> datetime tz=-06:00."""
    epoch = float(ts_raw)
    return datetime.fromtimestamp(epoch, tz=_TZ_MINUS6)


def _parse_dt_cx(timestamp_raw: str) -> datetime:
    """cx: ISO 8601 string -> datetime normalizado a tz=-06:00."""
    dt = datetime.fromisoformat(timestamp_raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TZ_MINUS6)
    return dt.astimezone(_TZ_MINUS6)


# ---------------------------------------------------------------------------
# Normalización de service
# ---------------------------------------------------------------------------

def normalize_service(service: str, config: dict) -> tuple[str, str]:
    """
    Devuelve (service_normalizado, service_original).

    Orden de aplicación:
    1. Corrección de typos (Princes -> Princess).
    2. Agrupación infra (i-*/new-parco-instance-*) -> 'infra'.

    El nombre original se conserva siempre en service_original.
    """
    original = service
    typos: dict[str, str] = config.get("normalizacion", {}).get("typos_service", {})
    service = typos.get(service, service)

    patterns: list[str] = config.get("normalizacion", {}).get("reglas_grupo_infra", [])
    for pattern in patterns:
        if re.fullmatch(pattern, service):
            return "infra", original

    return service, original


# ---------------------------------------------------------------------------
# Grupo de criticidad
# ---------------------------------------------------------------------------

def get_grupo_criticidad(service_normalizado: str, config: dict) -> str:
    """Devuelve el nombre del grupo de criticidad del servicio normalizado."""
    grupos: dict = config.get("criticidad_servicios", {}).get("grupos", {})
    for grupo, info in grupos.items():
        if service_normalizado in info.get("servicios", []):
            return grupo
    # infra se asigna por regla (lista vacía en config), ya fue normalizado arriba
    if service_normalizado == "infra":
        return "infra"
    return "default"


# ---------------------------------------------------------------------------
# Parseo de threshold
# ---------------------------------------------------------------------------

def parse_threshold(threshold: Any) -> tuple[str | None, str | None, str | None]:
    """
    Parsea el string de threshold a tres derivados.

    Devuelve (tipo_regla, direccion, ventana_eval).
    Si threshold es null/vacío devuelve (None, None, None).

    tipo_regla: 'anomalia' si contiene 'baseline', 'estatica' en otro caso.
    direccion:  'bajo' si el operador es '<'; 'sobre' si '>'; None si ausente.
    ventana_eval: el sufijo temporal extraído, e.g. '5min', '10min', '3min'.
    """
    if not threshold:
        return None, None, None

    s = str(threshold)
    tipo = "anomalia" if "baseline" in s else "estatica"

    if "<" in s:
        direccion: str | None = "bajo"
    elif ">" in s:
        direccion = "sobre"
    else:
        direccion = None

    m = re.search(r"/(\d+\w+)", s)
    ventana: str | None = m.group(1) if m else None

    return tipo, direccion, ventana


# ---------------------------------------------------------------------------
# Extracción de procesador
# ---------------------------------------------------------------------------

def extract_procesador(error_message: str | None, procesadores: list[str]) -> str:
    """
    Busca el nombre de procesador de pago en error_message.
    Devuelve el primer match (insensible a mayúsculas) o cadena vacía.
    """
    if not error_message:
        return ""
    for proc in procesadores:
        if re.search(re.escape(proc), error_message, re.IGNORECASE):
            return proc
    return ""


# ---------------------------------------------------------------------------
# Función principal de la capa
# ---------------------------------------------------------------------------

def normalize(records: list[dict], config: dict) -> pd.DataFrame:
    """
    Transforma la lista de dicts crudos al esquema canónico.

    Returns
    -------
    pd.DataFrame ordenado por dt ascendente; una fila por alerta cruda.
    """
    procesadores: list[str] = (
        config.get("normalizacion", {}).get("procesadores_conocidos", [])
    )
    rows: list[dict] = []

    for rec in records:
        channel: str = rec.get("channel", "")

        # Reloj confiable por canal (EDA §3, regla operativa)
        if channel == "sre":
            dt = _parse_dt_sre(rec["ts"])
        else:
            dt = _parse_dt_cx(rec["timestamp"])

        # Normalización de service
        raw_service: str = rec.get("service", "")
        service, service_original = normalize_service(raw_service, config)

        # Grupo de criticidad
        grupo = get_grupo_criticidad(service, config)

        # Threshold (ausente en PayPal Status)
        threshold_raw = rec.get("threshold")
        tipo_regla, direccion, ventana_eval = parse_threshold(threshold_raw)

        # Campos exclusivos de cx (EDA §5: son esquema por fuente, no missingness)
        if channel == "monitoring-ops-cx":
            error_type: str = rec.get("error_type") or ""
            error_message: str = rec.get("error_message") or ""
            procesador = extract_procesador(error_message, procesadores)
        else:
            error_type = ""
            error_message = ""
            procesador = ""

        rows.append({
            "dt": dt,
            "channel": channel,
            "source": rec.get("source", ""),
            "service": service,
            "service_original": service_original,
            "grupo_criticidad": grupo,
            "condition": rec.get("condition", ""),
            "policy": rec.get("policy"),
            "priority": rec.get("priority"),
            # incidents_raw conserva el null de New Relic para que dedupe use null->1
            "incidents_raw": rec.get("incidents"),
            "threshold": threshold_raw,
            "tipo_regla": tipo_regla,
            "direccion": direccion,
            "ventana_eval": ventana_eval,
            "error_type": error_type,
            "error_message": error_message,
            "procesador": procesador,
        })

    df = pd.DataFrame(rows)
    df = df.sort_values("dt", kind="stable").reset_index(drop=True)
    return df
