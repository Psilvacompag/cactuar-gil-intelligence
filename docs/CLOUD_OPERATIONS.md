# Operación en Google Cloud

## Arquitectura desplegada

- Proyecto: `cactuar-gil-intelligence-8148`.
- Región de cómputo y objetos: `us-central1`.
- Dataset analítico: BigQuery `US`, dataset `cactuar_gil`.
- Cloud Run service `cactuar-api`: entrega el dashboard público, sin acceso al SQLite.
- Cloud Run job `cactuar-refresh`: consulta Universalis, recalcula conversiones y publica el resultado.
- Cloud Storage privado: catálogo estático, SQLite operativo, dashboard generado y estado de ejecuciones.
- GitHub Pages: frontend estático, con fallback al último JSON incluido en el repositorio.

```text
Universalis -> Cloud Run Job -> bucket privado -> Cloud Run API -> GitHub Pages
```

El catálogo estático se extrae desde `sqpack` sólo cuando cambia el parche. Cloud Run no accede a los archivos del juego.

## Política de requests

El job utiliza una conexión, un máximo de 1 request por segundo, timeout de 10 segundos y hasta dos reintentos acotados. Una carga completa requiere aproximadamente 170 requests. La programación normal es dos veces al día, en minutos no redondos, con zona horaria `America/Santiago`.

El SQLite operativo conserva las últimas 14 corridas de Cactuar. Las páginas liberadas se reutilizan para evitar crecimiento ilimitado. El historial analítico de largo plazo se incorporará a BigQuery antes de la etapa de entrenamiento.

## Objetos

```text
catalog/static_snapshot.json
state/gil_intelligence.sqlite3
public/dashboard.json
status/latest.json
runs/YYYY-MM-DD/{market_snapshot_id}.json
```

Todos los objetos permanecen privados. La API pública sólo expone `GET /v1/dashboard` y `GET /v1/health`, con CORS limitado al origen de GitHub Pages y a los orígenes locales de desarrollo.

## Despliegue reproducible

La imagen usa `Dockerfile` y sirve la API por defecto. El job reemplaza el comando por:

```text
python -m gil_intelligence.cloud.runner
```

Antes de cambiar el Scheduler se debe ejecutar el job manualmente y comprobar:

1. ejecución exitosa;
2. `requestCount` y `elapsedSeconds` plausibles;
3. actualización de `public/dashboard.json`;
4. respuesta 200 de `/v1/health` y `/v1/dashboard`;
5. carga primaria desde el backend en GitHub Pages.

## Costos y límites

El servicio usa escala a cero y el job se ejecuta dos veces al día. El presupuesto del proyecto es CLP 5.000 con alertas al 50%, 90% y 100%; las alertas no detienen automáticamente los recursos. Vertex AI permanece deshabilitado hasta contar con historial y un criterio de evaluación del modelo.
