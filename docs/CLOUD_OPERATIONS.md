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

El catálogo estático se extrae desde `sqpack` sólo cuando cambia el parche. Cloud Run no accede a los archivos del juego. El esquema 6 incluye `iconId`; GitHub Pages solicita la conversión PNG directamente al endpoint de assets de XIVAPI, con caché del navegador y fallback SVG local.

La valoración conserva canjes con múltiples costos como un paquete indivisible. El
dashboard publica el listing y gil neto del canje completo, junto con cada moneda
requerida; no divide arbitrariamente el retorno entre sus componentes. Los canjes
no comerciables se cuentan para auditoría, pero no se presentan como oportunidad
de gil.

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

Todos los objetos permanecen privados. Sin autenticación solo se exponen
`GET /v1/health`, `GET /v1/auth/config`, la raíz descriptiva y el registro de sesión.
`GET /v1/dashboard`, `GET /v1/history`, `GET /v1/market-items`,
`GET /v1/market-history`, `GET /v1/opportunities` y `GET /v1/signals` exigen un
Firebase ID token perteneciente a una cuenta `ACTIVE`. `/v1/admin/*` exige además el
rol `ADMIN`. CORS queda limitado al origen de GitHub Pages y a los orígenes locales
configurados. Health responde 503 cuando los datos de mercado superan la edad máxima.

## Usuarios, favoritos y secretos

- Google autentica a los usuarios mediante Firebase Authentication.
- El primer administrador se define con `CACTUAR_BOOTSTRAP_ADMIN_EMAIL`; una cuenta
  nueva parte `PENDING` hasta que un administrador la aprueba.
- La interfaz permanece completamente cubierta por el gate de autenticación hasta
  confirmar una cuenta `ACTIVE`; no hay flash de tablas durante el arranque.
- El artefacto de GitHub Pages excluye los snapshots estáticos de mercado. Solo
  conserva `launch-signals.json`, que contiene reglas históricas sin precios actuales.
- Firestore guarda `cactuar_users/{uid}`, la subcolección privada `favorites` y el
  historial de cada regla bajo `favorites/{favorite}/history`.
- Los favoritos históricos del navegador se eliminan y no se importan.
- Cloud Run usa Application Default Credentials; no existen archivos JSON de cuenta
  de servicio ni llaves privadas.
- La configuración web de Firebase se inyecta desde el secreto
  `cactuar-firebase-web-config`. No se guarda en Git. Aunque el API key web se entrega
  necesariamente al navegador en runtime, la autorización efectiva depende del ID
  token verificado y del estado/rol almacenado por el servidor.

## Despliegue reproducible

La imagen usa `Dockerfile` y sirve la API por defecto. El job reemplaza el comando por:

```text
python -m gil_intelligence.cloud.runner
```

El job productivo define `CACTUAR_RADAR_HISTORY_ENABLED=true`. Después de publicar
los artefactos, registra de forma idempotente un punto por favorito usando el ID del
snapshot. Un fallo al escribir este historial se registra como warning y no invalida
el refresh de mercado.

Antes de cambiar el Scheduler se debe ejecutar el job manualmente y comprobar:

1. ejecución exitosa;
2. `requestCount` y `elapsedSeconds` plausibles;
3. actualización de `public/dashboard.json`;
4. respuesta 200 de `/v1/health`, `/v1/dashboard`, `/v1/market-history`, `/v1/opportunities` y `/v1/signals`;
5. carga primaria desde el backend en GitHub Pages.

## Costos y límites

El servicio usa escala a cero y el job se ejecuta dos veces al día. El presupuesto del proyecto es CLP 5.000 con alertas al 50%, 90% y 100%; las alertas no detienen automáticamente los recursos. Vertex AI permanece deshabilitado hasta contar con historial y un criterio de evaluación del modelo.
