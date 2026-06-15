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

## 5 · Lo que el pipeline construye encima

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

## 6 · Las dos vistas del producto (D-12)

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

## 7 · Cómo se mide el éxito (gestión completa en `gestion.md`)

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
