# parco-challenge — Pipeline de inteligencia de alertas

## LECTURA OBLIGATORIA antes de escribir código
Este archivo es la constitución operativa. La memoria profunda del proyecto vive en:
- `docs/eda.md` — TODOS los hallazgos del análisis exploratorio con evidencia y números
- `docs/outputs.md` — contratos EXACTOS de incidents.csv, metrics.json, digest.md y panel.html
Léelos antes de implementar la capa correspondiente. Si una decisión de implementación
contradice algo escrito en estos documentos, detente y pregunta — no improvises.

## Contexto
Technical assessment para AI Engineer en Parco (app de movilidad, ~2M transacciones/mes).
Problema: un canal de Slack recibe alertas crudas sin estructura ni prioridad; lo crítico
se descubre tarde porque la señal queda sepultada bajo el ruido. Input: `data/raw/alerts_combined.json`
(458 alertas, 2 canales de Slack). Output: incidentes deduplicados, scoreados y consumibles
por Ops/Tech sin contexto adicional ("2 minutos un lunes en la mañana").

El producto tiene DOS vistas sobre una sola fuente de verdad (`output/incidents.csv`):
- **Triage** (canal `sre`): incidentes con score 0-100 y banda P1/P2/P3. Pregunta: ¿qué atiendo primero?
- **Composición** (canal `monitoring-ops-cx`): agregación de rechazos de pago por error_type
  y procesador. Pregunta: ¿de qué se componen mis errores de pago? (KPI de Payments: % INSUFFICIENT_FUNDS)

## Mapa del archivo de entrada (CRÍTICO)
`alerts_combined.json` concatena TRES exports con personalidades distintas:
| Segmento | Índices (orden del archivo) | Canal | Período real | Reloj confiable |
|---|---|---|---|---|
| 1 | 0–151   | sre | 7–11 jun 2025   | `ts` e ISO coinciden (usar `ts`) |
| 2 | 152–362 | sre | 26 may–4 jun 2025 | `ts` (el ISO tiene desfases erráticos de −17h a +6h) |
| 3 | 363–457 | monitoring-ops-cx | 24–27 mar 2026 | `timestamp` ISO (el `ts` es sintético: gap fijo de 5.0 min) |
La implementación NO debe depender de índices: la regla operativa es POR CANAL
(sre -> ts, cx -> ISO), que produce el mismo resultado y es robusta a datos nuevos.

## Arquitectura (pipeline por capas, DAG determinista)
```
pipeline.py --input data/raw/alerts_combined.json [--no-llm]
  src/ingest.py      carga y validación del JSON
  src/normalize.py   adaptadores por source -> esquema canónico
  src/dedupe.py      fingerprint + ventana temporal -> incidentes
  src/profiles.py    fichas de recurrencia por fingerprint
  src/score.py       score 0-100, 5 componentes, pesos desde config.yaml
  src/views.py       vista triage (sre) y vista composición (cx)
  src/report.py      digest.md (Gemini 2.5 Flash, degradable con --no-llm), panel.html, metrics.json
```
Todo parámetro de negocio vive en `config.yaml` (pesos, criticidades, ventanas, mapas de
normalización). El código NO hardcodea criticidades ni pesos.

## Reglas de datos NO NEGOCIABLES (provienen del EDA; evidencia en docs/eda.md)
1. **Reloj confiable por canal**: en `sre` usar `ts` (epoch); en `monitoring-ops-cx` usar
   `timestamp` (ISO). NUNCA usar un solo campo de tiempo globalmente.
2. **Fingerprint** = (service_normalizado, condition). Los mensajes son 23 plantillas exactas:
   exact-match basta, NO usar fuzzy matching, embeddings ni LLM para agrupar.
3. **Normalización de services**: `Princes` -> `Princess`; servicios `i-*` y `new-parco-instance-*`
   -> grupo `infra` (conservar el nombre original en columna `service_original`).
4. **Incidente** = alertas del mismo fingerprint con gap <= ventana (config: 30 min).
   El tamaño real del incidente (`n_disparos`) suma la columna `incidents` de New Relic
   (con null -> 1); `n_alertas` cuenta mensajes.
5. **error_type/error_message** solo existen en cx (NO es missingness, es esquema por fuente;
   la completitud se reporta por fuente, nunca global). De error_message se extrae el campo
   derivado `procesador` (Conekta, Mercadopago, PayPal) por regex.
6. **threshold** se parsea a 3 derivados: tipo_regla (estatica|anomalia si contiene "baseline"),
   direccion (sobre|bajo según > o <), ventana_eval. No construir un motor de reglas.
7. **LLM (Gemini 2.5 Flash)** SOLO en report.py para narrar el digest desde la tabla ya
   calculada. Los números del digest se inyectan del CSV; el modelo narra, no calcula.
   Con --no-llm (o sin GEMINI_API_KEY) el digest sale de una plantilla determinista.
   API key vía .env (GEMINI_API_KEY), nunca commiteada.
8. **Los 3 registros de PayPal Status** (source != New Relic) pasan por su propio adaptador:
   priority/policy/incidents son null, el estado viene embebido en condition
   ("- INITIAL"/"- RESOLVED"). No imputarles datos de New Relic.

## Score (v0, pesos en config.yaml)
```
score = 100 * ( w_criticidad * S_servicio      # tabla de criticidad por servicio
              + w_ficha      * S_fuera_ficha   # desviación de su recurrencia histórica
              + w_rafaga     * S_rafaga        # log(n_disparos) normalizado + tasa
              + w_intensidad * S_intensidad    # high=0.5, critical=1.0
              + w_novedad    * S_novedad )     # fingerprint nunca visto
```
Bandas: P1 >= 70 ("Atiende ahora"), P2 40-69 ("Revisa hoy"), P3 < 40 ("Informativo, no
requiere acción"). Ficha de recurrencia por fingerprint = {dias_visto, horas_tipicas,
sello_finde, rafaga_tipica} calculada del propio histórico, POR CANAL (los períodos de
sre y cx son disjuntos: nunca mezclar sus fichas). NO usar z-scores: n=458 no lo sostiene
(decisión documentada). Casos canónicos esperados en docs/eda.md sección 9.

## Números de aceptación (los tests de integración los afirman; detalle en docs/eda.md)
- 458 registros totales; 3 esquemas de llaves (360 / 95 / 3 registros)
- 23 conditions únicas; 28 services crudos; 5 policies; 2 channels (sre=363, cx=95)
- cx: 95 registros, 100% con error_type; composición: INSUFFICIENT_FUNDS=28,
  IMPOSSIBLE_TO_CHARGE=25, CARD_DECLINED=23, BANK_REJECTED=12
- Duplicados byte a byte: 0. Con ventana de 30 min: ~277 incidentes; 46 ráfagas
  contienen 227 alertas
- Suma de columna incidents ≈ 664 (3 registros con null)
- policy->channel es partición perfecta; condition->policy es 1 a 1
- Invariantes: ninguna alerta se pierde; cada alerta pertenece a exactamente 1 incidente;
  sum(n_alertas de incidentes) = 458; correr dos veces = output byte a byte idéntico

## Convenciones
- Python 3.11+, pandas; dependencias mínimas y pinneadas en requirements.txt
- Funciones puras por capa; cada capa testeable aislada (tests/ con fixtures sintéticas:
  ráfaga obvia, campo vacío, timestamp roto, servicio desconocido, registro PayPal)
- Outputs SIEMPRE a output/: incidents.csv, digest.md, panel.html, metrics.json
- panel.html es autocontenido (datos embebidos, vanilla JS, sin backend, abre con doble clic)
- Commits chicos con mensajes que narran la decisión, no solo el cambio
- README: máximo 3 comandos para correr todo (setup, run, test)

## Fuera de alcance (NO construir, está decidido y documentado)
- Motor de reglas sobre threshold; z-scores/estadística sobre las fichas; clasificación
  con LLM o embeddings; backend o base de datos para el panel; modo continuo/streaming
  (se diseña en gestion.md como fase 2 con n8n, no se implementa)

## Documentos (docs/)
- decisiones.md: qué se hizo, por qué, qué se descartó (juicio de relojes, veredicto del
  "80% es ruido": 89% bajo definición ingenua / 40% redundancia dura)
- supuestos.md: ambigüedades del brief y resolución (períodos disjuntos, n=458 vs
  "cientos al día", criticidades inferidas a validar en semana 0)
- gestion.md: stakeholders, ownership, métricas (norte: tiempo crítico->atención),
  baseline pre-despliegue, cadencia 30/60/90, kill criteria (~70% P1 atendidos),
  evolución (recalibración con etiquetas = ahí sí aplica train/test)
- glosario.md: el diccionario con analogías para gente no técnica
- eda.md y outputs.md: memoria profunda (este archivo apunta a ellos)

# Convenciones
- la carpeta analysis/ y sus archivo son de exploración, el pipeline NUNCA importa nada de ahí 
