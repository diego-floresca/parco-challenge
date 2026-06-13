# Especificación de outputs — contratos exactos
> Si el pipeline produce estos cuatro artefactos con estos esquemas, está terminado.
> Cualquier columna/llave adicional se discute antes de agregarse. Nombres en snake_case.

## 1. output/incidents.csv — la fuente de verdad
Una fila por INCIDENTE (no por alerta). Orden: score descendente. Encoding UTF-8.

| Columna | Tipo | Descripción |
|---|---|---|
| incident_id | str | `INC-{NNNN}` secuencial determinista (orden cronológico de inicio) |
| channel | str | sre \| monitoring-ops-cx |
| vista | str | triage \| composicion (derivada del canal) |
| fingerprint | str | `{service}::{condition}` |
| service | str | servicio normalizado (Princess unificado; infra agrupado) |
| service_original | str | el valor crudo del JSON |
| grupo_criticidad | str | pagos \| nucleo \| datos \| infra \| codename \| web (de config.yaml) |
| condition | str | la plantilla tal cual |
| policy | str | tal cual (incluye Up_Satatus_Parco con su typo) |
| inicio / fin | str ISO | primer y último disparo del incidente, en el reloj confiable del canal, tz -06:00 |
| duracion_min | float | (fin - inicio) en minutos; 0 para incidente de 1 alerta |
| n_alertas | int | mensajes de Slack agrupados |
| n_disparos | int | suma de columna `incidents` de New Relic (null -> 1) |
| tasa_por_min | float | n_disparos / max(duracion_min, 1) |
| priority_max | str | high \| critical \| null (la máxima observada en el incidente) |
| tipo_regla | str | estatica \| anomalia \| null (threshold contiene "baseline" -> anomalia) |
| direccion | str | sobre \| bajo \| null (operador del threshold) |
| s_criticidad, s_ficha, s_rafaga, s_intensidad, s_novedad | float 0-1 | componentes del score, SIEMPRE visibles (transparencia) |
| score | int 0-100 | redondeado |
| banda | str | P1 \| P2 \| P3 |
| banda_etiqueta | str | "Atiende ahora" \| "Revisa hoy" \| "Informativo, no requiere acción" |
| explicacion | str | una frase en cristiano, generada por reglas (NO por LLM), ej. "Rechazos de pago en el canal de infraestructura, donde casi nunca se reportan" |
| es_recurrente | bool | ficha con dias_visto >= recurrente_min_dias |
| dias_visto | int | de la ficha del fingerprint |
| error_type | str | solo cx; vacío en sre |
| procesador | str | solo cx, extraído de error_message; vacío si no se detecta |
| atendido | str | VACÍO al generarse (lo llena el humano en el panel) |
| etiqueta | str | VACÍO al generarse (ameritaba \| ruido, lo llena el humano) |

Reglas de la columna `explicacion` (plantillas por condición dominante, en este orden):
1. fingerprint sin ficha o dias_visto <= 1 -> "Primera vez que se observa este comportamiento en {service}"
2. canal inusual (Payments rejected fuera de cx) -> "Rechazos de pago en el canal de infraestructura, donde casi nunca se reportan"
3. tipo_regla == anomalia -> "Detectado por la regla de anomalías de New Relic sobre {service}"
4. direccion == bajo -> "El tráfico de {service} CAYÓ por debajo de su mínimo: degradación silenciosa"
5. es_recurrente y dentro de horas_tipicas -> "Patrón habitual de {service}: visto {dias_visto} días, típicamente a las {hora}h"
6. default -> "{condition} en {service}, {n_disparos} disparos en {duracion_min:.0f} min"

## 2. output/metrics.json
```json
{
  "generado": "ISO timestamp de la corrida",
  "input": {"alertas_totales": 458, "por_canal": {"sre": 363, "monitoring-ops-cx": 95},
             "rango_sre": ["2025-05-26", "2025-06-11"], "rango_cx": ["2026-03-24", "2026-03-27"]},
  "compresion": {"incidentes": 277, "ratio": "458 -> 277", "pct_reduccion": 39.5,
                  "rafagas": 46, "alertas_en_rafagas": 227,
                  "disparos_reales_newrelic": 664},
  "ruido": {"definicion_ingenua_pct": 89.0, "redundancia_dura_pct": 40.0,
             "nota": "ambos en % de alertas crudas; ver docs/decisiones.md - la definición importa más que el número"},
  "bandas": {"P1": 0, "P2": 0, "P3": 0},
  "kpi_payments": {"total_rechazos": 95,
                    "composicion_pct": {"INSUFFICIENT_FUNDS": 29.5, "...": 0},
                    "por_procesador": {"Conekta": 0, "Mercadopago": 0},
                    "por_dia": {"2026-03-24": 57, "...": 0}},
  "calidad_datos": {"duplicados_exactos": 0, "registros_paypal_status": 3,
                     "typos_normalizados": ["Princes->Princess"],
                     "relojes": {"sre": "ts", "monitoring-ops-cx": "timestamp"}}
}
```
Los valores numéricos se calculan, no se copian: si difieren de los esperados,
los tests de aceptación lo gritan.

## 2.5. vista_patrones (insumo para digest y panel, no archivo independiente)

Producida por `views.vista_patrones(df_scored, config)`. Una fila por (channel, fingerprint).

| Columna | Tipo | Descripción |
|---|---|---|
| channel | str | canal |
| fingerprint | str | `{service}::{condition}` |
| service | str | servicio normalizado |
| n_incidentes | int | episodios en el período |
| score_medio | float | media de score de todos los episodios |
| score_max | int | score más alto del período |
| n_disparos_total | int | suma de n_disparos de todos los episodios |
| es_recurrente | bool | dias_visto >= recurrente_min_dias en su perfil |
| es_cronico | bool | es_recurrente AND n_incidentes >= cronico_min_incidentes (config) |
| primera | datetime | inicio del primer incidente del período |
| ultima | datetime | fin del último incidente del período |

**Crónico activo**: fingerprint con `es_recurrente=True` y `n_incidentes >= pipeline.cronico_min_incidentes` (default 5).
Son 19 de 43 fingerprints en el dataset real. Ejemplo canónico: `Orchestrator::high request count with status 500` — 45 episodios, score medio 43.9.
La distinción es de gestión: el crónico se gestiona como caso abierto (un ticket de ingeniería), no como alerta individual.
Esta vista es **insumo para digest.md y panel.html**; incidents.csv no cambia (sigue siendo una fila por incidente).

## 3. output/digest.md — los 2 minutos del lunes
Estructura fija (el LLM rellena la narrativa, NUNCA los números):
```
# Digest de alertas — {fecha de corrida}
Período procesado: {rangos} · {n} alertas -> {m} incidentes

## Merece tu atención ({k} incidentes P1)
- **{service} · {condition}** (score {s}, {banda_etiqueta}): {explicacion}. {narrativa_llm}
  ... (máximo 5; si hay más P1, los siguientes se listan en una línea)

## Crónicos activos — gestionar como caso, no como alerta ({c} patrones)
- **{service} · {condition}**: {n_incidentes} episodios en el período, score medio {score_medio} — {narrativa_llm}
  Ejemplo: "Orchestrator · 500s: 45 episodios, score medio 44 — problema estructural, abrir ticket de ingeniería"
  ... (todos los crónicos, ordenados por n_incidentes desc; máximo 8 en el digest; si hay más, nota al pie)

## Pagos (canal CX)
{composición del período: % por error_type, procesador dominante, día pico} — el % de
fondos insuficientes del período fue {x}%.

## El resto, en una frase
{n_p3 + P2 no-crónicos} incidentes informativos: {resumen de patrones habituales, ej. "el job nocturno
de data-team, el ritmo de fin de semana"}.
```
Prompt a Gemini 2.5 Flash (report.py):
- system: "Eres el narrador de un digest operativo. Recibes una tabla JSON de incidentes
  ya calculados. Redacta SOLO la narrativa de los campos {narrativa_llm}: contexto y
  consecuencia probable en <=25 palabras por incidente/crónico, español neutro, sin inventar
  números ni servicios que no estén en la tabla. Si no hay nada que agregar, devuelve
  cadena vacía."
- user: la tabla de incidentes P1 en JSON + la tabla de crónicos + el bloque de composición cx.
- Manejo: timeout 30s, 1 reintento; si falla o --no-llm: los campos {narrativa_llm}
  quedan vacíos y el digest sigue siendo válido (degradación elegante).

**Nota de reconciliación de calibración (2026-06-12):**
El diagnóstico con 277 incidentes reales reveló que el bloque P2 masivo (175/277) es un
hallazgo real, no un bug: 55 de esos P2 son Orchestrator crónico (problema estructural conocido).
Los umbrales P1≥70/P2≥40 se validaron contra valles naturales del histograma (anti-pico en 40-41,
salto en 70). El score y los umbrales no se tocaron; se añadió la sección "Crónicos activos" para
dar a estos incidentes una vía de gestión diferenciada sin inflar artificialmente P1.

## 4. output/panel.html — autocontenido, abre con doble clic
- Vanilla JS + CSS embebido, datos embebidos como JSON inline (sin fetch, sin backend,
  sin CDN: debe funcionar offline).
- Secciones, en orden:
  1. Header con métricas: alertas crudas -> incidentes, % redundancia, conteo por banda.
  2. Bloque digest (el mismo texto de digest.md, pre-renderizado).
  3. Vista triage: tabla de incidentes sre, orden score desc. Columnas visibles:
     score, banda_etiqueta (pill con color), service, explicacion, n_disparos,
     duracion_min, inicio. Fila expandible -> componentes del score (los 5 s_*) y
     detalle completo. Filtros: por banda y por service (selects simples).
  4. Vista composición: barras horizontales de error_type (conteo y %), tabla por
     procesador, mini-tabla por día.
  5. Columnas editables por fila: checkbox "atendido" (al marcarse guarda timestamp
     local) y select "etiqueta" (ameritaba | ruido). Botón "Exportar etiquetas" ->
     descarga labels.csv (incident_id, atendido_ts, etiqueta).
  6. Footer: "Las etiquetas alimentan la recalibración trimestral de los pesos" +
     versión/fecha de corrida.
- Persistencia: SOLO en memoria de la página + export manual a labels.csv. La
  persistencia real (BigQuery/Firestore) es fase 2 y vive en gestion.md, no aquí.
- Colores de banda: P1 fondo #FCEBEB texto #791F1F; P2 fondo #FAEEDA texto #633806;
  P3 gris neutro. Tipografía del sistema. Sin librerías de gráficas: las barras de
  composición son divs con width %.

## Criterio de terminado (Definition of Done)
1. `python pipeline.py --input data/raw/alerts_combined.json` produce los 4 artefactos
   sin errores en una máquina limpia (y con --no-llm también).
2. `pytest` verde: fixtures sintéticas + números de aceptación + invariantes.
3. Correr dos veces -> incidents.csv byte a byte idéntico.
4. panel.html abierto con doble clic muestra las dos vistas y exporta labels.csv.
5. README con máximo 3 comandos, dependencias pinneadas, sección "Decisiones clave"
   que apunta a docs/.
