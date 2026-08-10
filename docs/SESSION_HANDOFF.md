# Memoria de sesión

Última actualización: 9 de agosto de 2026, `America/Santiago`.

Este documento es el punto de reanudación del proyecto. No contiene secretos ni
credenciales.

## Objetivo

Construir una inteligencia de gil para FFXIV centrada en Cactuar que permita:

- valorar conversiones de monedas especiales;
- encontrar materiales de gathering y crafting con demanda;
- detectar compras baratas en Aether para vender en Cactuar;
- acumular historial por categoría para lanzamientos de expansiones y parches;
- incorporar ML sólo cuando exista suficiente historial para compararlo contra
  reglas deterministas.

## Estado productivo

- Web pública: <https://psilvacompag.github.io/cactuar-gil-intelligence/>
- API pública de sólo lectura: <https://cactuar-api-mpkrb3h6wa-uc.a.run.app/>
- Repositorio: <https://github.com/Psilvacompag/cactuar-gil-intelligence>
- Último commit verificado: `2ad2bd2` (`Use current listings for currency valuations`).
- Proyecto Google Cloud: `cactuar-gil-intelligence-8148`.
- Región de Cloud Run y Storage: `us-central1`.
- Dataset BigQuery: `cactuar_gil`, ubicación `US`.
- Imagen desplegada al cierre: `backend:v10`.
- Servicio: `cactuar-api`.
- Jobs: `cactuar-refresh` y `cactuar-archive`.
- Scheduler: 03:17 y 15:17, zona `America/Santiago`.
- Presupuesto configurado: CLP 5.000, alertas al 50%, 90% y 100%.
- La página continúa pública por decisión del usuario; la seguridad se abordará
  posteriormente.

El flujo vigente es:

```text
Universalis -> Cloud Run Job -> SQLite + BigQuery -> Cloud Run API -> GitHub Pages
```

## Funcionalidad disponible

### Conversiones

- Directorio buscable de más de 100 monedas, filtros y paginación.
- Incluye Poetics, scrips, Bicolor Gemstones y Storm/Serpent/Flame Seals.
- Ranking por gil neto por moneda y velocidad de venta.
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

- Compra sugerida en otros mundos de Aether y venta en Cactuar.
- Precio estresado, fee, ROI, ventas/día, persistencia y confianza explicable.
- Stock de la shortlist verificado mediante consultas detalladas.
- Optimizador de capital y cantidad recomendada.
- Son señales, no garantías; el precio debe confirmarse en el juego.

## Datos y frecuencia

- El catálogo estático v5 se extrajo desde los archivos locales `sqpack`; incluye
  categorías, recetas, ingredientes y Grand Company seals.
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

1. Confirmar que la próxima corrida programada publica `priceBasis=MIN_LISTING` y
   que no reaparece el promedio en conversiones.
2. Seguir acumulando historial antes de usar ML. La primera comparación debería ser
   contra las reglas actuales mediante backtesting, no un modelo desplegado a ciegas.
3. Diseñar inteligencia de lanzamiento por categorías usando ventanas equivalentes
   de expansiones anteriores.
4. Decidir si solicitar el snapshot histórico a Universalis o ejecutar un backfill
   progresivo del endpoint `/history`.
5. Evaluar una señal de profundidad de mercado: el listing mínimo es conservador
   frente a promedios inflados, pero una cantidad grande debería considerar varios
   niveles de listings.
6. Securitizar la página/API cuando el usuario lo solicite; por ahora debe seguir
   pública.
7. Revisar gasto real de Google Cloud después de varios días completos de operación;
   mantener Vertex AI deshabilitado mientras ML esté pospuesto.

## Verificación y operación

Pruebas locales:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

Estado al cierre: 35 pruebas exitosas.

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

## Punto recomendado para mañana

Comenzar revisando `/v1/health` y `/v1/dashboard`, comprobar el siguiente refresh
programado y luego elegir entre dos líneas de trabajo: profundidad de listings para
conversiones grandes o diseño del histórico de categorías de expansiones.
