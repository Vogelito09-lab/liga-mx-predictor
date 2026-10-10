# Resultados con datos reales (primera ejecución, 10-oct-2026)

Todo lo de esta página sale de la primera descarga real, no de datos simulados. Se puede repetir con los pasos 6–8
del README.

## Datos descargados

- **Fuente principal**: ESPN, consultada día por día del 1-jul-2016 al 31-oct-2026 (3,775 días). Las respuestas
  originales quedaron guardadas sin modificar para poder auditarlas.
- **Partidos**: 3,516 en total, de 21 torneos (Apertura 2016 → Apertura 2026), 23 equipos distintos.
  - 3,409 terminados (del 16-jul-2016 al 10-oct-2026)
  - 63 cancelados: Clausura 2020, suspendido por la pandemia
  - 43 programados (próximas jornadas del Apertura 2026, más 1 registro rancio, ver abajo)
  - 1 suspendido: Atlas – América, 21-feb-2021
- Cada torneo completo tiene 153 partidos de fase regular (171 en el Apertura 2019, con 19 equipos) y 14–18 de liguilla.

## Validación

- **Verificación cruzada con Football-Data.co.uk** (archivo `MEX.csv`, 3,407 filas en el periodo):
  3,393 marcadores coinciden, **3 no coinciden** y 14 filas no se pudieron emparejar con un partido de ESPN.

  | Partido | ESPN | Football-Data | Comentario |
  |---|---|---|---|
  | Monarcas – Santos Laguna, 5-ago-2017 | 2-1 | 1-1 | Por revisar a mano |
  | Santos Laguna – Monarcas, 22-ene-2018 | 0-0 | 1-0 | Por revisar a mano |
  | Querétaro – Atlas, 5-mar-2022 | 0-1 | 0-3 | Partido suspendido por violencia; ESPN guarda el marcador al momento de la suspensión y Football-Data el resultado administrativo |

  No se corrige ninguno automáticamente: quedan como incidencias en la página **Administración**.
- **Auditoría de ESPN**: 22 partidos donde la lista de goles no cuadra con el marcador final (se usa el marcador
  final) y 1 registro rancio: Tigres – Guadalajara con fecha 18-jul-2016, marcado como "programado" y asignado al
  Clausura 2017, que nunca se jugó en esa fecha.

## Backtesting

Origen móvil por torneo: 4 torneos de calentamiento (Apertura 2016 → Clausura 2018), 14 de validación
(Apertura 2018 → Clausura 2025, 2,314 partidos) para elegir modelo e hiperparámetros, y 2 de prueba reservados
(Apertura 2025 y Clausura 2026, 337 partidos) que no intervienen en la elección. El Apertura 2026 queda fuera porque
está en curso.

| Modelo | Log loss validación | Log loss prueba | Acierto prueba | Brier prueba | RPS prueba |
|---|---|---|---|---|---|
| A. Referencia (frecuencias) | 1.0678 | 1.0584 | 47.2 % | 0.6385 | 0.2248 |
| B. Elo | 1.0271 | 0.9942 | 54.3 % | 0.5936 | 0.2029 |
| C. Poisson (Dixon-Coles) | 1.0243 | 0.9974 | 51.3 % | 0.5952 | 0.2039 |
| D. Logística | 1.0343 | 0.9985 | 51.6 % | 0.5968 | 0.2049 |
| E. LightGBM | 1.0491 | 1.0121 | 54.9 % | 0.6050 | 0.2076 |
| **F. Combinado (C + B)** | **1.0242** | **0.9941** | 54.0 % | **0.5932** | **0.2028** |

- **Modelo elegido**: F (promedio de Poisson Dixon-Coles y Elo), por tener el menor log loss en validación. En el periodo
  de prueba también tiene el menor log loss, Brier y RPS. La diferencia con C y B es pequeña.
- Marcadores (modelo de goles Poisson), periodo de prueba: error medio de goles esperados 0.92 por equipo y marcador
  exacto acertado en el 10.7 % de los partidos (12.5 % en validación).
- Hiperparámetros elegidos: Elo k = 15, ventaja de local 80, regresión entre torneos 0.1; decaimiento temporal de
  Dixon-Coles 0.002; logística C = 0.01; LightGBM 200 árboles, 5 hojas.
- El modelo de producción se entrenó con los 3,409 partidos terminados y generó 42 predicciones para los partidos
  pendientes.
