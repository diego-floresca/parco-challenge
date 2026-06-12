# EDA — Hallazgos completos con evidencia
> Memoria profunda del análisis exploratorio sobre `alerts_combined.json` (458 registros).
> Cada número de aquí es verificable re-corriendo el análisis. Los tests de integración
> afirman los marcados como [ACEPTACIÓN].

## 1. Estructura general
- [ACEPTACIÓN] 458 registros, lista JSON plana.
- [ACEPTACIÓN] 3 esquemas de llaves: base con threshold (360), base + error_type/error_message (95,
  todo el canal cx), base sin threshold (3, los registros de PayPal Status).
- [ACEPTACIÓN] 2 channels: sre (363), monitoring-ops-cx (95). 2 sources: New Relic (455), PayPal Status (3).
- [ACEPTACIÓN] 28 services crudos, 23 conditions, 5 policies.

## 2. Los tres segmentos del archivo (el nombre "combined" lo confiesa)
| Seg | Índices | Canal | Período real | Estado de relojes |
|---|---|---|---|---|
| 1 | 0–151 | sre | 7–11 jun 2025 | ts e ISO coinciden (delta < 60s) |
| 2 | 152–362 | sre | 26 may–4 jun 2025 | ISO corrupto: desfases erráticos −17h a +6h, sin patrón de zona horaria |
| 3 | 363–457 | cx | 24–27 mar 2026 (según ISO) | ts roto: comprime 4 días en ~7.8 horas |
- 300 de 458 registros tienen contradicción >60s entre ts e ISO.
- Los períodos de sre y cx son DISJUNTOS y de años distintos: tratar como dos corpus;
  fichas de recurrencia por canal, nunca mezcladas.
- Implicación de volumen: ~21–38 alertas/día reales vs "cientos al día" del brief
  (supuesto documentado: muestra filtrada o brief exagera).

## 3. El juicio de los relojes de cx (evidencia del veredicto)
- Según `ts`: 95 alertas en 7.8 horas (18h–02h), gap mediano EXACTAMENTE 5.0 min
  (= la ventana de la regla >=5/5min; 95 × 5 min = 7.9 h, la aritmética del relleno cuadra).
  Rechazos de pago de madrugada a ritmo de metrónomo, cero en horario comercial: imposible.
- Según ISO: 72 de 95 alertas entre 12h–16h, silencio de madrugada, volumen por día
  57 / 10 / 5 / 23 (24–27 mar). Ritmo circadiano + un día malo: plausible.
- Veredicto: en cx gana el ISO. Principio: los rechazos son hijos de los intentos de pago,
  y los pagos siguen el ritmo humano. La uniformidad perfecta es firma de máquinas
  (gap fijo = timestamps regenerados por la herramienta de export, no horas reales).
- Nota fina: el desfase ts↔ISO en cx es ~375–378 días pero NO es un año corrido reparable:
  además de corrido está comprimido (ISO abarca 4 días, ts abarca ~1). No intentar reparar ts.

## 4. Duplicados y ráfagas
- [ACEPTACIÓN] Duplicados byte a byte: 0. Mismo (ts, service, condition): 0.
- La "duplicación" que el brief promete es SEMÁNTICA: mismo fingerprint repitiéndose en
  ventanas cortas. Con ventana de 30 min: [ACEPTACIÓN] 46 ráfagas contienen 227 alertas
  (50% del total); 458 alertas -> ~277 incidentes.
- La columna `incidents` de New Relic ya empaqueta disparos casi simultáneos en una
  notificación (anti-spam). Distribución: 1->298, 2->131, 3->14, 4->6, 6->4, 7->2, null->3.
  [ACEPTACIÓN] Suma ≈ 667 (con null→1; 664 sin los 3 PayPal) disparos reales en 455 mensajes: New Relic ya comprimió 31%
  antes que nosotros. Los valores altos (4-7) son cascadas critical de Throughput/CPU.

## 5. La jerarquía oculta entre columnas (pivotes)
```
channel  <-  policy  <-  condition  <-  service
  (2)         (5)         (23)          (28)
```
- [ACEPTACIÓN] policy -> channel es partición perfecta: Golden Signals (254), Parco2.0 strict (95),
  Up_Satatus_Parco (11) y None (3) viven 100% en sre; CX (95) vive 100% en cx.
- [ACEPTACIÓN] condition -> policy es 1 a 1 en las 23 conditions.
- service <-> condition es muchos-a-muchos con personalidad (cada servicio tiene su
  repertorio corto de males). Detalle completo:
  - Hairs (124): Payments rejected hairs CX (95), Throughput high general (19),
    Low Application Throughput (6), Payments rejected hairs (4)
  - Orchestrator (104): high request count with status 500 (91), High Application Error percentage (13)
  - Wallet_2.0 (31): Status code 500 counted request (31)
  - tesseract (29): Throughput high general (20), High App Error percentage (7),
    Low App Throughput (1), External Scan Alert (1)
  - Carts (28): Carts Throughput high (17), Apdex score (11)
  - Users (26): Throughput high general (19), SMS Alert (4), High App Error % (2), login alert (1)
  - Cerberus (20): Cerberus Throughput High (11), High App Error % (8), Low App Throughput (1)
  - Transaction query (12): global traffic alert (12)
  - Princess (11): High Application Response Time gral (8), High App Error % (3)
  - i-058689de5ec046291 (11): Parco 2.0 Nodes CPU Usage (11)
  - Wiki (9): Parco APIs status - locations failed (9)
  - data-team (7): RDS CPU Usage gral (7)

## 6. El mecanismo de la prioridad (escalones de umbral)
- priority NO es determinista por condition (9 de 23 conditions mixtas) pero cada condition
  tiene ESCALONES de threshold y el escalón alto dispara critical puro:
  - high request count with status 500: >55/5min -> {high:15, critical:43}; >60/5min -> {critical:33}
  - RDS CPU Usage gral: >55%/10min -> {high:5, critical:9}; >60%/10min -> {critical:5}
  - Throughput high general: >2700/5min -> {high:45, critical:8}; >3200/5min -> {critical:5}
- Conclusión: priority codifica INTENSIDAD (qué tan lejos del umbral). Es la quinta
  variable del score, con mecanismo documentado.
- threshold tipo "baseline" (detección de anomalías propia de New Relic): 53 alertas,
  TODAS critical, solo en High Application Error percentage (44) y Low Application
  Throughput (9). Una alerta tipo baseline viene pre-curada como anomalía -> boost.
- Reglas con dirección "<" (<0.5/3min, <0.6/3min): throughput POR DEBAJO = degradación
  silenciosa, semánticamente distinta y a menudo más grave -> boost candidato.

## 7. Canal cx = el KPI de Payments dentro del JSON
- [ACEPTACIÓN] 95 registros, 100% con error_type. Composición: INSUFFICIENT_FUNDS 28 (29%),
  IMPOSSIBLE_TO_CHARGE 25 (26%), CARD_DECLINED 23 (24%), BANK_REJECTED 12 (13%), resto 7 (8%).
- error_type != error_message en 37/95: error_message trae descripción humana en español
  Y el procesador de pago ("El banco emisor rechazó el pago sin más detalles (Conekta)",
  "Error from Mercadopago"). NO unificar: extraer campo derivado `procesador`.
- El KPI mensual de Payments ("disminuir % de errores por fondos insuficientes") se
  calcula directo de esta vista: % INSUFFICIENT_FUNDS por día, con tendencia y procesador.

## 8. Patrones temporales (canal sre, con reloj ts)
- Pico nocturno ~02h: RDS CPU Usage (data-team, 6 días distintos) + Apdex de Carts
  (5 días distintos). Hipótesis: ETL/jobs nocturnos. -> ficha "habitual nocturno".
- Fin de semana, normalizado por días observados: Dom ~64 alertas/día, Sáb ~37,
  vs Mié ~8. App de movilidad: el finde ES el pico de uso -> esperado bajo carga.
- Grueso del volumen 13h–20h (horas pico de transacciones).

## 9. Casos canónicos del score (valores del diseño coherente, pesos v0)

| Caso | sc/sf/sr/si/sn | Score real | Banda |
|---|---|---|---|
| Hairs · Payments rejected hairs (en sre) | 1.0/0.9/0.20/0.50/0.9 | 73 | P1 |
| tesseract · High Application Error percentage | 0.6/0.9/0.20/1.0/0.9 | 68 | P2 |
| i-0d26dd… · Parco 2.0 Nodes CPU Usage | 0.5/0.9/0.32/0.75/0.9 | 64 | P2 |
| data-team · RDS CPU Usage ráfaga ~02h | 0.6/0.0/0.32/0.75/0.0 | 36 | P3 |

Distribución real (277 incidentes): P1=16 (6%), P2=175 (63%), P3=86 (31%).

**Reconciliación respecto a los valores originales de este EDA:**
- Los valores anteriores (tesseract ~76 P1, data-team ~39 en frontera) asumían un boost
  acumulativo de +0.05 por tipo_regla==anomalia. Ese boost fue eliminado al implementar
  la capa de score porque duplicaba la señal ya capturada en s_intensidad=critical_anomalia=1.0.
- tesseract landing en P2: correcto sin double-counting. s_ficha=0.9 (dias_visto=2 < 3)
  + s_novedad=0.9 + s_intensidad=1.0 pero s_criticidad=0.6 (codename) → 68.
- data-team landing en 36 P3: s_ficha=0.0 (completamente dentro del patrón nocturno: días=6,
  hora 02h en horas_tipicas, n_alertas=1 ≤ rafaga_tipica). s_novedad=0.0 (recurrente). Sin
  ambigüedad P3/P2: 36 es P3 claro. El equipo humano dirá "sí, eso es el ETL nocturno de siempre".
- **El diseño manda sobre el número**: los scores son output del modelo coherente;
  los números de este EDA se actualizan a lo que ese modelo produce, no al revés.

## 10. Veredicto del "80% es ruido"
- Definición ingenua (repeticiones de ráfaga ∪ fingerprints recurrentes >=3 días): 89%
  de las alertas. Numéricamente "valida" la hipótesis interna del 80%; operativamente
  sería un desastre: marca como ruido el 100% del canal cx (¡el KPI de Payments!) y los
  500s crónicos de Orchestrator.
- Piso duro defendible: 40% es redundancia mecánica (repeticiones dentro de ráfagas,
  181 de 458).
- Conclusión: el error del análisis interno original no fue la muestra del día atípico,
  fue no definir "ruido" antes de contarlo. Lo recurrente se divide en
  esperado-bajo-carga vs crónico-que-merece-caso, y esa división la hacen la criticidad
  + las etiquetas humanas. En metrics.json se reportan AMBOS números con sus definiciones,
  y en % de alertas crudas (la unidad de la hipótesis original), no de incidentes.

## 11. Suciedad censada (manejo en normalize.py)
- Typos: service `Princes` -> `Princess` (mapa en config). Policy `Up_Satatus_Parco`
  se conserva tal cual (es identificador de origen) pero se documenta.
- Services que son infraestructura: i-058689de5ec046291 (11), i-0d26dd24e2a69bff0 (7),
  i-04acbab68c9357917 (2), i-0d568d70a0847d5b6 (2), new-parco-instance-1 (6),
  new-parco-instance-5 (2) -> grupo `infra`, conservando original en service_original.
- PayPal Status (3 registros): priority/policy/incidents null, sin threshold, estado
  embebido en condition (INITIAL/RESOLVED/Scheduled Maintenance). Adaptador propio.
  Dato externo: Chargehound es propiedad de PayPal (2021), por eso su status llega vía
  "PayPal Status". Familia pagos en criticidad.
- Formato de ts: 201 con decimales (firma Slack genuina), 257 enteros.
- Nulls reales fuera de esquema: priority null solo en los 3 de PayPal. error_type/
  error_message NO están "79% nulos": están 100% presentes en cx, 100% ausentes en sre
  (esquema por fuente, no missingness).

## 12. Contexto de negocio inferido (para narrativa, no para lógica)
- Hairs = servicio de pagos (sus conditions lo delatan). Wallet_2.0 = monedero.
  Peajero sugiere peajes/casetas. Orchestrator = coordinador central.
- Los dos focos crónicos de errores 500: Orchestrator (91) y Wallet_2.0 (31) — el
  coordinador y el monedero. Un canal cronológico jamás muestra esto.
- Golden Signals = canon SRE de Google (latencia, tráfico, errores, saturación).
- Criticidades de config.yaml son INFERIDAS: validar con el equipo en semana 0
  (documentado en supuestos.md). Es además una buena pregunta para la presentación.
