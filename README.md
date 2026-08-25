# parco-challenge — Pipeline de inteligencia de alertas

Un canal de Slack recibe 458 alertas crudas sin estructura ni prioridad; este pipeline las deduplica, las puntúa (score 0-100) y produce cuatro artefactos consumibles por Ops y Tech en dos minutos un lunes en la mañana.

## Setup

```bash
python3 -m venv venv_parco && source venv_parco/bin/activate
pip install -r requirements.txt
cp .env.example .env  # agregar GEMINI_API_KEY (opcional — el pipeline corre sin ella)
```

## Run

```bash
python pipeline.py --input data/raw/alerts_combined.json
# Sin LLM (no requiere API key):
python pipeline.py --input data/raw/alerts_combined.json --no-llm
```

## Test

```bash
pytest
```

## Outputs

Todos los artefactos se escriben en `output/`:

| Archivo | Descripción |
|---|---|
| `incidents.csv` | Una fila por incidente deduplicado con score 0-100 y banda P1/P2/P3. Fuente de verdad. |
| `metrics.json` | Métricas de la corrida: compresión, bandas, KPI de pagos, calidad de datos. |
| `digest.md` | Resumen ejecutivo de 2 minutos: P1s, crónicos, composición CX. Narrativa opcional vía Gemini 2.5 Flash. |
| `panel.html` | Panel interactivo autocontenido (abre con doble clic). Vista triage + composición CX. Exporta `labels.csv`. |

## Decisiones clave

- **Reloj confiable por canal**: `sre` usa `ts` (epoch); `monitoring-ops-cx` usa `timestamp` (ISO). Nunca un solo campo global. Ver `docs/decisiones.md`.
- **Fingerprint por exact-match**: 23 plantillas exactas — no fuzzy matching, no embeddings, no LLM para agrupar. Ver `docs/eda.md`.
- **Score de 5 componentes**: criticidad del servicio, desviación de la ficha histórica, tamaño de ráfaga, intensidad (high/critical/anomalía), novedad. Pesos en `config.yaml`. Ver `docs/eda.md`.
- **Sin z-scores**: n=458 no lo sostiene; la ficha de recurrencia usa medianas y conteos discretos. Ver `docs/decisiones.md`.
- **LLM solo en el digest**: Gemini 2.5 Flash narra, no calcula. Los números vienen del CSV; el modelo los contextualiza. Con `--no-llm` el digest es igualmente válido.
- **Dos vistas, una fuente**: `incidents.csv` no cambia; `triage` (sre) y `composicion` (cx) son perspectivas sobre el mismo archivo.
- **Determinismo**: correr el pipeline dos veces produce `incidents.csv` byte a byte idéntico (solo `generado` en `metrics.json` varía).

## Arquitectura

```
pipeline.py --input data/raw/alerts_combined.json [--no-llm]
  src/ingest.py      carga y validación del JSON (458 registros, 3 esquemas)
  src/normalize.py   adaptadores por canal → esquema canónico; reloj, typos, threshold
  src/dedupe.py      fingerprint + ventana 30 min → 277 incidentes
  src/profiles.py    fichas de recurrencia por (channel, fingerprint)
  src/score.py       score 0-100, 5 componentes, pesos desde config.yaml
  src/views.py       vista triage (sre), composición (cx), patrones crónicos
  src/report.py      metrics.json, digest.md (Gemini 2.5 Flash), panel.html
```

Todo parámetro de negocio (pesos, criticidades, ventanas) vive en `config.yaml`.
La documentación de decisiones, supuestos y gestión vive en `docs/`.
