# Operación en Google Cloud

## Arquitectura desplegada

- Proyecto: `cactuar-gil-intelligence-8148`.
- Región de cómputo y objetos: `us-central1`.
- Dataset analítico: BigQuery `US`, dataset `cactuar_gil`.
- Cloud Run service `cactuar-api`: entrega el dashboard público, sin acceso al SQLite.
- Cloud Run job `cactuar-refresh`: consulta Universalis, verifica stock de la shortlist, recalcula conversiones y publica el resultado.
- Cloud Storage privado: catálogo estático, SQLite operativo, dashboard generado y estado de ejecuciones.
- GitHub Pages: frontend estático, con fallback al último JSON incluido en el repositorio.

```text
Universalis -> Cloud Run Job -> SQLite + BigQuery -> Cloud Run API -> GitHub Pages
```

El catálogo estático se extrae desde `sqpack` sólo cuando cambia el parche. Cloud Run no accede a los archivos del juego.

## Política de requests

El job utiliza una conexión, un máximo de 1 request por segundo, timeout de 10 segundos y hasta dos reintentos acotados. Una carga completa requiere aproximadamente 170 requests agregados y 7 lotes detallados para la shortlist. La programación normal es dos veces al día, en minutos no redondos, con zona horaria `America/Santiago`.

El SQLite operativo conserva las últimas 14 corridas de Cactuar. Antes de podar,
cada snapshot se archiva idempotentemente en BigQuery. El job rechaza una corrida
si la cobertura, cantidad de conversiones, frescura o errores caen bajo los
umbrales de seguridad; un payload idéntico al anterior se registra como alerta.

## Objetos

```text
catalog/static_snapshot.json
state/gil_intelligence.sqlite3
public/dashboard.json
public/history.json
public/market-items.json
public/market-history.json
public/opportunities.json
public/signals.json
status/latest.json
runs/YYYY-MM-DD/{market_snapshot_id}.json
```

Todos los objetos permanecen privados. La API pública expone `GET /v1/dashboard`,
`GET /v1/history`, `GET /v1/market-items`, `GET /v1/market-history`,
`GET /v1/opportunities`, `GET /v1/signals` y `GET /v1/health`, con CORS limitado al origen de GitHub Pages
y a los orígenes locales de desarrollo. Health responde 503 cuando los datos de
mercado superan la edad máxima configurada.

## Despliegue reproducible

La imagen usa `Dockerfile` y sirve la API por defecto. El job reemplaza el comando por:

```text
python -m gil_intelligence.cloud.runner
```

Antes de cambiar el Scheduler se debe ejecutar el job manualmente y comprobar:

1. ejecución exitosa;
2. `requestCount` y `elapsedSeconds` plausibles;
3. actualización de `public/dashboard.json`;
4. respuesta 200 de `/v1/health`, `/v1/dashboard`, `/v1/market-history`, `/v1/opportunities` y `/v1/signals`;
5. carga primaria desde el backend en GitHub Pages.

## Costos y límites

El servicio usa escala a cero y el job se ejecuta dos veces al día. El presupuesto del proyecto es CLP 5.000 con alertas al 50%, 90% y 100%; las alertas no detienen automáticamente los recursos. Vertex AI permanece deshabilitado hasta contar con historial y un criterio de evaluación del modelo.
