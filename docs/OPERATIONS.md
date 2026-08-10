# Operación y frecuencia

Estado al 9 de agosto de 2026.

## Requests observados

El primer snapshot completo exitoso de Aether hizo:

- 1 request a `/api/v2/marketable`.
- 169 requests a `/api/v2/aggregated/Aether/{hasta 100 IDs}`.
- Total: 170 requests HTTP sin concurrencia.
- Los 169 lotes agregados tardaron 341,9 segundos: 0,49 requests/s efectivos.

La duración registrada no incluyó la primera consulta de catálogo, que fue breve. Hubo un intento completo anterior que expiró por el timeout externo de la herramienta; como ocurrió antes de añadir telemetría por job, su conteo exacto queda deliberadamente como desconocido.

La documentación pública de Universalis permite 25 requests/s, burst de 50 y 8 conexiones por IP. El proyecto usa por defecto una conexión y un máximo de 1 inicio de request/s, además de un `User-Agent` identificable.

## Frecuencia elegida

El backend de producción se ejecuta en Google Cloud dos veces al día:

| Job | Frecuencia normal | Requests aproximados |
|---|---:|---:|
| Snapshot agregado completo | Cada 12 horas | ~170 por ejecución / ~340 al día |
| Stock detallado de la shortlist | En la misma ejecución | ~1 lote por world de origen, normalmente 7 |
| Catálogo estático local | Sólo al cambiar versión del juego | 0 requests públicos |
| Valorar conversiones | Después de cada snapshot | 0 requests adicionales |

El total esperado queda cerca de 177 requests por corrida, o 354 diarios. Los
detalles se consultan sólo para los candidatos que ya superaron margen, liquidez
y frescura; se piden hasta 20 listings, sin historial de ventas duplicado. Aun
incluyendo esos lotes, el promedio diario es inferior a 0,005 requests/s. Cloud
Scheduler ejecuta a las 03:17 y 15:17 en `America/Santiago`. El Cloud Run Job usa
una tarea, paralelismo 1 y cero reintentos del job completo.

La primera ejecución cloud del 9 de agosto de 2026 obtuvo 170 respuestas exitosas en 171 intentos —una solicitud necesitó retry— y 423 segundos de recolección. La ejecución completa, incluido el aprovisionamiento, terminó en 9 minutos y 5 segundos.

## Ejecución

Manual, mercado más valoración:

```powershell
python tools/refresh_market_and_values.py --scope Aether
```

El comando usa un lock local para evitar solapamientos, guarda telemetría de requests/duración en SQLite y reconstruye las conversiones con `RECENT_AVG_SALE`, fee configurable de 5%, frescura de 24 horas y una velocidad mínima visible de 0,1 ventas/día.

La ejecución local sigue siendo manual y no existe una tarea oculta en Windows. La automatización vive únicamente en Cloud Scheduler y publica el resultado mediante el backend documentado en [CLOUD_OPERATIONS.md](CLOUD_OPERATIONS.md).
