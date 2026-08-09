# Feasibility spike — fuentes, cobertura y rate limits

Fecha: 2026-08-09  
Estado: extracción estática local y contratos públicos live confirmados

## Veredicto ejecutivo

| Capacidad | Factibilidad actual | Evidencia | Riesgo pendiente |
|---|---|---|---|
| Precio/mediana/velocidad por item | Alta | Universalis ofrece agregados y batches de hasta 100 IDs | Frescura crowdsourced |
| Historial de ventas | Alta | Endpoint histórico con ventanas y fecha de corte | Cobertura desigual por item/world |
| Leer catálogo estático del parche instalado | Alta | Lumina abrió 16/16 sheets desde `sqpack` | Revalidar después de cada parche |
| Extraer ofertas `SpecialShop` | Alta | 21.972 ofertas y 25.796 costos recorridos | Implementar persistencia y auditoría formal |
| Resolver Poetics y placeholders históricos | Alta | 2.963 costos de Poetics resueltos; self-test del resolver | Mantener reglas versionadas |
| Cubrir todas las familias de tienda | Media-alta | Todas las familias críticas existen y abren localmente | Falta un adapter normalizado por familia |
| Identificar items marketables | Alta | 16.843 candidatos locales y 16.843 IDs canónicos de Universalis | Revalidar por parche |
| Asociar tienda con NPC | Alta técnicamente | Índice inverso local construido | Muchas filas son internas, obsoletas o sin NPC directo |
| Coordenadas y requisitos completos | Media | `Level`, quest, content y festival están disponibles | Faltan joins y conversión a coordenadas de mapa |
| Persistir agregados del Market Board | Alta | Colector en batches de 100 y tablas SQLite con frescura | Ejecutar el primer snapshot completo |
| “Todas las conversiones” demostrable | Parcial | `SpecialShop` completo en memoria | Falta reconciliar el resto de familias y excepciones |

Conclusión: el proyecto es viable. Los datos estáticos pueden extraerse desde esta máquina sin red y sin rate limits. “Todas” seguirá siendo un porcentaje auditado: no se declarará cobertura total hasta normalizar y reconciliar cada familia de tienda. Los precios actuales sí requieren una fuente dinámica como Universalis.

## Evidencia confirmada

### Instalación local de FFXIV

El probe C# usa las bibliotecas Lumina ya instaladas por XIVLauncher y lee sólo los archivos estáticos del cliente; no se conecta al proceso del juego. Sobre la versión local `2026.08.05.0000.0000` confirmó:

| Medición | Resultado |
|---|---:|
| Sheets solicitadas/abiertas | 16/16 |
| Filas `Item` | 52.801 |
| Candidatos marketables por flags locales | 16.843 |
| Filas `SpecialShop` | 1.489 |
| Shops con ofertas | 1.215 |
| Grupos de oferta | 21.972 |
| Componentes de recompensa | 22.145 |
| Componentes de costo | 25.796 |
| Ofertas con costos múltiples | 3.638 |
| Monedas-placeholder convertidas a item real | 5.883 |
| Componentes de costo resueltos como Poetics | 2.963 |
| Shops enlazadas a NPC | 375 |
| NPC distintos enlazados | 252 |
| Shops con ubicación hallada en `Level` | 229 |

`CostType` no selecciona la moneda: entre otras propiedades, el valor `1` marca HQ. La conversión de IDs-placeholder depende de `SpecialShop.UseCurrencyType`, de `TomestonesItem` y de unas pocas excepciones históricas por shop. Esto se validó contra el resolvedor de AllaganLib instalado localmente y se reprodujo en el probe con cinco self-tests deterministas.

La baja cobertura bruta de NPC/ubicación no implica pérdida equivalente de ofertas: el conjunto contiene filas internas, antiguas y sub-shops incluidas por otras tiendas. La métrica útil de producción se calculará sobre ofertas activas y tras resolver `InclusionShop`/FATE shops.

Ventaja operativa: esta extracción estática no consume requests. Se ejecuta una vez por versión de juego y se guarda con el número de parche. AllaganLib se usó para validar semántica durante el spike; el producto tendrá reglas propias versionadas para no depender de un plugin concreto.

### XIVAPI

El OpenAPI actual confirma:

- `GET /api/version` para enumerar versiones.
- `GET /api/sheet` para enumerar sheets.
- `GET /api/sheet/{sheet}` con `limit`, `after`, `version`, `schema` y selección de fields.
- Respuestas con versión y schema canónicos.
- Paginación por último row ID; los IDs no son necesariamente contiguos.

La documentación advierte que v2 no expone los reverse relationships computados de v1. Construiremos índices inversos localmente.

El schema de `SpecialShop` inspeccionado confirma:

- Hasta 60 grupos de ofertas por fila.
- Hasta 2 recompensas por grupo.
- Hasta 3 componentes de costo.
- Cantidades, HQ y collectability.
- Relaciones a item, quest, achievement, content y festival.
- `CostType` con semántica sólo parcialmente documentada.

El schema de `ENpcBase` contiene 32 entradas `ENpcData` por NPC y relaciones polimórficas a `SpecialShop`, `GCShop`, `GilShop`, `InclusionShop`, `CollectablesShop`, `DisposalShop`, `FccShop`, `LotteryExchangeShop` y otros handlers. Esto hace posible construir `shop -> NPC`, pero exige escanear `ENpcBase` porque XIVAPI v2 no hace la consulta inversa.

Referencias:

- [XIVAPI OpenAPI](https://v2.xivapi.com/api/openapi.json)
- [Lectura de sheets](https://v2.xivapi.com/docs/guides/sheets/)
- [Versionado](https://v2.xivapi.com/docs/guides/pinning/)
- [Migración v1 → v2](https://v2.xivapi.com/docs/migrate/)
- [EXDSchema `SpecialShop`](https://github.com/xivdev/EXDSchema/blob/75f674655bb89d6172effa3a5a2d93bcfc7deb51/SpecialShop.yml)
- [EXDSchema `ENpcBase`](https://github.com/xivdev/EXDSchema/blob/75f674655bb89d6172effa3a5a2d93bcfc7deb51/ENpcBase.yml)

### Universalis

La documentación confirma:

- Límite de 25 req/s, burst 50 y máximo 8 conexiones simultáneas por IP.
- Batches de hasta 100 item IDs.
- Endpoint agregado preferido cuando no se necesitan listings individuales.
- Precio mínimo/mediano, compra reciente, precio promedio y velocidad diaria.
- Endpoints separados para listings actuales, historial y catálogo marketable.

Referencia: [Universalis REST API](https://docs.universalis.app/).

## Prueba live desde este entorno

Comando:

```powershell
python tools/probe_sources.py --live --scope Aether --timeout 10 --rps 2 --retries 2
```

Resultado del 9 de agosto de 2026:

- XIVAPI: conexión `PASS`; 42 versiones, 7.912 sheets y las 10 familias críticas presentes. El resultado global queda en `WARN` porque el descubrimiento conservador detecta 98 sheets relacionadas aún no clasificadas.
- Universalis: `PASS`; Data Center `Aether` encontrado, 16.843 IDs marketables y respuesta agregada válida para el batch de muestra.
- Versión XIVAPI observada: `c3f948214b90e498`.
- Schema XIVAPI observado: `exdschema@2:rev:cf037c37eff351db4d1ca5952e10cc08c131b828`.

La red ya no es un bloqueo para desarrollar ni ejecutar la ingesta. Los resultados live siguen siendo evidencia fechada: cada ejecución debe guardar procedencia, scope y frescura, porque ambas APIs y el catálogo del juego evolucionan.

## Presupuesto de requests

Conteo live observado:

- 16.843 items marketables.
- Batches de 100.
- 1 req/s por la política operativa actual, muy por debajo del máximo publicado de Universalis. El spike inicial se midió con un máximo configurado de 2 req/s.
- 4 snapshots globales al día.
- Top 1.000 candidatos cada 30 minutos.

| Trabajo | Requests |
|---|---:|
| Un snapshot de todo el catálogo | 169 |
| Tiempo mínimo teórico con el límite inicial de 2 req/s | 84,5 segundos |
| Tiempo mínimo teórico con el límite operativo de 1 req/s | 169 segundos |
| Primera carga completa observada | 341,9 segundos |
| Cuatro snapshots globales/día | 676/día |
| Top 1.000 cada 30 minutos | 480/día |
| Total conservador | 1.156/día |

Son 9,63 minutos mínimos de rate-limit distribuidos en 24 horas, un promedio aproximado de 0,013 req/s. La primera carga completa tardó 341,9 segundos debido a la latencia de las 169 respuestas secuenciales; el límite de Universalis no parece un problema para agregados, pero la duración operativa debe medirse y no inferirse sólo desde el rate limit.

Listings completos son otra carga y no se incluirán globalmente. Se consultarán sólo para candidatos, respetando `lastUploadTime` y cache.

XIVAPI se usa principalmente al cambiar parche:

- Inventario de sheets: una petición.
- Catálogo de tiendas: paginado por familia.
- Items/NPC/estructuras: descarga versionada y cacheada.
- Entre parches no se repite el crawl estático.

No se encontró un límite numérico público de XIVAPI v2 en la documentación revisada. El cliente comienza en 2 req/s, una conexión, usa backoff ante 429 y respeta `Retry-After`; se ajustará después del probe live.

## Código entregado por el spike

- `tools/probe_sources.py`: CLI dry-run/live.
- `src/gil_intelligence/probes/http.py`: cliente JSON con throttling, timeout, User-Agent y retry 429.
- `src/gil_intelligence/probes/runner.py`: inventario de sheets, shapes de tiendas y comprobación de Universalis.
- `src/gil_intelligence/probes/budget.py`: estimador de carga.
- `src/gil_intelligence/collectors/universalis.py`: colector agregado con batches de hasta 100 IDs.
- `src/gil_intelligence/storage/market_catalog.py`: persistencia SQLite de NQ/HQ, DC/región, fallos y frescura.
- `tools/collect_market_snapshot.py`: CLI para snapshots parciales o del catálogo marketable completo.
- `tests/`: pruebas unitarias de budgets, throttling, retry headers, descubrimiento y shapes.
- `tools/local_data_probe/`: lector C# de `sqpack`, inventario de sheets, resolvedor de monedas, joins NPC/ubicación y self-tests.

El probe live no descarga todo. Primero valida contratos y toma una fila por sheet encontrada. Después de esa evidencia se implementa el crawler exhaustivo.

## Gates antes de construir adapters completos

1. Persistir el resultado local versionado en tablas normalizadas.
2. Implementar adapters para `GCShop`, `GCScripShopItem`, `InclusionShop`, `CollectablesShop`, `FccShop`, `DisposalShop`, `LotteryExchangeShop`, `GilShop` y tomestones.
3. Resolver inclusión/FATE shops, nombres, requisitos y coordenadas de mapa.
4. Reconciliar cada fila como `offers + ignored + exceptions` y publicar métricas de cobertura.
5. ~~Confirmar marketability con Universalis cuando haya un runtime con red.~~ Confirmado: 16.843 IDs el 9 de agosto de 2026.
6. ~~Ejecutar y auditar el primer snapshot agregado completo.~~ Confirmado: 16.843 resultados, 0 fallos y `PRAGMA integrity_check = ok`.
7. Probar el cruce de monedas con precios live y frescura real.
8. Sólo entonces afirmar un porcentaje final de cobertura.
