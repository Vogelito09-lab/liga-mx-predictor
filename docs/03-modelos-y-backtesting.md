# Modelos, variables y backtesting

## Variables (todas disponibles antes del partido)

Se calculan recorriendo los partidos en orden cronológico. Para cada hora de inicio se calculan primero las variables
de todos los partidos de esa hora y **después** se incorporan sus resultados, de modo que ningún partido ve su propio
resultado ni el de partidos simultáneos o posteriores. Hay una prueba automática que recalcula las variables de
partidos al azar borrando todo lo posterior y comprueba que no cambian.

| Variable | Disponible desde | Detalle |
|---|---|---|
| Elo local, visitante y diferencia (con ventaja de local) | Fin del partido anterior de cada equipo | K y ventaja de local elegidos en validación; multiplicador por diferencia de goles; regresión parcial a la media al empezar cada torneo |
| Puntos por partido, últimos 5 y 10 | Ídem | |
| Goles a favor/en contra, últimos 5 y 10 | Ídem | |
| Rendimiento del local en casa y del visitante fuera (últimos 5) | Ídem | |
| Goles con ponderación temporal exponencial | Ídem | Vida media de 8 partidos |
| Puntos por partido y diferencia de goles en el torneo actual | Ídem | En las primeras jornadas se usa la forma de los últimos 10 partidos como respaldo |
| Enfrentamientos directos (últimos 6) | Ídem | Puntos medios del local |
| Días de descanso | Ídem | Solo partidos de Liga MX (no incluye Copa ni Concacaf) |
| Tendencia (últimos 5 − últimos 10) | Ídem | |
| Fase (regular / eliminatoria) | Publicación del calendario | |

**Equipos sin historial** (ascendidos o nuevos): Elo inicial de 1450 (la media es 1500), forma de respaldo de 1.2 puntos
por partido y, en el modelo de goles, ataque y defensa algo inferiores a la media. Todo está documentado en el código
(`app/features/build.py`, `app/ml/models.py`).

No se usan alineaciones, lesiones ni noticias: no hay una fuente gratuita y verificable con historial suficiente.

## Modelos

| | Modelo | Qué hace |
|---|---|---|
| A | Referencia | Frecuencias de local/empate/visitante del periodo de entrenamiento |
| B | Elo | Logit ordinal sobre la diferencia de Elo |
| C | Poisson Dixon-Coles | Ataque y defensa por equipo + ventaja de local + corrección de marcadores bajos, con ponderación temporal exp(−ξ·días). Da la matriz completa de marcadores |
| D | Logística multinomial | Sobre todas las variables, estandarizadas, con regularización L2 |
| E | LightGBM | Árboles potenciados poco profundos sobre las mismas variables |
| F | Combinado | Promedio de C y del mejor de B/D/E en validación |

El **marcador más probable** y los **goles esperados** salen siempre del modelo C (la matriz de marcadores), aunque las
probabilidades 1X2 vengan de otro modelo. El marcador más probable es la celda de mayor probabilidad conjunta, no una
conversión de las probabilidades de victoria. Por eso puede pasar que el resultado más probable sea "victoria local" y el
marcador más probable sea 1-1: el empate concentra su probabilidad en pocos marcadores.

## Backtesting

1. Se toman los torneos completos con al menos 60 partidos, ordenados por fecha.
2. Los 4 primeros solo sirven para entrenar (calentamiento).
3. Los siguientes, salvo los 2 últimos, son **validación**: ahí se eligen los hiperparámetros (K, ventaja de local y
   regresión del Elo; ξ del Poisson; C de la logística; configuración de LightGBM) y el modelo final, por **log loss**.
4. Los **2 últimos torneos completos** son la **prueba final**: se evalúan una sola vez, después de fijar todo lo anterior.
   Una prueba automática altera los resultados del periodo de prueba y comprueba que no cambia ninguna decisión.
5. Dentro de cada torneo evaluado, cada semana se predice con un modelo entrenado solo con partidos anteriores al inicio
   de esa semana (la misma política que en producción).

Métricas: exactitud del resultado más probable, log loss, Brier multiclase, RPS, matriz de confusión, calibración por
intervalos, error absoluto medio de goles esperados y del marcador más probable, y desglose por torneo, temporada, fase y
resultado real. Todas indican el tamaño de muestra.

Los resultados reales del backtesting se publican en la página **Rendimiento del modelo** cuando el backtesting se ejecuta
con los datos reales. Este documento no incluye cifras porque todavía no se han descargado.

## Predicciones en producción

- Se generan para partidos programados que aún no empiezan, hasta 30 días adelante.
- Son **inmutables** (la base de datos rechaza cualquier UPDATE). Si cambian el modelo o las variables de un partido
  (por ejemplo, porque uno de los equipos jugó entre medio), se guarda una **nueva** versión y se conserva la anterior.
- La predicción que cuenta para evaluar es la última generada antes del inicio del partido.
- Nunca se generan predicciones para partidos iniciados o finalizados.

## Probabilidad de clasificar y de ser campeón

La página **Tabla general** muestra, para el torneo en curso, la probabilidad de cada equipo de quedar entre los
8 primeros y de ganar el título. Se calcula en `backend/app/predict/standings.py` con una simulación Monte Carlo
(10,000 repeticiones, semilla fija para que el resultado no cambie entre visitas):

1. Se parte de la tabla real (partidos finalizados).
2. Cada partido pendiente de la fase regular se juega con la matriz de marcadores del modelo de goles
   (Dixon-Coles) del modelo activo; si el partido tiene predicción guardada, la matriz se reescala para que sus
   probabilidades de local/empate/visitante coincidan con esa predicción. Los cruces que ESPN aún no publica en el
   calendario (la liga es todos contra todos, una vez) se simulan promediando las dos opciones de local.
3. Se ordena la tabla de cada simulación (puntos, diferencia de goles, goles a favor) y los 8 primeros juegan la
   liguilla: 1-8, 2-7, 3-6, 4-5, semifinales con reacomodo, ida y vuelta con la vuelta en casa del mejor ubicado.
   En cuartos y semifinales el empate global lo gana el mejor ubicado; en la final hay tiempos extra (goles con un
   tercio del promedio) y penales (50 %). Los partidos de liguilla ya jugados usan su marcador real.

Formato verificado (10-oct-2026): desde el Apertura 2026 no hay Play-In y clasifican directo los 8 primeros
([Vanguardia](https://vanguardia.com.mx/deportes/futbol/asi-se-disputara-el-apertura-2026-fecha-de-inicio-adios-al-play-in-y-calendario-de-liguilla-GC20224103),
[TUDN](https://www.tudn.com/futbol/liga-mx/hay-play-in-o-repechaje-en-la-liga-mx-apertura-2026)); desempate en
eliminatorias según [Goal](https://www.goal.com/es-mx/noticias/como-se-define-liguilla-caso-de-empate/17q5mxhcxls1u125kbpkssurjr)
y criterios de la tabla según [Fox Sports](https://www.foxsports.com.mx/2026/04/22/quedan-3-cupos-para-liguilla-que-criterios-de-desempate-definen-la-tabla-general/).
La tabla de Fair Play no está en la fuente de datos, así que no se usa.

La API la recalcula solo cuando cambian los datos o el modelo (tarda menos de un segundo).

## Política de reentrenamiento

Actualizar estadísticas no es reentrenar: tras cada resultado, el Elo y la forma se recalculan y el modelo vigente
se aplica sobre las variables nuevas. El modelo se reentrena (tarea diaria de mantenimiento) cuando:

- no hay modelo activo, o
- hay 9 o más partidos nuevos desde su fecha de corte (una jornada), o
- tiene más de 7 días y hay al menos un partido nuevo.

El backtesting completo (que puede cambiar el tipo de modelo elegido) se repite una vez al mes o manualmente.
