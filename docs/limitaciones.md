# Limitaciones del proyecto

Documento honesto de lo que el pipeline NO hace, NO puede garantizar, o hace
de forma incompleta. Está escrito para que quien reciba este proyecto sepa
exactamente dónde están los bordes antes de desplegarlo.

Cada limitación incluye su impacto operativo real y, donde existe, la ruta
de resolución documentada.

---

## L-01 · La rama "hora atípica" del score nunca se activa en modo batch

**Qué pasa:** `s_ficha` tiene cuatro ramas: 0.9 (sin historial), 0.6 (hora
atípica), 0.1 (hora normal pero ráfaga mayor) y 0.0 (completamente habitual).
La rama 0.6 requiere que la hora de inicio del incidente no esté en
`horas_tipicas`. Pero `horas_tipicas` se construye como el conjunto exacto de
horas de todos los incidentes del fingerprint en el mismo histórico que se
scorea — por construcción, toda hora observada ya está en el conjunto.
Resultado verificado: **0 de 277 incidentes reciben s_ficha=0.6**.

**Impacto:** el componente de "hora atípica" no discrimina en datos históricos.
El score diferencia entre "sin historial" (0.9), "ráfaga mayor a lo habitual"
(0.1) y "completamente habitual" (0.0), pero no detecta desvíos de horario
en batch.

**Por qué no se corrigió en v0:** el pipeline procesa un snapshot fijo. La rama
0.6 tiene sentido en producción streaming: el perfil se construye con las
últimas N semanas y una alerta nueva a una hora nunca vista activa 0.6. Ese
modo está diseñado en `gestion.md` como fase 2 con n8n.

**Ruta de resolución:** leave-one-out (excluir el incidente a scorar de su
propio perfil) o split temporal al pasar a streaming. Ver `decisiones.md` D-06.

---

## L-02 · Los pesos del score son heurísticos sin ground truth

**Qué pasa:** los pesos (0.30 / 0.25 / 0.20 / 0.15 / 0.10) reflejan un juicio
de producto, no una optimización sobre datos etiquetados. No existe ninguna
alerta histórica con etiqueta "ameritaba / ruido" contra la cual validarlos.

**Impacto:** el score es auditable y transparente, pero no está demostrado que
sus pesos minimicen falsos positivos o falsos negativos. Puede ser que
`s_criticidad` deba pesar 0.40 y `s_rafaga` solo 0.10 — no hay forma de
saberlo sin etiquetas.

**Ruta de resolución:** el panel incluye las columnas `atendido` y `etiqueta`
precisamente para acumular ground truth. A los 60-90 días de uso, con suficientes
etiquetas, se puede hacer una regresión logística o ajuste de pesos por
validación cruzada. Ver `gestion.md`.

---

## L-03 · La tabla de criticidad de servicios no está validada con el equipo

**Qué pasa:** los grupos de criticidad (`pagos`, `nucleo`, `datos`, `infra`,
`codename`, `web`) y sus valores (1.0, 0.8, 0.6, 0.5, 0.7, 0.4) son inferidos
del dato — de qué alertas disparan cada servicio, con qué frecuencia, y el
nombre del servicio. No fueron confirmados por el equipo de Parco.

**Impacto:** si `tesseract` es en realidad un servicio crítico de pagos (no un
codename de baja criticidad), su score está subestimado. Si `Chargehound` es
menos crítico de lo que parece (aunque sea de PayPal), está sobreestimado.

**Ruta de resolución:** semana 0 del despliegue: revisar la tabla
`criticidad_servicios` en `config.yaml` con el equipo técnico de Parco. Es el
único paso que requiere contexto interno que este proyecto no puede tener.

---

## L-04 · n=458 con dos períodos disjuntos limita la robustez estadística

**Qué pasa:** el dataset tiene 458 alertas en dos ventanas temporales que no se
solapan: sre en mayo-junio 2025 y cx en marzo 2026. Las fichas de recurrencia
de sre se construyen con ~15 días de datos; las de cx con 4 días.

**Impacto:** fingerprints con pocas apariciones tienen fichas inestables. Un
servicio que falla una vez cada dos semanas puede tener `dias_visto=1` en este
período y recibir `s_ficha=0.9` por siempre, aunque tenga meses de historial
en producción. Las medianas de `rafaga_tipica` con n=2 o n=3 son orientativas,
no estadísticamente robustas.

**Ruta de resolución:** en producción, el perfil se construye con un ventana
deslizante de 30-90 días de datos reales. Con más volumen, las fichas convergen.

---

## L-05 · `null → 1` en la columna `incidents` es una imputación no verificada

**Qué pasa:** la columna `incidents` de New Relic (cuántos disparos reales
empaquetó en una notificación) es null en 3 registros. Se imputa como 1 —
asumiendo que si no se indica, es un disparo único.

**Impacto:** la suma total de `n_disparos` puede estar subestimada en hasta 3
disparos. Para los 3 registros afectados (PayPal Status, que no vienen de New
Relic), el campo `incidents` no tiene el mismo significado de todas formas —
la imputación es razonable pero no verificable.

---

## L-06 · El score es una suma lineal que asume independencia de componentes

**Qué pasa:** `score = Σ wᵢ · sᵢ`. Esto asume que los cinco componentes
aportan información independiente. En la práctica hay correlaciones: un
fingerprint nuevo (`s_novedad` alto) tiende también a tener poca ficha
(`s_ficha` alto), lo que puede inflar el score de primerías de forma
acumulada.

**Impacto:** incidentes que son genuinamente nuevos Y sin historial reciben el
doble del boost de "desconocido". Todos los P1 del dataset actual tienen
`s_ficha=0.9` — es decir, la señal que lleva incidentes a P1 es casi
exclusivamente la combinación novedad + sin historial + criticidad del servicio.

**Ruta de resolución:** cuando existan etiquetas, evaluar si una interacción
entre componentes (ej. penalizar cuando `s_ficha` y `s_novedad` son ambos
altos al mismo tiempo) mejora la precisión. Cambio de arquitectura del score,
no un ajuste de pesos.

---

## L-07 · El digest agrupa por fingerprint solo en la presentación

**Qué pasa:** si el mismo fingerprint genera N incidentes P1 en el período,
el digest los muestra como una sola entrada con "N episodios". Pero el score
de cada incidente individual en `incidents.csv` no cambia — cada uno sigue
siendo un incidente independiente con su propio timestamp, duración y score.

**Impacto:** la agrupación del digest puede esconder que un servicio tuvo
episodios en momentos muy distintos del período (ej. lunes y viernes). El
panel de triage sigue mostrando todos los incidentes individuales, que es
donde se opera.

---

## L-08 · El panel no tiene persistencia real

**Qué pasa:** las columnas `atendido` y `etiqueta` del panel viven en memoria
de la página. Si el usuario cierra el navegador sin exportar, los datos se
pierden. La exportación a `labels.csv` es manual.

**Impacto:** la métrica norte (tiempo crítico → atención) no es medible
automáticamente. El pipeline de recalibración con etiquetas requiere que alguien
exporte `labels.csv` y lo procese manualmente.

**Ruta de resolución:** fase 2 en `gestion.md`: persistencia en BigQuery o
Firestore, alimentada desde el panel o desde una integración de Slack.

---

## L-09 · Los crónicos se identifican por umbral fijo, no por tendencia

**Qué pasa:** un fingerprint es "crónico" si `es_recurrente=True` AND
`n_incidentes >= 5` en el período. El umbral 5 es arbitrario y no captura
si el problema está mejorando, empeorando o estable.

**Impacto:** un fingerprint con 5 episodios todos en la primera semana y
ninguno después se trata igual que uno con 5 episodios distribuidos
uniformemente. Un fingerprint con 4 episodios pero tendencia creciente no
aparece como crónico.

**Ruta de resolución:** con más datos históricos, añadir tendencia (regresión
lineal sobre frecuencia por semana) como dimensión adicional de la vista
`vista_patrones`.

---

## L-10 · La separación de períodos sre/cx impide comparar entre canales

**Qué pasa:** sre cubre mayo-junio 2025; cx cubre marzo 2026. Son períodos
disjuntos. Las fichas de recurrencia se calculan por canal (nunca se mezclan),
y los scores no son comparables entre canales porque los patrones de carga
son distintos.

**Impacto:** no se puede responder "¿los rechazos de pago de cx están
correlacionados con los errores de sre?". La correlación temporal entre
canales requeriría datos del mismo período, que este dataset no tiene.

---

## L-11 · PayPal Status y registros sin `priority` asumen s_intensidad=0.30

**Qué pasa:** los 3 registros de PayPal Status no vienen de New Relic y no
tienen campo `priority`. Se les asigna `s_intensidad=0.30` (el valor `null`
del config). Su estado viene en el texto de `condition` ("- INITIAL" /
"- RESOLVED"), no en un campo estructurado de prioridad.

**Impacto:** un aviso de "Intermittent Disruption - INITIAL" de Chargehound
(procesador de pagos de PayPal) recibe el mismo tratamiento de intensidad que
un aviso administrativo. En el dataset actual llegan a P1 por `s_novedad`
y `s_criticidad` altos — no por intensidad. Si PayPal Status enviara avisos
rutinarios frecuentes, el score necesitaría un adaptador más específico.

---

## L-12 · El modo `--no-llm` produce un digest sin narrativa contextual

**Qué pasa:** sin `GEMINI_API_KEY` o con `--no-llm`, el digest sale de
plantillas deterministas. Las líneas de P1 tienen solo la `explicacion` por
reglas (ej. "Primera vez que se observa este comportamiento en Invoice"),
sin el contexto adicional que Gemini añadiría.

**Impacto:** el digest es válido y legible, pero es una lista de hechos, no
una narrativa. Para el lunes por la mañana en producción, el modo sin LLM
es suficiente para la acción; para una presentación o un reporte ejecutivo,
el modo con LLM aporta más valor.

---

## Resumen de impacto operativo

| Limitación | Impacto en producción | Prioridad de resolución |
|---|---|---|
| L-01 · hora atípica inactiva en batch | Bajo — se activa en streaming | Al pasar a fase 2 |
| L-02 · pesos sin ground truth | Medio — el score puede estar mal calibrado | 60-90 días de uso |
| L-03 · criticidades no validadas | Alto — afecta scores de todos los servicios | Semana 0 |
| L-04 · n pequeño / períodos cortos | Medio — fichas inestables para fingerprints raros | Se resuelve con más datos |
| L-05 · null→1 en incidents | Muy bajo — 3 registros afectados | No prioritario |
| L-06 · score lineal, componentes correlacionados | Medio — P1 sesgado hacia "primeras veces" | Post-etiquetas |
| L-07 · digest agrupa, CSV no | Bajo — es comportamiento esperado y documentado | N/A |
| L-08 · panel sin persistencia | Alto — métrica norte no medible | Fase 2 |
| L-09 · crónico por umbral fijo | Bajo — funciona para v0 | Post-etiquetas |
| L-10 · períodos disjuntos sre/cx | Bajo — limitación del dataset de entrada | Requiere nuevos datos |
| L-11 · PayPal sin priority | Bajo — 3 registros, adaptador específico | Si aumentan los avisos |
| L-12 · digest sin LLM es lista plana | Bajo — válido y accionable | N/A |
