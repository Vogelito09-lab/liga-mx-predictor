# Limitaciones conocidas

## Datos

- **ESPN no ofrece una API documentada oficialmente.** Puede cambiar el formato o bloquear consultas sin aviso. Todo el
  manejo del formato está en `backend/app/sources/espn.py`, y la verificación cruzada con Football-Data.co.uk detecta
  marcadores incorrectos, pero si ESPN dejara de responder habría que cambiar de fuente.
- **Cobertura histórica**: se verificó que ESPN tiene partidos desde el Apertura 2016. La cobertura completa partido por
  partido (huecos, partidos faltantes) se medirá en la primera descarga real y quedará en este documento.
- **Torneo Clausura 2020**: se canceló por la pandemia sin liguilla; esos partidos son válidos pero el torneo queda
  incompleto (el backtesting solo usa torneos con al menos 60 partidos).
- **Jornada**: ESPN no la publica; se deriva por orden de partidos de cada equipo. Un partido reprogramado puede aparecer
  con otra jornada.
- **Marcador a 90 minutos** en partidos con prórroga: depende de la lista de goles de ESPN. Si no cuadra, el partido no se
  usa para entrenar.
- Sin alineaciones, lesiones, suspensiones, traspasos ni noticias: no hay una fuente gratuita y verificable con historial.
  Los cambios de plantilla solo se reflejan a través de los resultados (y de la regresión del Elo entre torneos).
- Días de descanso: solo cuentan partidos de Liga MX (no Copa, Leagues Cup ni Concacaf).

## Modelo

- El fútbol tiene mucho azar. Un buen modelo de 1X2 suele acertar alrededor de la mitad de los partidos; los empates son
  especialmente difíciles. Las métricas reales se publican en la web con el tamaño de muestra.
- Con unos 300 partidos por torneo, diferencias pequeñas entre modelos pueden no ser significativas.
- Las explicaciones ("factores") describen los datos que el modelo vio y el peso interno de las variables; no implican
  causalidad.

## Actualización

- "En vivo" significa cada ~10 minutos, no al segundo, por usar tareas programadas gratuitas.
- El servicio gratuito de Render se duerme: la primera visita tras un rato tarda ~1 minuto.
- Si GitHub Actions se retrasa o falla, la web lo indica con la hora de la última sincronización.

## Entorno de desarrollo

- El entorno en la nube donde se programó esta versión no tenía acceso a ESPN ni a Football-Data.co.uk (solo a
  gestores de paquetes). El código se probó con una liga **simulada** y con eventos que replican el formato verificado
  de ESPN; la primera descarga real se hará con acceso a esos dominios.
