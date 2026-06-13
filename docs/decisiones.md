# Decisiones de diseño — parco-challenge pipeline

Qué se hizo, por qué, y qué se descartó. Cada entrada tiene contexto suficiente
para que alguien que no estuvo en la conversación entienda la decisión.

---

## D-01 · Reloj confiable por canal, no global

**Decisión:** en `sre` usar el campo `ts` (epoch); en `monitoring-ops-cx` usar
`timestamp` (ISO). Nunca un solo campo para ambos canales.

**Por qué:** el archivo `alerts_combined.json` concatena tres exports con
personalidades distintas. En los segmentos de sre el ISO tiene desfases erráticos
de −17h a +6h respecto al epoch — el ISO fue editado a mano o proviene de un
sistema con zona horaria mal configurada. En cx el epoch tiene gaps de exactamente
5.0 minutos (metrónomo, no tráfico humano: 95 × 5 min = 7.9 h), es sintético.
La regla operativa por canal produce el mismo resultado que la regla por índices
y además es robusta a datos nuevos.

**Qué se descartó:** usar un solo campo globalmente (rompe cx o sre), elegir por
índice (frágil a nuevos exports).

---

## D-02 · Fingerprint por exact-match, sin fuzzy ni LLM

**Decisión:** fingerprint = `(service_normalizado, condition)`. Los mensajes son
23 plantillas exactas — basta con exact-match.

**Por qué:** el análisis exploratorio (EDA §4) reveló que `condition → policy`
es una relación 1-a-1 perfecta y los 23 valores son strings idénticos entre
registros. No hay variación ortográfica en `condition`. Usar fuzzy matching,
embeddings o un LLM para agrupar pagaría un costo enorme por un problema que
no existe.

**Qué se descartó:** clustering semántico, embeddings, clasificación con LLM
para agrupar conditions.

---

## D-03 · Agrupación interna de infra por instancia, no por grupo

**Decisión:** la clave interna de agrupación (`_fp_key`) usa `service_original`
para instancias infra (`service == 'infra'`) y `service` normalizado para el
resto.

**Por qué:** los servicios `i-XXXX` y `new-parco-instance-*` son instancias EC2
distintas con patrones de carga independientes. Agruparlos todos como "infra"
mezclaría sus fichas de recurrencia: una instancia con 8 días de historial
absorbería el historial de otra con 2 días, borrando la señal de novedad de
esta última. La separación produce que `i-0d26dd` tenga `dias_visto=2` (< 3)
→ `s_ficha=0.9` → P2, que es el resultado esperado (EDA §9).

**Qué se descartó:** agrupar todas las instancias bajo el fingerprint
`infra::condition`, que habría inflado artificialmente `dias_visto`.

---

## D-04 · s_intensidad: distinción estatica/anomalia en el componente, no en boost

**Decisión:** `s_intensidad` tiene cuatro valores: `null=0.30`, `high=0.50`,
`critical_estatica=0.75`, `critical_anomalia=1.00`. No existe boost separado
para alertas de tipo anomalía.

**Por qué:** una versión anterior tenía `s_intensidad=0.75` para todo `critical`
más un boost `regla_anomalia_newrelic=+0.10`. Eso generaba double-counting: la
señal de anomalía contaba dos veces (una como `critical`, otra como bonus).
La distinción `0.75 vs 1.00` captura la diferencia sin solapamiento: un umbral
estático mide distancia al límite (puede ser el comportamiento esperado cruzando
su umbral nocturno); un umbral baseline certifica que New Relic comparó contra
el comportamiento aprendido del servicio y lo encontró anómalo.

**Por qué 0.75 y no 1.0 para critical+estática:** el caso canónico es data-team
RDS CPU a las ~02h. La base de datos cruza su umbral crítico casi cada noche con
el ETL nocturno. Darle 1.0 lo elevaría artificialmente a P2; con 0.75 y
`s_ficha=0.0` (completamente habitual) aterriza en P3 (~36), que es el veredicto
correcto.

**Qué se descartó:** boost separado por tipo de regla (double-counting).

---

## D-05 · No usar z-scores en las fichas de recurrencia

**Decisión:** las fichas usan valores absolutos (días vistos, conjunto de horas,
mediana de n_alertas), no z-scores ni distancias estadísticas.

**Por qué:** n=458 alertas, de las cuales el fingerprint más frecuente
(Orchestrator) tiene 45 incidentes. La mayoría tienen menos de 10. Con n tan
pequeño, la desviación estándar es inestable y un z-score produciría bandas de
confianza sin respaldo estadístico real. La documentación dice explícitamente:
"NO usar z-scores: n=458 no lo sostiene."

**Qué se descartó:** distancia en desviaciones estándar para horas_tipicas
(ver también D-06), percentiles de rafaga_tipica.

---

## D-06 · Limitación conocida: horas_tipicas es tautológica en modo batch

**Decisión:** documentar como deuda técnica, no corregir en v0.

**El problema:** `horas_tipicas` se construye como el conjunto de horas exactas
de inicio de todos los incidentes del fingerprint en el período histórico:

```python
horas = sorted({dt.hour for dt in inicio_series})
```

Luego `_s_ficha` pregunta si la hora del incidente está en ese conjunto. Como
el incidente ES uno de los que construyó el conjunto, la condición es siempre
verdadera: la rama `s_ficha=0.6` (hora atípica) nunca se activa en datos
históricos. Verificado: **0 de 277 incidentes reciben s_ficha=0.6**.

**Por qué no corregir en v0:** este pipeline procesa un snapshot histórico fijo.
La rama 0.6 tiene sentido en producción streaming (el perfil se construye con
las últimas N semanas; una alerta nueva a una hora nunca vista activa 0.6). Ese
modo de operación está diseñado en `gestion.md` como fase 2 con n8n.

**Alternativa evaluada y descartada — promedio ± 1 desviación estándar:**
se consideró construir `horas_tipicas` como el rango `[mean_hora - std, mean_hora + std]`
en lugar de un conjunto de valores exactos. Se descartó por tres razones:
1. **Las horas son datos circulares.** La media aritmética de {23, 1} da 12
   (mediodía), no 0 (medianoche). El tratamiento correcto requiere estadística
   circular (media de Von Mises), que es significativamente más compleja y con
   n pequeño es inestable. Mismo problema que D-05.
2. **La mayoría de fingerprints son multimodales.** data-team dispara a las
   {2, 9, 13, 15, 22} — cinco clusters distintos. El promedio (~12h) con std
   (~7h) produciría un rango [5h, 19h] que cubre la mayor parte del día laboral
   y haría el chequeo casi vacío. Orchestrator (9h–22h) tendría incidentes a
   las 9h y 22h fuera de su propio rango, aunque son perfectamente habituales.
3. **No resuelve la tautología en batch.** Los incidentes que construyeron el
   promedio casi siempre caen dentro de su propio ±1 std. Solo se desplaza el
   problema un nivel más abajo.

**Lo que sí funciona en batch:** la rama `0.0 vs 0.1` sobre `rafaga_tipica`
(mediana de n_alertas). El tamaño de una ráfaga específica puede genuinamente
superar la mediana del conjunto — ese chequeo tiene valor real incluso con datos
históricos.

**Corrección para producción:** leave-one-out (excluir el incidente a scorar de
su propio perfil) o split temporal (perfil con primera mitad del período, score
con segunda mitad). Ambas opciones son válidas cuando el pipeline pase a modo
streaming.

---

## D-07 · Veredicto del "80% es ruido": la definición importa más que el número

**Decisión:** reportar dos métricas con definiciones explícitas, no un solo "% de ruido".

- **Redundancia dura (40%):** alertas en ráfagas que el dedup colapsa mecánicamente.
  Defendible sin supuestos: diez gritos del mismo fuego en 30 minutos = un incidente.
- **Definición ingenua (89%):** ráfagas + fingerprints recurrentes. Numéricamente
  valida la hipótesis interna de "80% es ruido", pero operativamente sería un
  desastre: archivaría los rechazos de pago en #sre y los 500s crónicos de
  Orchestrator.

**Por qué:** la definición de "ruido" determina el número, no al revés. Publicar
un solo porcentaje sin definición produce el número que confirma cualquier hipótesis
previa. El error del análisis original no fue la muestra del día atípico: fue no
definir "ruido" antes de contarlo.

**Qué se descartó:** un solo "% de ruido" global sin definición explícita.

---

## D-08 · LLM solo en la narrativa del digest, no en clasificación ni agrupación

**Decisión:** Gemini 2.5 Flash recibe la tabla de incidentes ya calculada y narra;
no clasifica, no agrupa, no calcula números.

**Por qué:** las 23 conditions son plantillas exactas (D-02). Clasificar plantillas
con un LLM pagaría latencia, costo y variabilidad por un problema que no existe.
Los números del digest se inyectan del CSV; el modelo completa la narrativa en
≤25 palabras por ítem. Con `--no-llm` (o sin `GEMINI_API_KEY`) el digest sale de
una plantilla determinista y sigue siendo válido.

**Qué se descartó:** clasificación de conditions con LLM, agrupación semántica
de servicios, generación de los números del digest por el modelo.

## D-09 · Fórmula del score: suma ponderada configurable, no un modelo entrenado

**Decisión:** el score es una combinación lineal de cinco componentes en [0,1],
cada uno con un peso fijo en `config.yaml`:

```
score = 100 × ( 0.30·s_criticidad + 0.25·s_ficha + 0.20·s_rafaga
              + 0.15·s_intensidad + 0.10·s_novedad )
```

Bandas: P1 >= 70 ("Atiende ahora"), P2 40-69 ("Revisa hoy"), P3 < 40
("Informativo, no requiere acción").

**Por qué:** no existe ground truth (ninguna alerta viene etiquetada como
"importante" o "ruido"), así que entrenar un modelo no es posible ni honesto en
v0. Una suma ponderada con pesos heurísticos y *declarados* tiene tres ventajas
sobre un modelo opaco: es auditable componente por componente (cada incidente
expone sus 5 valores `s_*` en `incidents.csv`), es ajustable por Ops sin tocar
código (los pesos viven en `config.yaml`), y es el mismo patrón que un score
crediticio — muchas variables, pesos declarados, traduce información técnica a
una decisión operativa.

**Los pesos v0 (0.30/0.25/0.20/0.15/0.10) son heurísticos, no derivados de datos.**
Reflejan un juicio de producto: "qué tan grave es el servicio" pesa más que
"qué tan fuerte gritó la alerta ahora", porque la criticidad cambia poco y la
intensidad nativa de New Relic es ruidosa (ver D-04). Se recalibran con las
etiquetas humanas (`atendido`/`etiqueta` en el panel) a partir de 60-90 días de
uso — momento en que sí existe ground truth y un ajuste de pesos por validación
(ahí sí aplica un split tipo train/test, ver `gestion.md`).

**Qué se descartó:** un modelo de ML entrenado sobre el histórico (sin etiquetas,
habría memorizado ruido); pesos iguales para los 5 componentes (trataría
"es la primera vez que se ve esto" igual de fuerte que "es el servicio de pagos",
lo cual no refleja el criterio de Ops).

---

## D-10 · Cuando el diseño contradice el número esperado, se corrige el diseño primero

**Decisión:** los cuatro casos canónicos del EDA (§9) son *sanity checks de diseño*,
no objetivos a alcanzar. Si una implementación coherente produce un resultado
distinto al esperado, se documenta el resultado nuevo con su razón — no se ajusta
el mecanismo hasta que el número viejo "salga".

**Por qué surgió esta regla:** en una iteración intermedia, dos ajustes se
introdujeron específicamente para que `data-team::RDS CPU ~02h` cayera en P3 y
`i-0d26dd::Parco 2.0 Nodes CPU` cayera en P2 — los valores que el EDA preliminar
había anotado a mano. El primer ajuste asignaba `s_intensidad=1.0` para todo
`critical` y luego restaba un boost ad-hoc para que data-team no subiera de P3;
el segundo cambiaba el nivel de agregación de las fichas de "por flota" (decidido
y documentado en una capa anterior) a "por instancia" — con la justificación
explícita de que así i-0d26dd subía a P2. Ambos cambios resolvían la pregunta
"¿cómo hago que el número coincida con la respuesta esperada?" en lugar de
"¿qué es correcto?" — exactamente el patrón que la ley de Goodhart describe:
cuando una medida (el caso canónico) se convierte en el objetivo, deja de
servir como medida.

**La corrección aplicada:** se separaron las dos responsabilidades que se habían
mezclado. `s_intensidad` mide la fuerza de la señal de origen (D-04: 0.75 vs 1.0
según tipo de regla, sin boost duplicado). `s_ficha` mide exclusivamente si el
comportamiento es habitual (D-06). La agregación de fichas volvió a ser por
identidad consistente con la llave de `dedupe` (D-03), una sola historia de
diseño en todo el repo.

**Resultado tras la corrección — el EDA §9 se reconcilió con la realidad, no al
revés:**

| Caso | Antes (ajustado) | Después (coherente) |
|---|---|---|
| Hairs · Payments rejected (sre) | 73 · P1 | 73 · P1 (sin cambio) |
| tesseract · High App Error % | 76 · P1 | 68 · P2 — bajó al eliminar el double-count de la anomalía |
| i-0d26dd · Nodes CPU Usage | 64 · P2 | 64 · P2 (sin cambio) |
| data-team · RDS CPU ~02h | 39 · P3 | 36 · P3 (sin cambio de banda) |

tesseract cambiando de P1 a P2 no se "arregló" después — es el resultado correcto
de un score coherente, y se mantiene. Es un caso frontera (68, dos puntos bajo el
corte de P1) consistente con la idea de que los casos frontera son los que las
etiquetas humanas terminan de calibrar.

**Qué se descartó:** mantener los ajustes ad-hoc para preservar los 4 valores
originales del EDA; tratar el EDA §9 como inmutable.

---

## D-11 · Normalización de identidad (siempre) vs agrupación semántica (según propósito)

**Decisión:** existen dos tipos de normalización de `service`, con reglas distintas:

1. **Corrección de identidad** (typos): `Princes → Princess`. Se aplica en TODA
   parte del pipeline donde `service` se usa como llave — incluida la llave
   interna de `dedupe` (`_fp_key`). Razón: son la misma entidad, mal escrita.
2. **Agrupación semántica por clase**: instancias EC2 (`i-XXXX`, `new-parco-instance-*`)
   se exponen como `service = "infra"` en `incidents.csv` para vistas y reportes
   agregados, pero **no** en la llave interna de `dedupe`/`profiles` (D-03):
   ahí cada instancia conserva su `service_original`. Razón: son entidades
   distintas de la misma clase; agruparlas mezclaría sus historiales individuales.

**Por qué se documenta como principio aparte:** la llave de `dedupe` originalmente
usaba `service_original` sin corrección de typos. Un test sintético
(`test_typo_corrected_service_merges_in_window`) verificó que si una alerta de
`Princes` y una de `Princess` con la misma `condition` cayeran dentro de la
ventana de 30 min, debían colapsar en un solo incidente — y con la llave sin
corregir, no lo harían. En los datos actuales esto no cambia el conteo de 277
(la única alerta de `Princes` tiene una `condition` que ninguna alerta de
`Princess` comparte), pero el principio queda blindado para datos futuros sin
tocar código: si llega un `Princes` con una condition que Princess ya tiene,
se agrupará correctamente.

**La regla general, reutilizable:** *la identidad se corrige siempre porque es
la misma entidad; la clase se agrupa solo donde el propósito de la vista lo
requiere, preservando identidad en las capas que construyen historial.*

**Qué se descartó:** usar `service_original` sin corrección como llave universal
(fragmenta entidades idénticas mal escritas); aplicar la agrupación "infra" también
en `dedupe`/`profiles` (D-03, mezclaría historiales de instancias distintas).

---

## D-12 · Dos vistas porque son dos preguntas de producto, no dos formatos de dato

**Decisión:** `#sre` se presenta como **triage** (incidentes individuales,
score, banda, ordenados por prioridad). `#monitoring-ops-cx` se presenta como
**composición** (agregación por `error_type` y `procesador`, sin score ni banda
operativa).

**Por qué:** las 95 alertas de cx son, en esencia, **una sola "enfermedad"**
(rechazo de pago) con 4 variantes (`error_type`). Priorizar entre rechazos de
pago individuales no tiene sentido operativo — nadie "atiende" un
`INSUFFICIENT_FUNDS` aislado. La pregunta útil sobre cx es de composición: ¿qué
porcentaje de los rechazos son por fondos insuficientes (29.5%, el KPI de
Payments)? ¿qué procesador concentra más rechazos? ¿cómo cambia el día a día?

La analogía que sostiene esta decisión: `#sre` es la sala de urgencias (cada
paciente es un caso distinto, hay que ordenarlos por gravedad — eso es triage).
`#cx` es el reporte epidemiológico del director del hospital (no importa el
orden de la fila de hoy, importa de qué se enferma la población y cómo cambia
la mezcla con el tiempo).

Una sola fuente de verdad (`incidents.csv`) alimenta ambas vistas — `views.py`
separa por `channel` y aplica la agregación correspondiente. La columna `score`
existe también para los incidentes de cx (no se computa selectivamente), pero
la vista de composición no la usa como criterio de orden porque no responde la
pregunta que esa vista hace.

**Qué se descartó:** aplicar triage (score + banda como criterio principal) a
cx, lo que habría producido 95 registros casi idénticos rankeados entre sí sin
información operativa nueva — y habría escondido la pregunta real (composición,
tendencia, KPI de Payments) detrás de un ranking sin sentido.

---

## D-13 · Los crónicos activos se presentan como hallazgo de producto, no se ocultan bajando umbrales

**Decisión:** tras el diagnóstico de la distribución de bandas (P1=6%, P2=63%,
P3=31%), no se modificaron pesos ni umbrales. En cambio, `views.py` agrega
`vista_patrones`: agrupación por fingerprint con `n_incidentes`, `score_medio`
y primera/última aparición. Un fingerprint con `es_recurrente=True` y
`n_incidentes >= cronico_min_incidentes` (config, default 5) se marca como
"crónico activo" y se presenta colapsado en el panel y resumido en el digest.

**Por qué:** el diagnóstico mostró que el 63% en P2 no es ruido de calibración —
es un cluster compacto y nombrable: 55 de los 175 incidentes P2 (31%) son dos
`conditions` de `Orchestrator` (errores 500 crónicos), con `s_ficha≈0.0`
(comportamiento totalmente habitual) y `s_novedad=0.0`. El score está
funcionando como se diseñó: criticidad alta (Orchestrator es el coordinador
central) + completamente habitual + intensidad `critical` = "importante pero
no es una emergencia, y ocurre todos los días". Mover el umbral P2/P3 de 40 a,
digamos, 50 para "desinflar" la banda habría reclasificado los 500s crónicos de
Orchestrator como P3 ("informativo, no requiere acción") — exactamente el error
operativo que el brief advierte: tratar lo recurrente como ignorable cuando es
estructural.

Además, los valles del histograma de scores **validan** los umbrales actuales
sin haber sido diseñados para eso: el corte 40 cae en un anti-pico natural
(solo 2 incidentes en 40-41); P1 al 6% es una banda sana.

El problema real era de **presentación**, no de matemáticas: 42 episodios del
mismo crónico no deben verse como 42 renglones idénticos de "revisa hoy" — deben
verse como un expediente con su historial. Es la tercera etapa de compresión
(458 alertas → 277 incidentes → patrones): lo agudo se triagea por episodio, lo
crónico se gestiona por caso, como el expediente de un paciente con una
condición crónica frente a una visita de urgencias.

**Qué se descartó:** subir el umbral P2/P3 para reducir el tamaño visual de P2
(reclasificaría problemas estructurales como ignorables); ocultar o eliminar
los incidentes recurrentes de la vista (perdería la trazabilidad de episodios
individuales, que sigue existiendo en `incidents.csv`).