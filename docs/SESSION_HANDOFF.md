# Memoria de sesión

Última actualización: 10 de agosto de 2026, `America/Santiago`.

Este documento es el punto de reanudación del proyecto. No contiene secretos ni
credenciales.

## Objetivo

Construir una inteligencia de gil para FFXIV centrada en Cactuar que permita:

- valorar conversiones de monedas especiales;
- encontrar materiales de gathering y crafting con demanda;
- detectar compras baratas en North America para vender en Cactuar;
- acumular historial por categoría para lanzamientos de expansiones y parches;
- incorporar ML sólo cuando exista suficiente historial para compararlo contra
  reglas deterministas.

## Estado productivo

- Web pública: <https://psilvacompag.github.io/cactuar-gil-intelligence/>
- API pública de sólo lectura: <https://cactuar-api-mpkrb3h6wa-uc.a.run.app/>
- Repositorio: <https://github.com/Psilvacompag/cactuar-gil-intelligence>
- Código base anterior: `fbc7f7a` (`Make sales velocity explanation always visible`).
- Proyecto Google Cloud: `cactuar-gil-intelligence-8148`.
- Región de Cloud Run y Storage: `us-central1`.
- Dataset BigQuery: `cactuar_gil`, ubicación `US`.
- Imagen desplegada al cierre: `backend:v20`, digest
  `sha256:4aadfd684ba066efec29a394432de41407558b692d948cfa622515efb9e499e5`.
- Servicio: `cactuar-api`.
- Jobs: `cactuar-refresh` y `cactuar-archive`.
- Scheduler: 03:17 y 15:17, zona `America/Santiago`.
- Presupuesto configurado: CLP 5.000, alertas al 50%, 90% y 100%.
- Los datos de mercado continúan públicos. Google/Firebase protege perfiles,
  favoritos y administración de usuarios.

El flujo vigente es:

```text
Universalis -> Cloud Run Job -> SQLite + BigQuery -> Cloud Run API -> GitHub Pages
```

### Verificación del 10 de agosto

- La corrida programada de las 03:17 `America/Santiago` terminó correctamente en
  9 minutos y 9 segundos.
- `/v1/health` respondió `ok`; el mercado fue recolectado a las 07:18 UTC y el
  dashboard se actualizó a las 07:26 UTC.
- El dashboard publicó `priceBasis=MIN_LISTING`.
- La corrida solicitó y obtuvo 16.843 ítems, sin fallos reportados, mediante 171
  requests.
- Regresión de Grand Company seals confirmada: `200 Storm Seal -> 1 Glamour
  Dispeller`, listing mínimo de 270 gil y retorno neto de 1,2825 gil por seal.
- Las 35 pruebas locales finalizaron correctamente.

### Despliegue de Proyecciones, Snipeos y profundidad

- GitHub Pages publicó correctamente el commit `ae3b6e5`.
- Cloud Run API sirve `backend:v11` desde la revisión `cactuar-api-00010-qwg`,
  con 100% del tráfico.
- Los jobs `cactuar-refresh` y `cactuar-archive` usan la misma imagen `v11`.
- La ejecución manual `cactuar-refresh-24tr8` terminó correctamente en 9m36s.
- El snapshot productivo quedó actualizado a las 13:43 UTC: 16.843 ítems,
  cero fallos y estado de salud `ok`.
- El dashboard publicó profundidad real para 151 conversiones; las rutas de API,
  Proyecciones y Snipeos respondieron HTTP 200.

### Corrección del matching para Evercold 8.0

- GitHub Pages publicó el commit `ce30695` y Cloud Run sirve `backend:v12` desde
  `cactuar-api-00012-6fc`, con 100% del tráfico.
- Se eliminó el matching genérico por categorías. Los ítems históricos enseñan el
  rol; sólo IDs actuales explícitamente mapeados pueden ser candidatos.
- El job `cactuar-archive-kjtvx` republicó desde SQLite sin requests a Universalis.
- Producción expone 13 Materia XI adicionales, centralidad de recetas hasta Patch 7.5
  y 25 equivalentes actuales en el radar; no aparecen los precrafts antiguos.
- Validación final: 38 pruebas correctas y smoke visual del sitio público.

### Estrategia de entrada, Snipeos verificados y alertas

- GitHub Pages publicó `f294f2e`; Cloud Run sirve `backend:v13` desde
  `cactuar-api-00013-jj5`, con 100% del tráfico.
- `cactuar-refresh` y `cactuar-archive` usan la misma imagen `v13`.
- La ejecución manual `cactuar-refresh-sx4ds` terminó correctamente en 9m34s.
- El snapshot de las 14:37 UTC expone 4.032 filas, 7 snapshots históricos y estado
  de salud `ok`, con 0,15 horas de antigüedad al verificar.
- Los 26 equivalentes actuales de Evercold tienen profundidad real; el export total
  contiene profundidad para 84 filas y ninguna compra ponderada excede el stock
  observado.
- Proyecciones calcula decisión, entrada máxima, cantidad, capital expuesto, fase,
  salida e invalidación. El capital predeterminado es 5.000.000 gil y se guarda sólo
  en el navegador.
- Snipeos exige al menos dos unidades cerca del piso, atraviesa tiers reales,
  descuenta fee y mide persistencia. El primer snapshot productivo mostró 25
  candidatos verificados, 9 urgentes.
- Watchlist, alertas del navegador y ledger inicial de señales usan `localStorage`;
  no son notificaciones push en segundo plano ni un registro global del servidor.
- Validación final: 40 pruebas correctas, sintaxis JavaScript/JSON válida y smoke
  visual desktop/móvil y productivo.

### Snipeos regionales North America → Cactuar

- GitHub Pages publicó `9b5c507`; Cloud Run sirve `backend:v14` desde
  `cactuar-api-00014-6cm`, con 100% del tráfico y ambos jobs en `v14`.
- La ejecución `cactuar-refresh-5t2jf` terminó correctamente en 10m04s.
- El mínimo de compra usa `scope_level=REGION`, cubriendo los 32 Worlds de Aether,
  Primal, Crystal y Dynamis. La venta, velocidad y estrés siguen siendo Cactuar.
- Producción publicó 74 oportunidades con stock verificado. Snipeos aceptó 41 rutas
  en 19 Worlds: 9 Aether, 10 Primal, 10 Crystal y 12 Dynamis; 32 quedaron fuera de
  Aether.
- Ninguna cantidad recomendada excedió el stock verificado y el API declaró
  `sourceScope=North-America`, `sourceScopeLevel=REGION`, destino Cactuar.

### Centro unificado de señales

- GitHub Pages publicó `f35425c`; Cloud Run sirve `backend:v15` desde
  `cactuar-api-00015-gq2`, con 100% del tráfico y ambos jobs en `v15`.
- La ejecución `cactuar-refresh-5qvhr` terminó correctamente en 9m16s y publicó
  el snapshot `universalis:3bc579bf299ed787f8698088`.
- El endpoint `/v1/signals` publicó 542 señales y 542 observaciones iniciales:
  150 Conversiones, 250 Mercado, 26 Proyecciones, 75 Oportunidades y 41 Snipeos.
- `signal_observations` quedó creado en BigQuery con las mismas 542 filas, cinco
  módulos y 542 claves distintas. El ledger SQLite no tiene FK al snapshot de
  mercado, por lo que sobrevive a la ventana operativa de 14 corridas.
- La watchlist usa una clave común en las cinco vistas y migra las selecciones
  anteriores del navegador. Las alertas se emiten para vigilados de puntaje alto.
- El Centro calcula cambio, máximo y drawdown desde la primera observación; los
  retornos 7/30/90 permanecen `Acumulando` hasta cumplir cada horizonte.
- Validación final: 41 pruebas correctas, todos los endpoints HTTP 200, cero claves
  duplicadas o incompletas y smoke visual productivo desktop/móvil.

### Iconos originales y catálogo estático v6

- GitHub Pages publicó `09f1765`; Cloud Run sirve `backend:v16` desde
  `cactuar-api-00017-mrh`, con 100% del tráfico y ambos jobs actualizados a `v16`.
- Se conservó el catálogo anterior en
  `catalog/archive/static_snapshot-v5-pre-icons-20260810.json` antes de publicar v6.
- El catálogo v6 contiene 52.800 assets y 50.775 `iconId`; BigQuery archivó las
  mismas cantidades bajo `sqpack:2026.08.05.0000.0000:schema-6`.
- La ejecución `cactuar-archive-kkhkx` republicó desde el último SQLite en 2m42s,
  sin nuevas solicitudes a Universalis.
- Producción entrega iconos en 2.221 conversiones, 4.065 filas de mercado, 70
  oportunidades y 534 señales. Las seis vistas usan los PNG originales y un SVG
  minimalista local si el asset externo falla.
- `Khloe's Gold Certificate of Commendation` usa `iconId=26191`; tanto el nombre de
  moneda como la recompensa se verificaron completos en desktop y móvil.
- Validación final: 42 pruebas Python, sintaxis JavaScript, compilación Python,
  consulta BigQuery y smoke visual productivo correctos.

### Hoy, ficha universal y canjes combinados

- GitHub Pages publicó `060e97a`; Cloud Run sirve `backend:v17` desde
  `cactuar-api-00018-4f6`, con 100% del tráfico y ambos jobs en `v17`.
- La ejecución `cactuar-archive-flk2s` terminó correctamente en 2m05s y republicó
  desde el último SQLite sin nuevas solicitudes a Universalis.
- Las seis vistas comparten búsqueda global, ficha universal, etiquetas de calidad,
  sparklines reales y planes de acción deterministas. `Centro` pasó a `Hoy en
  Cactuar` y prioriza seis decisiones entre todos los módulos.
- La experiencia avanzada de Favoritos queda como TODO. La lista básica sigue
  funcionando sólo en `localStorage`; no hay sincronización, notas ni reglas por
  favorito.
- Se incorporaron canjes con varias monedas sin atribuir el retorno completo a un
  componente. Producción publica 2.577 rutas de catálogo y 270 monedas.
- Regresión verificada: `5 Bozjan Gold Coin + 30 Bozjan Platinum Coin -> Modern
  Aesthetics - Early to Rise`. El resultado es comerciable, aparece fresco y se
  valora como gil neto por canje completo; ambas monedas encuentran la misma ruta.
- Los objetos no comerciables siguen auditados en el backend, pero no inflan el
  explorador público ni reciben un valor de gil ficticio.
- Validación final: 44 pruebas Python, sintaxis de todo el JavaScript, compilación
  Python, siete endpoints HTTP 200 y smoke productivo con origen Cloud correctos.

### Cuentas Google, favoritos sincronizados y administración

- Firebase Authentication y Firestore se habilitaron en el proyecto existente.
- Las cuentas nuevas comienzan `PENDING`; `darkside.dx@gmail.com` es el bootstrap
  admin y el panel permite aprobar, suspender/reactivar y cambiar roles.
- Los favoritos viven en `cactuar_users/{uid}/favorites`. Las cuatro claves antiguas
  de favoritos se eliminan de `localStorage` sin leerlas ni migrarlas: todos parten
  desde cero.
- Los endpoints privados verifican Firebase ID tokens en Cloud Run; los datos de
  mercado siguen públicos. La revisión `cactuar-api-00021-6b7` sirve `backend:v20`.
- Firestore se creó en `us-central1` con protección de borrado. La identidad de
  Cloud Run usa ADC y roles acotados; no se creó ninguna llave de cuenta de servicio.
- Las reglas publicadas en `cloud.firestore` deniegan toda lectura/escritura directa
  desde clientes; una prueba anónima devolvió HTTP 403.
- La configuración web se obtiene en runtime desde Secret Manager y no está en Git.
- Validación: 50 pruebas Python, sintaxis JavaScript, compilación Python, health 200,
  acceso anónimo privado 401 y preflight CORS 204.

## Funcionalidad disponible

### Conversiones

- Directorio buscable de más de 100 monedas, filtros y paginación.
- Incluye Poetics, scrips, Bicolor Gemstones y Storm/Serpent/Flame Seals.
- Ranking por gil neto por moneda y velocidad de venta.
- Los canjes combinados muestran todos sus costos y gil neto por canje completo.
- Historial por conversión.
- El fee de Market Board configurado es 5%.

Decisión crítica: todas las conversiones productivas usan `MIN_LISTING`, nunca el
promedio de ventas, para evitar que operaciones atípicas inflen el retorno.

```text
gil neto / moneda = listing mínimo × recompensa × 0,95 ÷ costo en moneda
```

Caso de regresión verificado:

- `200 Storm Seal -> 1 Glamour Dispeller`.
- Backend al cierre: 288 gil por unidad y 1,368 gil neto por seal.
- El antiguo valor 2.194,65 provenía de un promedio contaminado por una venta de
  3.600.000 gil.
- La velocidad, 620,9 unidades/día en el snapshot revisado, se conserva como señal
  independiente de liquidez.
- Se comprobaron 3.060 filas valoradas contra el listing mínimo, con 0 diferencias.

### Mercado

- Listados separados para gathering y crafting.
- Búsqueda, categorías, liquidez, gil/día, frescura e historial.
- Rentabilidad estimada de recetas con ingredientes y rendimiento por craft.

### Oportunidades entre mundos

- Compra sugerida en cualquier World accesible de North America y venta en Cactuar.
- Precio estresado, fee, ROI, ventas/día, persistencia y confianza explicable.
- Stock de la shortlist verificado mediante consultas detalladas.
- Optimizador de capital y cantidad recomendada.
- Son señales, no garantías; el precio debe confirmarse en el juego.

## Trabajo desplegado el 10 de agosto

- La UI distingue `Sin datos Cactuar` de cero ventas y muestra una explicación visible
  junto a `Ventas / día`. En casos como Filtered Water, Universalis publica listing
  mundial pero omite `dailySaleVelocity.world` en el endpoint agregado.
- Los nombres de la primera celda ya no se truncan y pueden ocupar varias líneas,
  incluido el selector de monedas largas como Khloe's Gold Certificate of
  Commendation.
- Las tres tablas conservan el selector y además permiten ordenar al pulsar sus
  encabezados, alternando ascendente y descendente.
- Se incorporaron Manrope y Space Grotesk, superficies más definidas, iconos
  originales extraídos desde `sqpack` y SVG minimalistas como fallback.
- Se añadieron `Proyecciones` y `Snipeos`. Proyecciones usa el mapping v2 para Evercold:
  los ganadores históricos definen roles y sólo equivalentes actuales explícitos
  pueden entrar. No admite matches genéricos por categoría. Snipeos detecta descuentos
  anómalos contra medianas históricas conservadoras y exige margen, actividad y
  muestras suficientes.
- Las conversiones principales solicitan profundidad real de listings de Cactuar en
  lotes de hasta 100 ítems: unidades dentro de 10% del piso, días de oferta, presión
  competitiva y precio ponderado de hasta las primeras 20 unidades. El dashboard se
  vuelve a exportar después de importar estos detalles.
- La investigación histórica inicial está documentada en
  `docs/EXPANSION_LAUNCH_EVIDENCE.md` y su dataset curado en
  `docs/data/expansion_launch_evidence.json`.
- Dawntrail aún está disponible para backfill cuantitativo mediante el endpoint
  `/history` de Universalis. Endwalker no apareció en la ventana pública probada y
  debe permanecer como evidencia manual salvo que se obtenga otra fuente.
- Validación local inicial: JavaScript sin errores de sintaxis, JSON válido, 40 pruebas
  Python correctas y smoke visual en Chrome para escritorio y móvil.

## Datos y frecuencia

- El catálogo estático v6 se extrajo desde los archivos locales `sqpack`; incluye
  iconos, categorías, recetas, ingredientes y Grand Company seals.
- Una corrida consulta 1 vez `/marketable`, aproximadamente 169 lotes agregados y
  unos 7 lotes detallados: cerca de 177 requests.
- Ritmo máximo configurado: 1 request/s, una conexión y hasta dos reintentos HTTP.
- Frecuencia normal: dos corridas diarias, cerca de 354 requests/día.
- SQLite conserva 14 snapshots operativos; BigQuery recibe el histórico antes de
  la poda.
- No hay automatización oculta en Windows: la periodicidad vive en Cloud Scheduler.
- Valorar, exportar o republicar desde SQLite no genera requests a Universalis.

## Investigación sobre un dump de Universalis

- No se encontró un dump público de precios o ventas listo para importar.
- La infraestructura pública de Universalis revela un respaldo PostgreSQL diario
  en Wasabi, pero el bucket es privado.
- PostgreSQL mantiene listings actuales; el historial de ventas vive en ScyllaDB.
- No se encontró una exportación pública de Scylla, Kaggle o Hugging Face.
- Antes de construir un backfill masivo, conviene pedir al equipo de Universalis un
  snapshot de ventas limitado a Cactuar/Aether.
- Si no lo entregan, usar `/api/v2/history` en lotes y períodos, empezando por los
  ítems útiles; no ejecutar este backfill sin decidir alcance y almacenamiento.

## Decisiones pendientes

1. Seguir acumulando historial antes de usar ML. La primera comparación debería ser
   contra las reglas actuales mediante backtesting, no un modelo desplegado a ciegas.
2. Diseñar inteligencia de lanzamiento por categorías usando ventanas equivalentes
   de expansiones anteriores.
3. Decidir si solicitar el snapshot histórico a Universalis o ejecutar un backfill
   progresivo del endpoint `/history`.
4. Observar durante varios refresh la cobertura y utilidad de la nueva profundidad
   de listings antes de ampliar la shortlist más allá de 100 ítems.
5. Revisar gasto real de Google Cloud después de varios días completos de operación;
   mantener Vertex AI deshabilitado mientras ML esté pospuesto.
6. Diseñar la segunda fase de Favoritos: notas, umbrales personalizados y
   agrupaciones. La sincronización básica ya está resuelta.

## Verificación y operación

Pruebas locales:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

Estado al cierre: 44 pruebas exitosas.

Health productivo:

```text
GET https://cactuar-api-mpkrb3h6wa-uc.a.run.app/v1/health
```

Al usar `gcloud`, especificar siempre el proyecto explícitamente porque la
configuración activa del CLI puede apuntar a otro proyecto:

```powershell
--project cactuar-gil-intelligence-8148 --region us-central1
```

No iniciar manualmente `cactuar-refresh` sólo para recalcular una vista. Para una
republicación sin requests de mercado debe usarse `cactuar-archive`.

## Punto recomendado para continuar

Observar durante varios refresh los falsos positivos de Snipeos, la estabilidad de
Proyecciones y la utilidad de las seis decisiones de Hoy. Después conviene calibrar
umbrales y diseñar la segunda fase de Favoritos; ML continúa pospuesto hasta contar
con suficiente historial para comparar contra las reglas deterministas actuales.
