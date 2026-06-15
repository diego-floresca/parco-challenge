# Gestión del proyecto — parco-challenge

Este documento responde las cuatro preguntas que la herramienta de hace un año
nunca respondió: quién la usa, quién es dueño de qué, cómo se sabe si funciona,
y cómo evoluciona. Esas cuatro preguntas sin respuesta son, según el propio
brief, la razón por la que esa herramienta "técnicamente funcionaba" pero dejó
de usarse sin que nadie tomara la decisión formalmente.

---

## 1 · Stakeholders

Ambas vistas son consultadas por ambos equipos — pero cada uno hace una pregunta
distinta en cada una. El panel es uno solo, con dos pestañas, precisamente porque
ninguna de las dos audiencias puede prescindir de ninguna de las dos vistas:

| Vista | Tech pregunta | Ops / Payments pregunta |
|---|---|---|
| **Triage (#sre)** | "¿qué de mi infraestructura necesita acción ahora?" — **consumidor primario**: marca `atendido`/`etiqueta`, son sus servicios y su código. | "¿el sistema está sano para operar hoy?" — consulta de contexto antes de operar. |
| **Composición (#cx)** | "¿algún pico de rechazos tiene causa técnica que deba investigar?" — consulta de contexto (un timeout o bug puede manifestarse como rechazos). | "¿cuál es mi % de fondos insuficientes este mes?" — **consumidor primario**, insumo directo del reporte mensual de Payments. |

| Rol | Relación con el sistema |
|---|---|
| **Tech** | Consumidor primario de triage (#sre); dueño de `config.yaml` (pesos, criticidades, ventanas); consulta composición (#cx) cuando un pico sugiere causa técnica. |
| **Ops / Payments** | Consumidor primario de composición (#cx) para su KPI mensual; consulta triage (#sre) como contexto de salud general antes de operar; marca `atendido`/`etiqueta` en el panel (rotación semanal, sección 2). |
| **Líder de soporte técnico** | Co-autor del análisis original de "80% es ruido". Su hipótesis se trata como contexto a verificar, no como instrucción — y el resultado (D-07) la refina sin descalificarla: la redundancia dura (39.5%) confirma que SÍ hay mucho ruido mecánico; la cifra de 80-89% depende de la definición. |
| **Dirección** | Audita adopción a 30/60/90 días contra el kill criteria (sección 4). |

---

## 2 · Ownership

| Responsabilidad | Owner | Notas |
|---|---|---|
| Revisar el digest cada mañana | Rotación semanal en Ops | Resuelve "todos lo ven, nadie lo procesa" con proceso, no con código — el brief mismo aclara que el ownership del canal es contexto organizacional, no algo que el pipeline pueda resolver. |
| Ajustar `config.yaml` (pesos, criticidades, ventanas) | Tech | Cambios versionados en git; cada ajuste es un commit con su razón (mismo estándar que `decisiones.md`). |
| Validar la tabla de criticidad v0 | Tech + Ops, semana 0 | Los grupos de criticidad (D-09, `config.yaml`) son **inferidos del comportamiento del dato**, no confirmados por el equipo. Es la primera reunión de trabajo real del proyecto. |
| Exportar y conservar `labels.csv` | Ops (rotación) | Hasta que exista persistencia real (sección 6, fase 2), las etiquetas viven en exports manuales periódicos. |
| Auditar métricas de adopción | Dirección | Mensual, contra la tabla de la sección 4. |

---

## 3 · Validar en semana 0 (antes de confiar en los números)

Estos son los supuestos que el pipeline asume hoy y que una sola reunión con el
equipo puede confirmar o corregir — sin tocar código, solo `config.yaml`:

- **Tabla de criticidad por servicio** (grupos `pagos`, `nucleo`, `datos`, `infra`,
  `codename`, `web` — D-09, `eda_hallazgos.md` §12). Inferida de qué *conditions*
  dispara cada servicio; nunca confirmada por alguien que sepa qué es `tesseract`
  o `Cerberus` en realidad.
- **Baseline pre-despliegue de la métrica norte** (sección 4): medir, durante la
  semana 0, cuánto tarda HOY un incidente crítico en recibir atención — sin la
  herramienta. Sin este número, "38 min" no tiene punto de comparación real.
- **Ventana de ráfaga (30 min) y `recurrente_min_dias` (3)** — perillas elegidas
  como punto de partida razonable, no derivadas de un SLA real de Ops. Si Ops
  normalmente revisa Slack cada 15 minutos, la ventana debería ajustarse.
- **`cronico_min_incidentes` (5)** — el umbral para que un patrón se marque
  "crónico activo" (D-13). Con más historia, este número se puede recalibrar.

---

## 4 · Cómo se sabe si funciona

### Métrica norte
**Tiempo entre que un incidente P1 comienza y se marca `atendido`.** Es la
traducción directa de la frase del brief: "cuando algo crítico falla, suele
descubrirse tarde". Hoy es inmedible — la columna `atendido` no existe en la
operación actual. La **semana 0 mide el baseline sin la herramienta**; sin esa
medición, ninguna mejora futura es demostrable (la lección de la herramienta
anterior: "no se midió nada antes de lanzarlo").

### Métricas de sistema (disponibles desde el día 1, del propio JSON)

| Métrica | Valor día 1 |
|---|---|
| Compresión (alertas → incidentes) | 39.5% |
| Redundancia dura (ráfagas) | 39.5% |
| Ruido amplio (ráfagas + recurrentes) | [valor recalculado, D-07] |
| Distribución de bandas | P1 6% · P2 63% · P3 31% |
| Crónicos activos | 5 patrones |
| KPI Payments (% fondos insuficientes) | 29.5% |

### Métricas de adopción — duales, porque las dos vistas tienen nociones distintas de "útil" (D-12)

- **Triage (#sre):** % de incidentes P1/P2 marcados `atendido` en el panel.
  Instrumentación: ya existe (columnas `atendido`/`etiqueta`), vacía hasta uso real.
- **Composición (#cx):** frecuencia de consulta del reporte + si el % de
  `INSUFFICIENT_FUNDS` calculado por el pipeline se citó en el reporte mensual
  real de Payments. Instrumentación: ligera y manual (log de consultas), porque
  "atender" no es una acción que tenga sentido por `error_type` individual —
  la acción es de negocio (ajustar procesador, abrir ticket), no de panel.

### Matriz de confusión: banda vs etiqueta humana
Cruza lo que el score predijo (P1/P2 = "atiende") contra lo que el humano
etiquetó (`ameritaba`/`ruido`). Requiere acumulación de etiquetas — vacía el
día 1 por diseño. Los falsos negativos (score dijo P3, humano dice "ameritaba")
son la categoría más cara y la más difícil de detectar — solo aparecen cuando
alguien revisa un P3 por curiosidad o porque algo falló y se rastreó hacia atrás.

### Kill criteria
**Si a los 90 días el % de P1 atendidos está por debajo de 60%, la herramienta
se rediseña o se mata formalmente.** El 60% no es la meta — es el piso de "no
está muerto": 50% equivale a que el usuario decida por volado si usar la
herramienta o no; 60% indica que ya hay una preferencia detectable, aunque
modesta. Es deliberadamente conservador para el criterio de *kill* (prefiere un
falso negativo — seguir con algo mediocre un poco más — sobre un falso positivo
— matar algo que apenas arrancaba). La meta real de adopción (probablemente
80%+) se fija en semana 0 con el equipo, una vez exista el baseline.

Revisión a 30 / 60 / 90 días:
- **Día 30:** primera lectura de adopción real, sin decisiones drásticas.
- **Día 60:** primera recalibración de pesos del score con las etiquetas
  acumuladas (D-09) — aquí sí aplica un split tipo validación, porque ya existe
  ground truth.
- **Día 90:** evaluación contra el kill criteria.

---

## 5 · Cómo evoluciona

- **Sistema nuevo generando alertas:** un adaptador nuevo en `normalize.py`
  (patrón ya probado con New Relic vs PayPal Status, D-01/D-02). Horas, no semanas.
- **Equipo rota:** `CLAUDE.md` + `docs/` + `glosario.md` son el onboarding — la
  misma documentación que permitió a un agente operar con criterio consistente
  durante el desarrollo sirve para una persona nueva.
- **Prioridades de negocio cambian:** ajustar `config.yaml` (criticidades,
  pesos, umbral de crónico) — sin tocar código, con commit que narra el cambio.
- **Recalibración de pesos:** a partir de día 60, con etiquetas humanas
  acumuladas existe ground truth por primera vez — ahí es donde un split
  train/test tiene sentido (a diferencia de hoy, donde partir el dataset no
  mediría nada porque no hay verdad contra la cual validar).

---

## 6 · Fase 2 — diseñado, no implementado

Decisiones explícitas de **qué no se construyó y por qué**, con su ruta de
implementación futura:

- **Persistencia real de etiquetas (BigQuery/Firestore).** Hoy: exports
  manuales a `labels.csv`. La fusión de etiquetas históricas con corridas
  nuevas del pipeline (que regenera `panel.html` desde cero, D-?) es trabajo
  de esta fase.
- **Modo continuo/streaming.** El pipeline batch está diseñado para
  containerizarse trivialmente (sin estado, configuración externa en
  `config.yaml`, un solo entrypoint, degradación con `--no-llm`) y desplegarse
  como job calendarizado (Cloud Run Jobs / ECS Scheduled Tasks) — el mismo patrón ya usado en el proyecto Agentic WhatsApp. En streaming,
  además, la limitación de D-06 (`horas_tipicas` tautológica en batch) se
  resuelve naturalmente: el perfil se construye con ventana móvil y se evalúa
  contra alertas nuevas que el perfil nunca vio.
- **Panel v2 (diseño visual).** El panel actual es austero y funcional
  (autocontenido, sin CDN, abre con doble clic offline) — deliberado para el
  Definition of Done. Un rediseño visual (paleta de marca, jerarquía tipográfica,
  grupos crónicos colapsados por default) es mejora de UX, no de funcionalidad,
  y se aborda cuando el v1 esté en uso real.
- **Leave-one-out / split temporal para `horas_tipicas`** (D-06): solo
  relevante una vez que el sistema opera en streaming.
