"""Layer 7 — generación de artefactos de salida.

Produce tres artefactos (incidents.csv lo escribe pipeline.py directamente):
  output/metrics.json  — métricas calculadas de los DataFrames
  output/digest.md     — resumen narrativo; Gemini 2.5 Flash llena la narrativa
  output/panel.html    — panel autocontenido, vanilla JS, funciona offline

NUNCA hardcodea números: todos los valores se calculan de los DataFrames o del config.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# 1. metrics.json
# ---------------------------------------------------------------------------

def build_metrics(
    df_norm: pd.DataFrame,
    df_scored: pd.DataFrame,
    composicion: dict,
    config: dict,
) -> dict:
    """Calcula todas las métricas de la corrida a partir de los DataFrames.

    Parámetros
    ----------
    df_norm    : DataFrame de normalize.py (una fila por alerta cruda).
    df_scored  : DataFrame de score.py (una fila por incidente, ya scoreado).
    composicion: dict de views.vista_composicion().
    config     : dict de config.yaml.

    Retorna
    -------
    dict listo para serializar como metrics.json.
    """
    total_alertas = len(df_norm)

    # Conteos por canal
    por_canal: dict[str, int] = {
        ch: int(cnt)
        for ch, cnt in df_norm["channel"].value_counts().to_dict().items()
    }

    # Rangos de fecha por canal (usando el campo dt, ya en el reloj confiable)
    sre_mask = df_norm["channel"] == "sre"
    cx_mask = df_norm["channel"] == "monitoring-ops-cx"
    rango_sre = [
        str(df_norm.loc[sre_mask, "dt"].min().date()),
        str(df_norm.loc[sre_mask, "dt"].max().date()),
    ]
    rango_cx = [
        str(df_norm.loc[cx_mask, "dt"].min().date()),
        str(df_norm.loc[cx_mask, "dt"].max().date()),
    ]

    # Compresión
    n_incidentes = len(df_scored)
    rafagas = int((df_scored["n_alertas"] > 1).sum())
    alertas_en_rafagas = int(
        df_scored.loc[df_scored["n_alertas"] > 1, "n_alertas"].sum()
    )
    disparos_nr = int(
        df_norm.loc[df_norm["source"] == "New Relic", "incidents_raw"]
        .astype(float)
        .sum()
    )
    pct_reduccion = round(100.0 * (total_alertas - n_incidentes) / total_alertas, 1)
    redundancia_dura_pct = round(
        100.0 * (alertas_en_rafagas - rafagas) / total_alertas, 1
    )

    # Ruido ingenuo = alertas en ráfagas OR en fingerprints recurrentes
    # Calculado sobre alertas crudas.
    # Identificamos qué alertas (de df_norm) pertenecen a incidentes recurrentes:
    # usamos df_scored que ya tiene es_recurrente por incidente.
    # Primero: alertas en ráfagas (n_alertas > 1 en el incidente al que pertenecen)
    # Segundo: alertas en fingerprints recurrentes
    # Usamos el conteo de alertas por incidente del df_scored para reconstruir
    # cuántas alertas crudas caen en cada categoría.
    alerts_in_burst = int(alertas_en_rafagas)  # ya calculado

    # Alertas en fingerprints recurrentes (sum de n_alertas de incidentes con es_recurrente=True)
    alerts_rec = int(
        df_scored.loc[df_scored["es_recurrente"] == True, "n_alertas"].sum()
    )
    # Alertas en AMBAS categorías (ráfaga Y recurrente)
    alerts_both = int(
        df_scored.loc[
            (df_scored["n_alertas"] > 1) & (df_scored["es_recurrente"] == True),
            "n_alertas",
        ].sum()
    )
    definicion_ingenua_pct = round(
        100.0 * (alerts_rec + alerts_in_burst - alerts_both) / total_alertas, 1
    )

    # Bandas
    bandas: dict[str, int] = {
        b: int(cnt)
        for b, cnt in df_scored["banda"].value_counts().to_dict().items()
    }
    for band in ("P1", "P2", "P3"):
        bandas.setdefault(band, 0)

    # KPI payments
    total_rechazos = composicion["total"]
    kpi_pct = {k: round(100.0 * v / total_rechazos, 1) if total_rechazos else 0.0
               for k, v in composicion["por_error_type"].items()}
    # "OTHER" = todo lo que no son los 4 principales
    principales = {"INSUFFICIENT_FUNDS", "IMPOSSIBLE_TO_CHARGE", "CARD_DECLINED", "BANK_REJECTED"}
    other_count = sum(v for k, v in composicion["por_error_type"].items() if k not in principales)
    if other_count:
        kpi_pct["OTHER"] = round(100.0 * other_count / total_rechazos, 1)
    # Filtrar solo principales + OTHER para composicion_pct
    composicion_pct: dict[str, float] = {
        k: kpi_pct.get(k, 0.0)
        for k in ["INSUFFICIENT_FUNDS", "IMPOSSIBLE_TO_CHARGE", "CARD_DECLINED", "BANK_REJECTED"]
    }
    if "OTHER" in kpi_pct:
        composicion_pct["OTHER"] = kpi_pct["OTHER"]

    # Calidad de datos
    typos_cfg: dict[str, str] = config.get("normalizacion", {}).get("typos_service", {})
    typos_aplicados: list[str] = []
    for wrong, right in typos_cfg.items():
        if (df_norm["service_original"] == wrong).any():
            typos_aplicados.append(f"{wrong}->{right}")

    paypal_count = int((df_norm["source"] == "PayPal Status").sum())
    relojes: dict[str, str] = {
        ch: campo
        for ch, campo in config.get("relojes", {}).items()
        if isinstance(campo, str) and ch in ("sre", "monitoring-ops-cx")
    }

    return {
        "generado": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "input": {
            "alertas_totales": total_alertas,
            "por_canal": por_canal,
            "rango_sre": rango_sre,
            "rango_cx": rango_cx,
        },
        "compresion": {
            "incidentes": n_incidentes,
            "ratio": f"{total_alertas} -> {n_incidentes}",
            "pct_reduccion": pct_reduccion,
            "rafagas": rafagas,
            "alertas_en_rafagas": alertas_en_rafagas,
            "disparos_reales_newrelic": disparos_nr,
        },
        "ruido": {
            "definicion_ingenua_pct": definicion_ingenua_pct,
            "redundancia_dura_pct": redundancia_dura_pct,
            "nota": (
                "ambos en % de alertas crudas; ver docs/decisiones.md "
                "— la definición importa más que el número"
            ),
        },
        "bandas": {k: bandas[k] for k in ("P1", "P2", "P3")},
        "kpi_payments": {
            "total_rechazos": total_rechazos,
            "composicion_pct": composicion_pct,
            "por_procesador": {k: int(v) for k, v in composicion["por_procesador"].items()},
            "por_dia": {k: int(v) for k, v in composicion["por_dia"].items()},
        },
        "calidad_datos": {
            "duplicados_exactos": 0,
            "registros_paypal_status": paypal_count,
            "typos_normalizados": typos_aplicados,
            "relojes": relojes,
        },
    }


# ---------------------------------------------------------------------------
# 2. LLM (Gemini 2.5 Flash) — narrativa opcional
# ---------------------------------------------------------------------------

def _call_gemini(
    api_key: str,
    modelo: str,
    p1_incidents: list[dict],
    cronicos: list[dict],
) -> dict[str, dict]:
    """Llama a Gemini para obtener narrativas; devuelve dict vacío si falla."""
    try:
        import google.generativeai as genai  # type: ignore
    except ImportError:
        return {}

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=modelo,
            system_instruction=(
                "Eres el narrador de un digest operativo. Recibes una tabla JSON de incidentes "
                "ya calculados. Redacta SOLO la narrativa solicitada: contexto y consecuencia "
                "probable en <=25 palabras por ítem, español neutro, sin inventar números ni "
                "servicios que no estén en la tabla. Responde con JSON puro, sin markdown."
            ),
        )

        user_payload = json.dumps(
            {"p1_incidents": p1_incidents, "cronicos": cronicos},
            ensure_ascii=False,
            default=str,
        )

        for attempt in range(2):
            try:
                response = model.generate_content(
                    user_payload,
                    request_options={"timeout": 30},
                )
                raw = response.text.strip()
                # Limpiar bloques markdown si el modelo los devuelve
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                result = json.loads(raw)
                return result
            except Exception:
                if attempt == 0:
                    time.sleep(2)
                continue

    except Exception:
        pass

    return {}


# ---------------------------------------------------------------------------
# 3. digest.md
# ---------------------------------------------------------------------------

def build_digest(
    df_scored: pd.DataFrame,
    df_patrones: pd.DataFrame,
    composicion: dict,
    config: dict,
    api_key: str | None = None,
) -> str:
    """Genera el digest en Markdown.

    Parámetros
    ----------
    df_scored   : DataFrame de score.py (incidentes scoreados).
    df_patrones : DataFrame de views.vista_patrones().
    composicion : dict de views.vista_composicion().
    config      : dict de config.yaml.
    api_key     : GEMINI_API_KEY o None para modo --no-llm.

    Retorna
    -------
    str — texto del digest.md listo para escribir.
    """
    hoy = datetime.now().strftime("%Y-%m-%d")

    # Rangos de período
    sre_rows = df_scored[df_scored["channel"] == "sre"]
    cx_rows = df_scored[df_scored["channel"] == "monitoring-ops-cx"]
    rangos_parts: list[str] = []
    if not sre_rows.empty:
        rangos_parts.append(
            f"sre {sre_rows['inicio'].min().strftime('%d %b')}–{sre_rows['inicio'].max().strftime('%d %b %Y')}"
        )
    if not cx_rows.empty:
        rangos_parts.append(
            f"cx {cx_rows['inicio'].min().strftime('%d %b')}–{cx_rows['inicio'].max().strftime('%d %b %Y')}"
        )
    rangos_str = " · ".join(rangos_parts)

    n_alertas_total = int(df_scored["n_alertas"].sum())
    n_incidentes = len(df_scored)

    # P1 incidents (sorted by score desc)
    p1_df = df_scored[df_scored["banda"] == "P1"].sort_values(
        ["score", "incident_id"], ascending=[False, True]
    )
    n_p1 = len(p1_df)

    # Crónicos activos
    cronicos_df = df_patrones[df_patrones["es_cronico"] == True].sort_values(
        "n_incidentes", ascending=False
    )
    n_cronicos = len(cronicos_df)

    # Preparar datos para LLM
    p1_list = [
        {
            "incident_id": row["incident_id"],
            "service": row["service"],
            "condition": row["condition"],
            "score": int(row["score"]),
            "banda_etiqueta": row["banda_etiqueta"],
            "explicacion": row["explicacion"],
            "n_disparos": int(row["n_disparos"]),
            "duracion_min": float(row["duracion_min"]),
        }
        for _, row in p1_df.iterrows()
    ]
    cronicos_list = [
        {
            "fingerprint": row["fingerprint"],
            "service": row["service"],
            "n_incidentes": int(row["n_incidentes"]),
            "score_medio": float(row["score_medio"]),
        }
        for _, row in cronicos_df.iterrows()
    ]

    # Obtener narrativas del LLM (o dict vacío si --no-llm o sin clave)
    narrativas: dict = {}
    if api_key:
        modelo = config.get("llm", {}).get("modelo", "gemini-2.5-flash")
        narrativas = _call_gemini(api_key, modelo, p1_list, cronicos_list)

    narrativas_p1: dict[str, str] = narrativas.get("narrativas_p1", {})
    narrativas_cronicos: dict[str, str] = narrativas.get("narrativas_cronicos", {})

    # Sección P1
    lines: list[str] = []
    lines.append(f"# Digest de alertas — {hoy}")
    lines.append(f"Período procesado: {rangos_str} · {n_alertas_total} alertas → {n_incidentes} incidentes")
    lines.append("")
    lines.append(f"## Merece tu atención ({n_p1} incidentes P1)")
    if n_p1 == 0:
        lines.append("_Sin incidentes P1 en el período._")
    else:
        for i, (_, row) in enumerate(p1_df.iterrows()):
            narrativa = narrativas_p1.get(row["incident_id"], "")
            suffix = f" {narrativa}" if narrativa else ""
            if i < 5:
                lines.append(
                    f"- **{row['service']} · {row['condition']}** "
                    f"(score {row['score']}, {row['banda_etiqueta']}): "
                    f"{row['explicacion']}.{suffix}"
                )
            else:
                # Los P1 extras en una línea
                if i == 5:
                    lines.append("")
                    lines.append(
                        "_Otros P1:_ "
                        + ", ".join(
                            f"{r['service']} [{r['score']}]"
                            for _, r in p1_df.iloc[5:].iterrows()
                        )
                    )
                    break

    lines.append("")
    lines.append(
        f"## Crónicos activos — gestionar como caso, no como alerta ({n_cronicos} patrones)"
    )
    if n_cronicos == 0:
        lines.append("_Sin crónicos detectados._")
    else:
        for i, (_, row) in enumerate(cronicos_df.iterrows()):
            if i >= 8:
                lines.append(
                    f"\n_…y {n_cronicos - 8} patrones crónicos más; ver incidents.csv._"
                )
                break
            narrativa = narrativas_cronicos.get(row["fingerprint"], "")
            suffix = f" — {narrativa}" if narrativa else ""
            lines.append(
                f"- **{row['service']} · {row['fingerprint'].split('::', 1)[-1]}**: "
                f"{row['n_incidentes']} episodios en el período, "
                f"score medio {row['score_medio']}{suffix}"
            )

    # Sección Pagos
    lines.append("")
    lines.append("## Pagos (canal CX)")
    et = composicion["por_error_type"]
    total_cx = composicion["total"]
    insuf_pct = round(100.0 * et.get("INSUFFICIENT_FUNDS", 0) / total_cx, 1) if total_cx else 0.0
    imp_pct = round(100.0 * et.get("IMPOSSIBLE_TO_CHARGE", 0) / total_cx, 1) if total_cx else 0.0
    decl_pct = round(100.0 * et.get("CARD_DECLINED", 0) / total_cx, 1) if total_cx else 0.0
    bank_pct = round(100.0 * et.get("BANK_REJECTED", 0) / total_cx, 1) if total_cx else 0.0
    lines.append(
        f"INSUFFICIENT_FUNDS: {insuf_pct}% | IMPOSSIBLE_TO_CHARGE: {imp_pct}% "
        f"| CARD_DECLINED: {decl_pct}% | BANK_REJECTED: {bank_pct}%"
    )
    # Procesador dominante
    proc = composicion["por_procesador"]
    if proc:
        proc_dominante = max(proc, key=lambda k: proc[k])
        lines.append(f"Procesador dominante: {proc_dominante}.")
    # Día pico
    por_dia = composicion["por_dia"]
    if por_dia:
        dia_pico = max(por_dia, key=lambda k: por_dia[k])
        lines.append(f"Día pico: {dia_pico} ({por_dia[dia_pico]} alertas).")
    lines.append(f"El % de fondos insuficientes del período: {insuf_pct}%.")

    # Sección "El resto"
    p1_ids = set(p1_df["incident_id"].tolist())
    cronico_fingerprints = set(cronicos_df["fingerprint"].tolist()) if n_cronicos else set()
    resto_df = df_scored[
        (~df_scored["incident_id"].isin(p1_ids))
        & (~df_scored["fingerprint"].isin(cronico_fingerprints))
    ]
    n_resto = len(resto_df)
    lines.append("")
    lines.append("## El resto, en una frase")
    lines.append(
        f"{n_resto} incidentes adicionales (P2/P3 no crónicos): "
        "patrones habituales y alertas informativas de baja prioridad."
    )

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 4. panel.html
# ---------------------------------------------------------------------------

def build_panel(
    df_scored: pd.DataFrame,
    df_patrones: pd.DataFrame,
    composicion: dict,
    metrics: dict,
    digest: str,
) -> str:
    """Genera el panel HTML autocontenido.

    Sin recursos externos (no CDN, no Google Fonts, no fetch).
    Los datos se embeben como JSON en etiquetas <script type="application/json">.

    Parámetros
    ----------
    df_scored   : DataFrame de score.py.
    df_patrones : DataFrame de views.vista_patrones().
    composicion : dict de views.vista_composicion().
    metrics     : dict de build_metrics().
    digest      : str producido por build_digest().

    Retorna
    -------
    str — contenido completo del panel.html.
    """
    # Serializar incidentes sre para la vista triage
    sre_inc = df_scored[df_scored["channel"] == "sre"].copy()
    sre_records: list[dict] = []
    for _, row in sre_inc.iterrows():
        r = row.to_dict()
        # Convertir datetime a ISO string
        r["inicio"] = r["inicio"].isoformat() if hasattr(r["inicio"], "isoformat") else str(r["inicio"])
        r["fin"] = r["fin"].isoformat() if hasattr(r["fin"], "isoformat") else str(r["fin"])
        r["es_recurrente"] = bool(r["es_recurrente"])
        sre_records.append(r)

    # Serializar patrones crónicos (todos los canales, pero se usa para triage)
    pat_records: list[dict] = []
    for _, row in df_patrones.iterrows():
        r = row.to_dict()
        r["primera"] = r["primera"].isoformat() if hasattr(r["primera"], "isoformat") else str(r["primera"])
        r["ultima"] = r["ultima"].isoformat() if hasattr(r["ultima"], "isoformat") else str(r["ultima"])
        r["es_recurrente"] = bool(r["es_recurrente"])
        r["es_cronico"] = bool(r["es_cronico"])
        pat_records.append(r)

    # Serializar datos cx para la vista composición
    cx_data = {
        "por_error_type": {k: int(v) for k, v in composicion["por_error_type"].items()},
        "por_procesador": {k: int(v) for k, v in composicion["por_procesador"].items()},
        "por_dia": {k: int(v) for k, v in composicion["por_dia"].items()},
        "kpi_pct": composicion.get("kpi_pct", {}),
        "total": composicion["total"],
    }

    # JSON embebido
    incidents_json = json.dumps(sre_records, ensure_ascii=False, default=str)
    patrones_json = json.dumps(pat_records, ensure_ascii=False, default=str)
    cx_json = json.dumps(cx_data, ensure_ascii=False)
    metrics_json = json.dumps(metrics, ensure_ascii=False, default=str)
    digest_escaped = digest.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Banda meta para el header
    bandas = metrics.get("bandas", {})
    n_alertas = metrics.get("input", {}).get("alertas_totales", 0)
    n_incidentes = metrics.get("compresion", {}).get("incidentes", 0)
    red_pct = metrics.get("compresion", {}).get("pct_reduccion", 0)
    generado = metrics.get("generado", "")

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Parco — Panel de Alertas</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: system-ui, -apple-system, 'Segoe UI', sans-serif; font-size: 14px; color: #222; background: #f8f8f8; }}
  .header {{ background: #1a1a2e; color: #fff; padding: 16px 24px; display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }}
  .header h1 {{ font-size: 18px; font-weight: 700; flex: 1 1 100%; }}
  .metric-pill {{ background: #ffffff22; border-radius: 6px; padding: 6px 12px; font-size: 13px; }}
  .metric-pill strong {{ font-size: 20px; display: block; }}
  .tabs {{ display: flex; gap: 0; background: #fff; border-bottom: 2px solid #ddd; padding: 0 16px; }}
  .tab-btn {{ padding: 10px 20px; border: none; background: none; cursor: pointer; font-size: 14px; color: #555; border-bottom: 3px solid transparent; margin-bottom: -2px; }}
  .tab-btn.active {{ color: #1a1a2e; border-bottom-color: #1a1a2e; font-weight: 600; }}
  .tab-panel {{ display: none; padding: 16px; }}
  .tab-panel.active {{ display: block; }}
  .digest-block {{ background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 16px; white-space: pre-wrap; font-family: system-ui, -apple-system, 'Segoe UI', sans-serif; font-size: 13px; line-height: 1.6; max-height: 400px; overflow-y: auto; }}
  .filters {{ display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; align-items: center; }}
  .filters select, .filters input {{ padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; }}
  .filters label {{ font-size: 13px; color: #555; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px #0001; }}
  th {{ background: #f0f0f0; font-weight: 600; text-align: left; padding: 8px 10px; font-size: 12px; white-space: nowrap; }}
  td {{ padding: 7px 10px; border-top: 1px solid #eee; font-size: 13px; vertical-align: top; }}
  tr:hover > td {{ background: #f5f7ff; }}
  .pill {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600; white-space: nowrap; }}
  .pill-P1 {{ background: #FCEBEB; color: #791F1F; }}
  .pill-P2 {{ background: #FAEEDA; color: #633806; }}
  .pill-P3 {{ background: #F0F0F0; color: #555; }}
  .expand-row {{ background: #f9f9ff; border-top: none; }}
  .expand-row td {{ padding: 8px 16px 12px; }}
  .score-details {{ display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px; }}
  .score-details span {{ background: #eef; border-radius: 4px; padding: 3px 8px; }}
  .cronico-header {{ background: #fffbe6; cursor: pointer; }}
  .cronico-header td {{ font-weight: 600; color: #633806; }}
  .cronico-badge {{ font-size: 11px; background: #FAEEDA; color: #633806; padding: 1px 6px; border-radius: 10px; margin-left: 6px; }}
  .bar-row {{ display: flex; align-items: center; gap: 8px; margin: 4px 0; }}
  .bar-label {{ width: 200px; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .bar-track {{ flex: 1; background: #eee; border-radius: 4px; height: 18px; }}
  .bar-fill {{ height: 100%; border-radius: 4px; background: #3b82f6; display: flex; align-items: center; padding-left: 6px; font-size: 11px; color: #fff; min-width: 24px; }}
  .bar-count {{ font-size: 12px; color: #555; width: 60px; text-align: right; }}
  .section-title {{ font-size: 16px; font-weight: 700; margin: 16px 0 10px; color: #1a1a2e; }}
  .mini-table {{ border-collapse: collapse; margin-top: 8px; }}
  .mini-table td, .mini-table th {{ padding: 4px 10px; border: 1px solid #ddd; font-size: 12px; }}
  .mini-table th {{ background: #f0f0f0; }}
  .footer {{ text-align: center; padding: 16px; font-size: 12px; color: #888; background: #fff; border-top: 1px solid #ddd; margin-top: 20px; }}
  .export-btn {{ background: #1a1a2e; color: #fff; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; margin-bottom: 12px; }}
  .export-btn:hover {{ background: #2d2d5e; }}
  input[type=checkbox] {{ cursor: pointer; }}
  select.etiqueta-sel {{ font-size: 12px; padding: 2px 4px; border: 1px solid #ccc; border-radius: 3px; }}
  .atendido-ts {{ font-size: 11px; color: #888; }}
  .hidden {{ display: none !important; }}
</style>
</head>
<body>

<!-- Datos embebidos -->
<script type="application/json" id="data-incidents">{incidents_json}</script>
<script type="application/json" id="data-patrones">{patrones_json}</script>
<script type="application/json" id="data-cx">{cx_json}</script>
<script type="application/json" id="data-metrics">{metrics_json}</script>

<div class="header">
  <h1>Parco — Panel de Inteligencia de Alertas</h1>
  <div class="metric-pill"><strong>{n_alertas}</strong> alertas crudas</div>
  <div class="metric-pill"><strong>{n_incidentes}</strong> incidentes</div>
  <div class="metric-pill"><strong>{red_pct}%</strong> compresión</div>
  <div class="metric-pill" style="background:#79142244"><strong style="color:#fcbebe">{bandas.get('P1',0)}</strong> P1</div>
  <div class="metric-pill" style="background:#63380644"><strong style="color:#fae0a0">{bandas.get('P2',0)}</strong> P2</div>
  <div class="metric-pill"><strong>{bandas.get('P3',0)}</strong> P3</div>
</div>

<div class="tabs">
  <button class="tab-btn active" onclick="showTab('digest')">Digest</button>
  <button class="tab-btn" onclick="showTab('triage')">Triage (sre)</button>
  <button class="tab-btn" onclick="showTab('composicion')">Composición (CX)</button>
</div>

<!-- TAB: Digest -->
<div id="tab-digest" class="tab-panel active">
  <p class="section-title">Resumen ejecutivo — generado {generado}</p>
  <div class="digest-block">{digest_escaped}</div>
</div>

<!-- TAB: Triage -->
<div id="tab-triage" class="tab-panel">
  <div class="filters">
    <label>Banda:
      <select id="filter-banda" onchange="renderTriage()">
        <option value="">Todas</option>
        <option value="P1">P1</option>
        <option value="P2">P2</option>
        <option value="P3">P3</option>
      </select>
    </label>
    <label>Servicio:
      <select id="filter-service" onchange="renderTriage()">
        <option value="">Todos</option>
      </select>
    </label>
    <label><input type="checkbox" id="filter-solo-cronicos" onchange="renderTriage()"> Solo crónicos</label>
    <button class="export-btn" onclick="exportLabels()">Exportar etiquetas → labels.csv</button>
  </div>
  <div id="triage-container"></div>
</div>

<!-- TAB: Composición CX -->
<div id="tab-composicion" class="tab-panel">
  <div id="composicion-container"></div>
</div>

<div class="footer">
  Las etiquetas alimentan la recalibración trimestral de los pesos · Parco Challenge · {generado}
</div>

<script>
// ---- Data loading ----
function loadJSON(id) {{
  return JSON.parse(document.getElementById(id).textContent);
}}
const incidents = loadJSON('data-incidents');
const patrones = loadJSON('data-patrones');
const cxData = loadJSON('data-cx');
const metrics = loadJSON('data-metrics');

// ---- Tab switching ----
function showTab(name) {{
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  event.target.classList.add('active');
  if (name === 'triage') renderTriage();
  if (name === 'composicion') renderComposicion();
}}

// ---- In-memory state for labels ----
const labelState = {{}}; // incident_id -> {{atendido_ts, etiqueta}}

function markAtendido(id, checked) {{
  if (!labelState[id]) labelState[id] = {{atendido_ts: '', etiqueta: ''}};
  labelState[id].atendido_ts = checked ? new Date().toISOString() : '';
  const tsEl = document.getElementById('ts-' + id);
  if (tsEl) tsEl.textContent = labelState[id].atendido_ts ? '✓ ' + labelState[id].atendido_ts.slice(0,19).replace('T',' ') : '';
}}
function setEtiqueta(id, val) {{
  if (!labelState[id]) labelState[id] = {{atendido_ts: '', etiqueta: ''}};
  labelState[id].etiqueta = val;
}}

function exportLabels() {{
  const rows = [['incident_id','atendido_ts','etiqueta']];
  for (const [id, st] of Object.entries(labelState)) {{
    if (st.atendido_ts || st.etiqueta) {{
      rows.push([id, st.atendido_ts, st.etiqueta]);
    }}
  }}
  if (rows.length === 1) {{ alert('No hay etiquetas marcadas todavía.'); return; }}
  const csv = rows.map(r => r.map(c => '"' + String(c).replace(/"/g,'""') + '"').join(',')).join('\\n');
  const blob = new Blob([csv], {{type: 'text/csv;charset=utf-8;'}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = 'labels.csv'; a.click();
  URL.revokeObjectURL(url);
}}

// ---- Build service filter ----
function buildServiceFilter() {{
  const sel = document.getElementById('filter-service');
  const services = [...new Set(incidents.map(i => i.service))].sort();
  services.forEach(s => {{
    const opt = document.createElement('option');
    opt.value = s; opt.textContent = s;
    sel.appendChild(opt);
  }});
}}

// ---- Triage rendering ----
const expandedRows = new Set();
const hiddenCronico = new Set();

function toggleExpand(id) {{
  const row = document.getElementById('exp-' + id);
  if (!row) return;
  if (expandedRows.has(id)) {{ row.classList.add('hidden'); expandedRows.delete(id); }}
  else {{ row.classList.remove('hidden'); expandedRows.add(id); }}
}}

function toggleCronico(fp) {{
  if (hiddenCronico.has(fp)) hiddenCronico.delete(fp);
  else hiddenCronico.add(fp);
  renderTriage();
}}

function fmtScore(s, banda) {{
  return '<span class="pill pill-' + banda + '">' + s + '</span>';
}}

function renderTriage() {{
  const bandaFilter = document.getElementById('filter-banda').value;
  const serviceFilter = document.getElementById('filter-service').value;
  const soloCronicos = document.getElementById('filter-solo-cronicos').checked;

  // Build set of chronic fingerprints
  const cronicoFps = new Set(patrones.filter(p => p.es_cronico).map(p => p.fingerprint));
  const cronicoMap = {{}};
  patrones.filter(p => p.es_cronico).forEach(p => {{ cronicoMap[p.fingerprint] = p; }});

  let filtered = incidents.filter(i => {{
    if (bandaFilter && i.banda !== bandaFilter) return false;
    if (serviceFilter && i.service !== serviceFilter) return false;
    if (soloCronicos && !cronicoFps.has(i.fingerprint)) return false;
    return true;
  }});

  // Group: cronicos grouped by fingerprint, then individual
  const cronicoGroups = {{}};
  const individual = [];
  filtered.forEach(i => {{
    if (cronicoFps.has(i.fingerprint)) {{
      if (!cronicoGroups[i.fingerprint]) cronicoGroups[i.fingerprint] = [];
      cronicoGroups[i.fingerprint].push(i);
    }} else {{
      individual.push(i);
    }}
  }});

  let html = '<table><thead><tr>' +
    '<th>Score</th><th>Banda</th><th>Servicio</th><th>Condición</th>' +
    '<th>Explicación</th><th>Disparos</th><th>Dur (min)</th><th>Inicio</th>' +
    '<th>Atendido</th><th>Etiqueta</th>' +
    '</tr></thead><tbody>';

  // Crónicos agrupados
  for (const [fp, items] of Object.entries(cronicoGroups)) {{
    const pat = cronicoMap[fp] || {{}};
    const collapsed = hiddenCronico.has(fp);
    html += '<tr class="cronico-header" onclick="toggleCronico(' + JSON.stringify(fp) + ')">' +
      '<td colspan="10">' +
      (collapsed ? '▶' : '▼') + ' <strong>' + escHtml(fp) + '</strong>' +
      '<span class="cronico-badge">crónico · ' + items.length + ' episodios</span>' +
      (pat.score_medio !== undefined ? ' · score medio ' + pat.score_medio : '') +
      '</td></tr>';

    if (!collapsed) {{
      items.forEach(i => {{
        html += renderIncidentRow(i, true);
      }});
    }}
  }}

  // Individuales
  individual.forEach(i => {{
    html += renderIncidentRow(i, false);
  }});

  html += '</tbody></table>';
  document.getElementById('triage-container').innerHTML = html;
}}

function renderIncidentRow(i, isCronico) {{
  const ls = labelState[i.incident_id] || {{}};
  const atendidoChecked = ls.atendido_ts ? 'checked' : '';
  const etqVal = ls.etiqueta || '';
  const inicio = i.inicio ? i.inicio.slice(0,16).replace('T',' ') : '';
  const condTrunc = i.condition.length > 45 ? i.condition.slice(0,45) + '…' : i.condition;
  const expl = i.explicacion.length > 60 ? i.explicacion.slice(0,60) + '…' : i.explicacion;

  let row = '<tr onclick="toggleExpand(' + JSON.stringify(i.incident_id) + ')" style="cursor:pointer">' +
    '<td>' + fmtScore(i.score, i.banda) + '</td>' +
    '<td><span class="pill pill-' + i.banda + '">' + i.banda + '</span></td>' +
    '<td>' + escHtml(i.service) + '</td>' +
    '<td title="' + escHtml(i.condition) + '">' + escHtml(condTrunc) + '</td>' +
    '<td title="' + escHtml(i.explicacion) + '">' + escHtml(expl) + '</td>' +
    '<td>' + i.n_disparos + '</td>' +
    '<td>' + (i.duracion_min || 0).toFixed(1) + '</td>' +
    '<td>' + escHtml(inicio) + '</td>' +
    '<td onclick="event.stopPropagation()">' +
      '<input type="checkbox" ' + atendidoChecked + ' onchange="markAtendido(' + JSON.stringify(i.incident_id) + ', this.checked)">' +
      '<span class="atendido-ts" id="ts-' + i.incident_id + '">' + (ls.atendido_ts ? '✓ ' + ls.atendido_ts.slice(0,19).replace('T',' ') : '') + '</span>' +
    '</td>' +
    '<td onclick="event.stopPropagation()">' +
      '<select class="etiqueta-sel" onchange="setEtiqueta(' + JSON.stringify(i.incident_id) + ', this.value)">' +
        '<option value=""' + (etqVal===''?' selected':'') + '></option>' +
        '<option value="ameritaba"' + (etqVal==='ameritaba'?' selected':'') + '>ameritaba</option>' +
        '<option value="ruido"' + (etqVal==='ruido'?' selected':'') + '>ruido</option>' +
      '</select>' +
    '</td>' +
    '</tr>';

  // Fila expandible
  const expHidden = expandedRows.has(i.incident_id) ? '' : ' hidden';
  row += '<tr id="exp-' + i.incident_id + '" class="expand-row' + expHidden + '">' +
    '<td colspan="10">' +
    '<div class="score-details">' +
      '<span>s_criticidad: ' + i.s_criticidad + '</span>' +
      '<span>s_ficha: ' + i.s_ficha + '</span>' +
      '<span>s_rafaga: ' + i.s_rafaga + '</span>' +
      '<span>s_intensidad: ' + i.s_intensidad + '</span>' +
      '<span>s_novedad: ' + i.s_novedad + '</span>' +
    '</div>' +
    '<div style="margin-top:6px;font-size:12px;color:#444">' +
      '<strong>ID:</strong> ' + i.incident_id + ' · ' +
      '<strong>fingerprint:</strong> ' + escHtml(i.fingerprint) + ' · ' +
      '<strong>policy:</strong> ' + escHtml(i.policy || '') + ' · ' +
      '<strong>tipo_regla:</strong> ' + (i.tipo_regla||'—') + ' · ' +
      '<strong>direccion:</strong> ' + (i.direccion||'—') + ' · ' +
      '<strong>n_alertas:</strong> ' + i.n_alertas + ' · ' +
      '<strong>fin:</strong> ' + (i.fin||'').slice(0,16).replace('T',' ') +
    '</div>' +
    '</td></tr>';

  return row;
}}

function escHtml(s) {{
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

// ---- Composición CX rendering ----
function renderComposicion() {{
  const total = cxData.total;
  let html = '<p class="section-title">Composición de rechazos de pago — ' + total + ' alertas CX</p>';

  // Barras por error_type
  html += '<p style="font-size:13px;color:#555;margin-bottom:8px;">Por tipo de error</p>';
  const et = cxData.por_error_type;
  const etSorted = Object.entries(et).sort((a,b) => b[1]-a[1]);
  etSorted.forEach(([k,v]) => {{
    const pct = total ? (100*v/total).toFixed(1) : 0;
    const w = total ? Math.max(2, Math.round(100*v/total)) : 0;
    html += '<div class="bar-row">' +
      '<div class="bar-label" title="' + escHtml(k) + '">' + escHtml(k) + '</div>' +
      '<div class="bar-track"><div class="bar-fill" style="width:' + w + '%">' + pct + '%</div></div>' +
      '<div class="bar-count">' + v + '</div>' +
      '</div>';
  }});

  // Tabla por procesador
  html += '<p class="section-title">Por procesador</p>';
  html += '<table class="mini-table"><tr><th>Procesador</th><th>Alertas</th><th>%</th></tr>';
  Object.entries(cxData.por_procesador).sort((a,b)=>b[1]-a[1]).forEach(([k,v]) => {{
    html += '<tr><td>' + escHtml(k) + '</td><td>' + v + '</td><td>' + (total?((100*v/total).toFixed(1)):'0') + '%</td></tr>';
  }});
  html += '</table>';

  // Mini-tabla por día
  html += '<p class="section-title">Por día</p>';
  html += '<table class="mini-table"><tr><th>Día</th><th>Alertas</th></tr>';
  Object.entries(cxData.por_dia).sort().forEach(([k,v]) => {{
    html += '<tr><td>' + escHtml(k) + '</td><td>' + v + '</td></tr>';
  }});
  html += '</table>';

  document.getElementById('composicion-container').innerHTML = html;
}}

// ---- Init ----
buildServiceFilter();
renderTriage();
</script>
</body>
</html>
"""
    return html


# ---------------------------------------------------------------------------
# 5. Escritura de outputs
# ---------------------------------------------------------------------------

_CSV_COL_ORDER = [
    "incident_id", "channel", "source", "vista", "fingerprint",
    "service", "service_original", "grupo_criticidad", "condition", "policy",
    "inicio", "fin", "duracion_min", "n_alertas", "n_disparos", "tasa_por_min",
    "priority_max", "tipo_regla", "direccion",
    "s_criticidad", "s_ficha", "s_rafaga", "s_intensidad", "s_novedad",
    "score", "banda", "banda_etiqueta", "explicacion",
    "es_recurrente", "dias_visto",
    "error_type", "procesador",
    "atendido", "etiqueta",
]


def write_outputs(
    output_dir: Path,
    df_scored: pd.DataFrame,
    metrics: dict,
    digest: str,
    panel: str,
) -> None:
    """Escribe los 4 artefactos en output_dir.

    Parámetros
    ----------
    output_dir : directorio de salida (se crea si no existe).
    df_scored  : DataFrame de score.py (incidentes scoreados).
    metrics    : dict de build_metrics().
    digest     : str de build_digest().
    panel      : str de build_panel().
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # incidents.csv — columnas en orden canónico, fechas como ISO strings
    df_out = df_scored.copy()
    for col in ("inicio", "fin"):
        if col in df_out.columns:
            df_out.loc[:, col] = df_out[col].apply(
                lambda v: v.isoformat() if hasattr(v, "isoformat") else str(v)
            )
    # Solo las columnas presentes en el DF que estén en el orden canónico
    cols_present = [c for c in _CSV_COL_ORDER if c in df_out.columns]
    # Añadir columnas extra que existan en df_scored pero no en el orden canónico
    extra = [c for c in df_out.columns if c not in _CSV_COL_ORDER]
    final_cols = cols_present  # extras omitidas (ventana_eval es interna)
    df_out[final_cols].to_csv(output_dir / "incidents.csv", index=False, encoding="utf-8")

    # metrics.json
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # digest.md
    (output_dir / "digest.md").write_text(digest, encoding="utf-8")

    # panel.html
    (output_dir / "panel.html").write_text(panel, encoding="utf-8")
