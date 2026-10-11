# Marcador y probabilidad en vivo

**Costo: $0.** No hay ningún proceso encendido todo el tiempo: el servidor solo trabaja mientras alguien tiene la
página abierta y hay un partido por empezar (15 min antes) o en juego.

## Cómo funciona

- La página pregunta a `GET /api/live` cada 30 s cuando hay partido (cada 2 min si no).
- La API pide el marcador a ESPN (`/scoreboard` de `mex.1`) **como mucho cada 25 s**, y todas las personas que
  miran comparten esa misma respuesta. Sin partidos en ventana no se consulta a ESPN.
- De ESPN se usan: marcador, minuto (`status.displayClock`), periodo, estado y tarjetas rojas (`details[].redCard`).
- Si ESPN falla o tarda, se sigue mostrando el último dato y la tarjeta avisa que está atrasado.
- Nada de esto se guarda en la base de datos. Cuando ESPN marca un partido como empezado o terminado y la base aún
  no, se adelanta la sincronización normal (como mucho una vez cada 2 min); el resultado oficial a 90' y los
  puntos de la quiniela siguen saliendo de esa sincronización, igual que antes.

Se ve en Inicio, Predicciones, la página de cada equipo (tarjetas de partido) y en la Quiniela (partidos cerrados).

## Probabilidad según el minuto (`app/predict/live.py`)

1. Se toman los goles esperados de la última predicción previa al partido (λ local, μ visitante).
2. Si falta la fracción `f` de los 90', los goles que faltan siguen una Poisson de media λ·f y μ·f
   (se supone que los goles caen parejo a lo largo del partido; en el añadido se deja al menos 1 minuto).
3. Marcador actual + goles que faltan → probabilidad de local / empate / visitante a los 90' y marcador final
   más probable.
4. Cada resultado se multiplica por (p_previa / p_poisson)^f: así en el minuto 0 coincide exactamente con la
   predicción previa (que combina Poisson y Elo) y esa corrección desaparece al final.

En prórroga y penales no se muestra probabilidad en vivo: la predicción y la quiniela son sobre los 90'.

## Limitaciones

- La API de ESPN no es oficial: puede cambiar, tardar o fallar.
- El marcador llega con el atraso de ESPN más hasta ~30 s.
- No se ajusta por expulsiones, cambios, lesiones ni dominio del partido (no hay datos propios para medirlo);
  las rojas solo se muestran.
- En Render gratis la API se duerme sin visitas: la primera carga puede tardar ~1 min.
