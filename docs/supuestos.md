# Supuestos — ambigüedades resueltas

Cada entrada: el supuesto, por qué se tomó, y qué pasa si resulta incorrecto.
Donde aplica, referencia a la decisión técnica completa en `decisiones.md`.

---

## S-01 · "Período representativo" son dos ventanas disjuntas, no una

El JSON contiene tres exports concatenados: dos de `#sre` (26 may–11 jun 2025)
y uno de `#cx` (24–27 mar 2026) — casi un año de diferencia, sin solapamiento.
Se asume que cada canal tiene su propio "presente" y sus propias fichas de
recurrencia, sin intentar construir una línea de tiempo única (D-01).

**Si es incorrecto:** si en realidad hubiera continuidad temporal entre ambos
canales (ej. mismo período, exports separados por error), las fichas de
recurrencia de `#cx` estarían artificialmente vacías (solo 4 días de historia
vs los ~17 de `#sre`) — pero esto no afecta `#cx` porque esa vista no usa score
ni fichas (D-12).

---

## S-02 · El volumen real es ~21–38 alertas/día, no "cientos al día"

El brief describe "cientos de mensajes al día" en el canal. El JSON, en sus
~17 días efectivos de `#sre`, promedia 21 alertas/día (con picos de fin de
semana hasta ~64). Se asume que el JSON es una **muestra representativa** del
patrón (distribución por hora/día/servicio), aunque no del volumen absoluto
que describe el brief — quizá un período de menor actividad, o el brief
describe el estado agregado de *todos* los canales de monitoreo, no solo estos dos.

**Si es incorrecto** (el volumen real es 10x mayor): la arquitectura no cambia
— normalización, dedup, score y vistas operan igual sobre 4,580 alertas que
sobre 458. Lo que sí cambiaría es la justificación de D-05 (no usar z-scores):
con mayor n, un baseline estadístico por hora/servicio empieza a tener sentido,
y es exactamente la evolución que `gestion.md` §5 anticipa.

---

## S-03 · Las criticidades por servicio son inferidas, no confirmadas

`config.yaml` asigna criticidad a cada servicio agrupándolo por familia
(`pagos`, `nucleo`, `datos`, `infra`, `codename`, `web`) basándose en **qué
conditions dispara cada servicio** — no en conocimiento directo de qué hace
cada servicio en Parco. Servicios como `tesseract`, `Cerberus`, `Kraken` son
nombres clave internos sin contexto disponible.

**Si es incorrecto** (ej. `Cerberus` es en realidad un servicio crítico de
pagos, no "codename" genérico): el score de sus incidentes cambiaría con un
solo ajuste en `config.yaml` (cambiar su grupo de criticidad), sin tocar
código. Por esto `gestion.md` §3 marca esta tabla como **lo primero a validar
en semana 0** — es la superficie de mayor riesgo del sistema y la más barata
de corregir.

---

## S-04 · Las perillas (ventana de ráfaga, días de recurrencia, umbral de
crónico) son puntos de partida razonables, no SLAs medidos

`ventana_rafaga_minutos=30`, `recurrente_min_dias=3`, `cronico_min_incidentes=5`
se eligieron por ser razonables dado el tamaño del dataset (S-02) — no porque
reflejen, por ejemplo, cada cuánto Ops revisa Slack en la realidad.

**Si son incorrectas:** son las primeras candidatas a recalibración temprana
(antes incluso del día 60 de etiquetas, D-09) porque su efecto es observable
de inmediato — si Ops dice "nosotros revisamos cada 15 minutos, no cada 30",
la ventana se ajusta y se vuelve a correr el pipeline (D-14 confirma que esto
es seguro: regenera todo desde cero).

---

## S-05 · "Atendido" y "etiqueta" se llenan manualmente; no hay integración
con un sistema de tickets

Se asume que, en v0, Ops marca estas columnas directamente en `panel.html` y
exporta `labels.csv` periódicamente — sin integración con Jira, PagerDuty, o
similar.

**Si es incorrecto** (Parco ya tiene un sistema de tickets que registra
"atendido" automáticamente): sería una mejora de fase 2 — un adaptador que lea
el sistema de tickets y rellene estas columnas automáticamente, mismo patrón
que los adaptadores de `normalize.py` (D-02). No cambia el esquema de
`incidents.csv`, solo la fuente de las dos columnas finales.

---

## S-06 · El "ruido del 80%" del líder de soporte no se trata como instrucción

Las hipótesis internas mencionadas en el brief (umbral del 80%, ownership del
canal, patrones de fin de semana) se trataron como **contexto a verificar**,
no como restricciones de diseño. El resultado (D-07) ni confirma ni descarta
la hipótesis original — la refina: hay mucho ruido mecánico real (39.5%
redundancia dura), pero el número exacto depende de la definición, y una
definición demasiado amplia (89.5%) clasificaría como ignorable el KPI de
Payments y los 500s crónicos de Orchestrator.

**Si el equipo insiste en que "80% es ruido y debe ignorarse" como política**:
el sistema lo soporta — bastaría con definir una banda adicional o ajustar
umbrales para que ese 80% caiga en P3. Pero la recomendación documentada es
no hacerlo sin pasar por D-07 y D-13 primero, porque la consecuencia
(archivar el canal de pagos y los crónicos estructurales) probablemente no es
la intención real detrás de la cifra original.
