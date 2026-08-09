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

Durante desarrollo, todos los jobs son manuales. La frecuencia objetivo para producción local es:

| Job | Frecuencia normal | Requests aproximados |
|---|---:|---:|
| Snapshot agregado completo | Cada 6 horas | 170 por ejecución / 680 al día |
| Catálogo estático local | Sólo al cambiar versión del juego | 0 requests públicos |
| Valorar conversiones | Después de cada snapshot | 0 requests adicionales |
| Candidatos prioritarios | Pendiente, 30–60 minutos | Se añadirá cuando exista ranking estable |

Los 680 requests diarios equivalen a un promedio de 0,008 requests/s. Se programará en minutos no redondos (por ejemplo 00:17, 06:17, 12:17 y 18:17) y nunca se permitirán dos refresh simultáneos.

## Ejecución

Manual, mercado más valoración:

```powershell
python tools/refresh_market_and_values.py --scope Aether
```

El comando usa un lock local para evitar solapamientos, guarda telemetría de requests/duración en SQLite y reconstruye las conversiones con `RECENT_AVG_SALE`, fee configurable de 5%, frescura de 24 horas y una velocidad mínima visible de 0,1 ventas/día.

Cuando confirmemos que el ranking es útil, este mismo comando se registrará en Windows Task Scheduler cada seis horas. La tarea aún no está instalada: no hay automatización oculta ejecutándose en el equipo.
