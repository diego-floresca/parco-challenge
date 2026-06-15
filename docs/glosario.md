# Glosario — el diccionario que nunca nos dieron

> Escrito para que cualquier persona — de Ops, de Tech, o sin contexto previo —
> entienda cada concepto con su analogía. Si un concepto no se puede explicar
> con peras y manzanas, no está listo para presentarse.

## 1 · El problema en una frase

Un canal de Slack recibe cientos de alertas crudas, sin estructura ni
prioridad; nadie puede leerlas todas, y lo crítico se descubre tarde **no
porque el sistema no avise, sino porque la señal queda sepultada bajo el
ruido**. La solución no es mostrar más datos: es procesar los que ya existen
para que alguien abra el output un lunes por la mañana y sepa, en menos de dos
minutos, qué merece su atención.

---

## 2 · Anatomía de una alerta: los 12 campos nativos

| Campo | Qué cuenta | Analogía | Rol en la solución |
|---|---|---|---|
| `ts` | Reloj epoch: segundos desde el 1 de enero de 1970 | El odómetro del coche: un contador, ilegible para humanos, preciso para máquinas | Tiempo confiable en `#sre` (D-01) |
| `timestamp` | La misma hora en formato ISO 8601 (legible, con zona horaria) | La fecha escrita a mano atrás de una foto | Tiempo confiable en `#cx` (D-01) |
| `channel` | A qué canal de Slack llegó: `sre` o `monitoring-ops-cx` | El buzón al que llegó la carta | Router maestro: decide la vista (D-12) y qué reloj creer |
| `source` | Qué sistema generó la alerta: New Relic (455) o PayPal Status (3) | El remitente de la carta | Llave del patrón de adaptadores |
| `service` | El servicio afectado (28 valores) | El órgano del cuerpo que duele | Entrada a la criticidad del score, previa normalización (D-11) |
| `condition` | La plantilla del problema (23 únicas) | El diagnóstico estándar del doctor | Mitad de la identidad del incidente (fingerprint, D-02) |
| `priority` | `high` o `critical`, asignado por New Relic | El tono de voz del que grita | Componente de `s_intensidad` (D-04) |
| `threshold` | La regla exacta que disparó: operador + valor + unidad / ventana | La línea roja del termómetro que se cruzó | Tres derivados: tipo de regla, dirección, ventana |
| `policy` | La carpeta de New Relic que agrupa conditions relacionadas | Las materias de una boleta | Metadata de agrupación; determina el canal |
| `error_type` | Código estructurado del rechazo de pago (solo en `#cx`) | El código de diagnóstico en la receta médica | Dimensión principal de la vista composición y del KPI de Payments |
| `error_message` | Descripción humana del rechazo, en español, con pistas extra | La explicación del doctor en palabras | De aquí se extrae el `procesador` (Conekta, Mercadopago, PayPal) |
| `incidents` | Cuántos disparos reales empaquetó New Relic en esta notificación | Una llamada que dice "te hablé 7 veces" | Suma a `n_disparos` |

**Sobre `sre`:** no es un término técnico del dato — es el nombre del canal de
Slack. SRE = *Site Reliability Engineering*, la disciplina (de Google) del
equipo que mantiene los sistemas vivos. `#sre` es donde gritan las máquinas;
`#monitoring-ops-cx` (CX = *customer experience*) es donde gritan los clientes.

---

## 3 · La jerarquía oculta entre columnas

```
channel  <-  policy  <-  condition  <-  service
  (2)         (5)         (23)          (28)
```

- **policy → channel es partición perfecta:** Golden Signals (254), Parco2.0
  strict (95), Up_Satatus_Parco (11) y None (3) viven 100% en `#sre`; CX (95)
  vive 100% en `#cx`.
- **condition → policy es 1 a 1** en las 23 conditions.
- **service ↔ condition es muchos-a-muchos con personalidad:** cada servicio
  tiene su repertorio corto de males — Orchestrator solo falla con errores 500,
  data-team solo alerta por CPU de base de datos.

---

## 4 · Diccionario de valores reales

### 4.1 Policies

| Policy | Alertas | Qué es |
|---|---|---|
| Golden Signals | 254 | Canon de SRE (de Google): latencia, tráfico, errores, saturación — los cuatro signos vitales de un sistema, como pulso, presión, temperatura y respiración |
| Parco2.0 strict | 95 | Reglas estrictas de la plataforma Parco 2.0 |
| CX | 95 | Reglas de experiencia de cliente: rechazos de pago |
| Up_Satatus_Parco | 11 | Disponibilidad / uptime (typo de origen: "Satatus") |
| None | 3 | Avisos de la página de estado de PayPal — no nacen de New Relic, por eso no traen carpeta |

### 4.2 Services (28, agrupados — criticidades inferidas, ver S-03)

| Grupo | Services (conteo) | Inferencia |
|---|---|---|
| Pagos | Hairs (124), Wallet_2.0 (31), Transaction query (12), Chargehound (2), PayPal (1), Invoice (1) | Hairs dispara "Payments rejected" → es el servicio de pagos. Wallet = monedero. Chargehound = disputas de contracargos, propiedad de PayPal desde 2021 |
| Núcleo de producto | Orchestrator (104), Carts (28), Users (26), Access (6), Peajero (2) | Orquestador central, carritos, usuarios, accesos; "Peajero" sugiere peajes — el corazón de una app de movilidad |
| Nombres clave | tesseract (29), Cerberus (20), Princess (12), Kraken (5), demo2 (4), Gigante (3), data-team (7) | Microservicios internos; criticidad por confirmar con el equipo (S-03) |
| Infraestructura | 6 hosts EC2 (i-058689..., i-0d26dd..., i-04acba..., i-0d568d..., new-parco-instance-1/5) | "i-XXXX" = número de serie de un servidor en AWS. Se agrupan como "infra" en vistas, conservando identidad individual en dedup (D-03, D-11) |
| Web | Wiki (9), Wordpress web page (1), Web Page Parco (1) | Sitios y páginas |

### 4.3 Conditions (las 23, traducidas)

| Condition (conteo) | Traducción |
|---|---|
| Payments rejected hairs CX (95) | Rechazos de pago de clientes — regla: 5+ en 5 min. Canal CX |
| high request count with status 500 (91) | Muchas peticiones terminando en error 500: el mesero regresa diciendo "la cocina tronó" |
| Throughput high general (58) | *Throughput* = volumen de tráfico. Alto = mucha demanda — puede ser éxito o problema |
| High Application Error percentage (44) | El % de peticiones que fallan subió — detectado por la regla de anomalías de New Relic |
| Status code 500 counted request (31) | Variante contadora de los errores 500 (Wallet_2.0) |
| Parco 2.0 Nodes CPU Usage (23) | CPU de los servidores de la plataforma 2.0 al límite |
| RDS CPU Usage gral (19) | CPU de la base de datos al límite (RDS = base de datos administrada de AWS) |
| Carts Throughput high (17) | Tráfico alto en carritos |
| global traffic alert (12) | Tráfico total de la plataforma anómalo |
| High Application Response Time gral (11) | *Latencia*: la app tarda en contestar |
| Apdex score (11) | Índice 0–1 de satisfacción del usuario (rápidas + lentas + fallidas) |
| Cerberus Throughput High (11) | Tráfico alto en Cerberus |
| Parco APIs status - locations failed (11) | Robots de New Relic en el mundo no logran acceder a las APIs |
| Low Application Throughput (9) | Tráfico DESPLOMADO — degradación silenciosa: nadie llega al restaurante |
| Payments rejected hairs (4) | Variante rara: rechazos reportados en `#sre` en vez de `#cx` |
| SMS Alert (4) | Problemas enviando SMS (Users) |
| Intermittent Disruption INITIAL/RESOLVED (2) | Página de estado de PayPal sobre Chargehound: "tenemos intermitencia" / "ya se resolvió" |
| Scheduled Maintenance, External Scan Alert, login alert, High response time, Error percentage high (1 c/u) | Apariciones únicas |

### 4.4 Thresholds (operador + valor + unidad / ventana)

| Ejemplo | Descripción |
|---|---|
| `>55/5min` | Más de 55 eventos en 5 minutos |
| `>1800ms/5min` | Respuestas tardando más de 1.8 segundos, 5 minutos sostenido |
| `baseline/10min` | New Relic comparó contra el comportamiento histórico propio — su detector de anomalías. Las 53 alertas con esta regla son TODAS critical (D-04) |
| `<0.5/3min` | El tráfico CAYÓ debajo del mínimo — el silencio sospechoso |
| `1+ locations` | Al menos una ubicación de prueba en el mundo no pudo acceder |
| `>=5/5min` | Cinco o más rechazos de pago en 5 minutos (regla del canal CX) |

---

## 5 · Diccionario de `incidents.csv` — todas las columnas explicadas

`incidents.csv` es la fuente de verdad del pipeline: cada fila es un incidente ya
deduplicado, perfilado y scoreado. Tiene 35 columnas organizadas en cinco bloques.
A continuación, cada columna con su tipo, su rango y una descripción sin jerga.

---

### 5.1 Identidad del incidente

| Columna | Tipo | Valores | Qué significa |
|---|---|---|---|
| `incident_id` | string | `INC-0001` … `INC-0277` | Número de caso. Se asigna por orden cronológico de `inicio`: INC-0001 es el más antiguo del dataset. Determinista: el mismo input siempre produce el mismo ID. |
| `channel` | string | `sre` · `monitoring-ops-cx` | Canal de Slack de origen. Decide la vista del panel y qué reloj se usó para el timestamp. |
| `source` | string | `New Relic` · `PayPal Status` | Sistema que generó la alerta. Los 3 registros de PayPal Status no tienen priority, threshold ni policy. |
| `vista` | string | `triage` · `composicion` | Vista del producto a la que pertenece el incidente. `triage` = incidentes de sre con score. `composicion` = rechazos de pago de cx, sin score individual. |
| `fingerprint` | string | `Orchestrator::high request count with status 500` | La identidad del problema: `{service_normalizado}::{condition}`. La CURP del incidente. Dos incidentes con el mismo fingerprint son el mismo problema en distintos momentos. |

---

### 5.2 Servicio afectado

| Columna | Tipo | Valores | Qué significa |
|---|---|---|---|
| `service` | string | 28 valores normalizados | Nombre del servicio **normalizado**: typos corregidos (`Princes` → `Princess`), instancias EC2 colapsadas a `infra`. El que aparece en el panel. |
| `service_original` | string | nombre crudo del JSON | Nombre tal como llegó en la alerta. Para instancias infra (`i-058689...`) conserva el ID de servidor individual, que se pierde en `service`. |
| `grupo_criticidad` | string | `pagos` · `nucleo` · `datos` · `infra` · `codename` · `web` | Categoría de criticidad del servicio, inferida del dato y configurable en `config.yaml`. Determina `s_criticidad`. Ver S-03 en `supuestos.md`: debe validarse con el equipo en semana 0. |
| `condition` | string | 23 valores | La plantilla del problema que disparó la alerta. Mitad de la identidad del fingerprint. |
| `policy` | string | 4 valores + null | Carpeta de New Relic que agrupa conditions relacionadas. Los 3 PayPal Status tienen null. |

---

### 5.3 Tiempo y tamaño del incidente

| Columna | Tipo | Valores | Qué significa |
|---|---|---|---|
| `inicio` | datetime (tz-aware) | timestamp ISO con UTC-6 | Cuándo llegó la **primera alerta** del incidente a Slack. No es cuándo empezó el problema en el sistema — es cuándo New Relic lo notificó. |
| `fin` | datetime (tz-aware) | timestamp ISO con UTC-6 | Cuándo llegó la **última alerta** del incidente. Si solo hay una alerta, `fin == inicio`. |
| `duracion_min` | float | 0.0 … ~200 | `(fin − inicio)` en minutos. Mide la ventana de tiempo que duró la ráfaga de notificaciones, no necesariamente el tiempo que el sistema estuvo degradado. |
| `n_alertas` | int | 1 … N | Cuántos **mensajes de Slack** (filas del JSON) conforman este incidente. Es el contador de notificaciones. |
| `n_disparos` | int | 1 … N | Suma de la columna `incidents` de New Relic: cuántos disparos internos empaquetó cada mensaje. Siempre ≥ `n_alertas`. Los 3 PayPal Status se imputan como 1. |
| `tasa_por_min` | float | > 0 | `n_disparos / max(duracion_min, 1.0)`. Disparos por minuto. Para incidentes de 0 min de duración, el denominador se sujeta a 1 para evitar división por cero. |

---

### 5.4 Señal original de New Relic

| Columna | Tipo | Valores | Qué significa |
|---|---|---|---|
| `priority_max` | string | `high` · `critical` · null | La prioridad más alta que tuvo alguna alerta del incidente. `critical` gana sobre `high`. Los 3 PayPal Status son null. |
| `tipo_regla` | string | `estatica` · `anomalia` | Cómo disparó la regla. `estatica`: cruzó un umbral fijo (ej. `>60%`). `anomalia`: New Relic comparó contra el comportamiento histórico propio y detectó desviación (`baseline`). |
| `direccion` | string | `sobre` · `bajo` · `neutral` | Dirección del cruce. `sobre`: el valor subió por encima del umbral. `bajo`: cayó por debajo (degradación silenciosa). `neutral`: regla sin operador direccional. |

---

### 5.5 Score y banda

| Columna | Tipo | Rango | Qué significa |
|---|---|---|---|
| `s_criticidad` | float | 0.0 – 1.0 | ¿Qué tan vital es el servicio afectado? Viene de la tabla `criticidad_servicios` en `config.yaml`. Pagos = 1.0, web = 0.4. |
| `s_ficha` | float | 0.0 · 0.1 · 0.6 · 0.9 | ¿Se comporta como siempre? 0.9 = sin historial. 0.6 = hora atípica (inactivo en batch, ver L-01). 0.1 = ráfaga mayor a la típica. 0.0 = completamente habitual. |
| `s_rafaga` | float | 0.0 – 1.0 | ¿Con qué intensidad insiste? `log2(n_disparos + 1) / log2(sat + 1)` donde `sat` = `score.rafaga.saturacion_disparos` en `config.yaml` (por defecto 31). Se satura en 1.0. |
| `s_intensidad` | float | 0.30 · 0.50 · 0.75 · 1.00 | ¿Con qué fuerza gritó New Relic? null = 0.30, high = 0.50, critical estática = 0.75, critical anomalía = 1.00. |
| `s_novedad` | float | 0.0 · 0.9 · 1.0 | ¿Es la primera vez que existe? 1.0 = nunca visto o visto un solo día. 0.9 = poco visto (< `recurrente_min_dias`). 0.0 = fingerprint establecido. |
| `score` | int | 0 – 100 | `round(100 × Σ wᵢ·sᵢ)`. La suma ponderada de los 5 componentes. Pesos en `config.yaml`. |
| `banda` | string | `P1` · `P2` · `P3` | Traducción del score a acción. P1 ≥ 70, P2 40–69, P3 < 40. |
| `banda_etiqueta` | string | texto | La banda en lenguaje humano: "Atiende ahora", "Revisa hoy", "Informativo, no requiere acción". |
| `explicacion` | string | texto | Frase generada por reglas que explica por qué el incidente recibió ese score. Se muestra en el panel y en el digest. |

---

### 5.6 Ficha de recurrencia (snapshot del historial)

| Columna | Tipo | Valores | Qué significa |
|---|---|---|---|
| `es_recurrente` | bool | `True` · `False` | `True` si el fingerprint tiene `dias_visto >= recurrente_min_dias` (por defecto 3). Indica que existe ficha histórica estable. |
| `dias_visto` | int | 1 … N | Cuántos días distintos apareció este fingerprint en el histórico del canal. Base de `s_novedad` y `s_ficha`. |

---

### 5.7 Columnas exclusivas de cx (canal monitoring-ops-cx)

| Columna | Tipo | Valores | Qué significa |
|---|---|---|---|
| `error_type` | string · null | `INSUFFICIENT_FUNDS` · `CARD_DECLINED` · etc. | Código estructurado del rechazo de pago. Solo existe en cx — en sre es null por diseño (esquema distinto, no missingness). Dimensión principal de la vista composición. |
| `procesador` | string · null | `Conekta` · `Mercadopago` · `PayPal` · null | Procesador de pago derivado de `error_message` por regex. Solo en cx. |

---

### 5.8 Columnas del panel (editables por el humano)

| Columna | Tipo | Valores | Qué significa |
|---|---|---|---|
| `atendido` | datetime · null | timestamp o vacío | El operador marcó que actuó sobre este incidente. Se registra con timestamp. Es el sensor de la métrica norte: tiempo entre `inicio` y `atendido`. Vive en memoria del panel — se pierde si no se exporta (L-08). |
| `etiqueta` | string · null | `ameritaba` · `ruido` · vacío | El juicio humano sobre si el score fue correcto. Acumula el ground truth necesario para recalibrar los pesos a partir del día 60 (L-02, `gestion.md`). |

---

## 6 · Lo que el pipeline construye encima

| Componente | Qué es | Analogía |
|---|---|---|
| Fingerprint | Identidad del problema: service + condition | La CURP del problema |
| Deduplicación | Colapsar gritos repetidos en uno | Los palitos del mesero: "tacos pastor \|\|\|\|" |
| Ráfaga | Repeticiones del mismo fingerprint con ≤30 min entre sí | Las llamadas perdidas de tu mamá = UN "me urge" |
| Incidente | Un episodio: fingerprint + ventana + conteo + duración | El expediente del caso |
| Ficha de recurrencia | La costumbre histórica de cada fingerprint: días vistos, horas típicas, tamaño de ráfaga típico | La tarjeta del cliente frecuente: "Juan, martes-jueves, 8am, 1 café" |
| Score | Avalúo 0–100 con 5 ingredientes ponderados (D-09) | El score crediticio: muchas variables, pesos declarados, traduce técnico a operativo |
| Banda | El score traducido a acción: P1 Atiende ahora / P2 Revisa hoy / P3 Informativo | El semáforo: nadie opera con "87" |
| Crónico activo | Fingerprint recurrente con ≥5 episodios en el período (D-13) | El expediente del paciente con condición crónica: no es una urgencia nueva cada visita |
| Digest | Resumen narrado del día (Gemini 2.5 Flash, D-08) | El noticiero matutino: no 642 notas, las 3 que importan |
| Panel | Tabla de incidentes con score, banda, atendido y etiqueta editables | La mesa de trabajo del detective |
| Etiqueta | El humano dicta: "ameritaba" o "ruido" | El maestro calificando al alumno (el score) |
| Atendido | El humano marca que actuó, con timestamp | El acuse de recibo — sensor de la métrica norte |
| Adaptador | Traductor por fuente al esquema común | El enchufe universal de viaje |
| config.yaml | Pesos, criticidades y ventanas editables sin tocar código | Las perillas del tablero |

### El score, con números (D-09)

```
score = 100 × ( 0.30·s_criticidad   ¿qué tan vital es el órgano afectado?
              + 0.25·s_ficha        ¿se porta como acostumbra? (D-04, D-06)
              + 0.20·s_rafaga       ¿con qué intensidad insiste?
              + 0.15·s_intensidad   ¿qué tan fuerte gritó New Relic?
              + 0.10·s_novedad )    ¿es la primera vez que existe?
```

Bandas: **P1 ≥ 70 · P2 40–69 · P3 < 40**. Pesos heurísticos v0, declarados en
`config.yaml`, recalibrables con etiquetas humanas a partir del día 60
(`gestion.md`).

---

## 7 · Las dos vistas del producto (D-12)

**Triage (`#sre`)** — la enfermera de urgencias: llegan pacientes distintos y
hay que ordenarlos por gravedad. Decisión individual contra el reloj. Aquí
viven el score y las bandas. Consumidor primario: Tech.

**Composición (`#cx`)** — el reporte epidemiológico del director: no importa
el orden de la fila, importa de qué se enferma la población y cómo cambia la
mezcla. Los 95 registros son la misma "enfermedad" (rechazo de pago);
priorizarlos entre sí no aporta. Lo útil es su composición por `error_type` y
`procesador`, y su tendencia. Consumidor primario: Ops/Payments.

Una sola fuente de verdad (`incidents.csv`), dos preguntas, dos vistas. Más dos
superficies: el **digest** (push, los 2 minutos) y el **panel** (pull,
profundización + etiquetado).

---

## 8 · Cómo se mide el éxito (gestión completa en `gestion.md`)

**Métrica norte:** tiempo entre que un incidente P1 comienza y se marca
`atendido`. Como una alarma de incendios: lo que importa es cuántos minutos
pasan entre el fuego y los bomberos. Hoy inmedible — la semana 0 mide el
baseline sin la herramienta.

**Matriz de confusión** (banda vs etiqueta humana):

| | Humano: ameritaba | Humano: ruido |
|---|---|---|
| Score: P1/P2 | ✅ Detección correcta | ❌ Falso positivo — fatiga de alertas |
| Score: P3 | ❌ Falso negativo — el error caro | ✅ Ignorado correctamente — **ignorar bien también es éxito medible** |

**Kill criteria:** si a 90 días el % de P1 atendidos está por debajo de 60%
(el piso de "ya no es un volado", `gestion.md`), la herramienta se
rediseña o se mata formalmente — el sistema carga su propia sentencia de
muerte a la vista, el antídoto contra "dejó de usarse sin que nadie tomara la
decisión".

El ciclo completo: el humano etiqueta → las etiquetas recalibran pesos → el
score mejora → el humano confía más. **No se sostiene por disciplina: se
sostiene porque usarlo lo mejora.**

---

> **La frase que resume todo:** el pipeline convierte 12 columnas sucias en un
> sistema que aprende de quien lo usa. Y este glosario existe porque traducir
> lo técnico a lenguaje de cualquiera no es un apoyo del proyecto — es el
> proyecto.
