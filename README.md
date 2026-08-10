# FFXIV Gil Intelligence

Dashboard público: https://psilvacompag.github.io/cactuar-gil-intelligence/

Backend público de sólo lectura: https://cactuar-api-mpkrb3h6wa-uc.a.run.app/

Sistema para analizar el Market Board, valorar conversiones de monedas y construir
señales de demanda para expansiones y parches.

La web tiene seis exploradores:

- **Conversiones:** recompensas comprables con una o varias monedas, con gil neto
  por moneda o por canje completo según corresponda.
- **Mercado:** rankings buscables, historial de precio y rentabilidad de recetas para gathering y crafting.
- **Oportunidades:** cruces conservadores entre los 32 Worlds de North America, stock verificado y optimizador de capital para vender en Cactuar.
- **Proyecciones:** candidatos actuales para Evercold 8.0. Los ganadores históricos
  definen roles repetibles y una regla explícita busca el equivalente vigente; los
  ítems antiguos no entran sólo por compartir categoría.
- **Snipeos:** caídas anómalas del listing mínimo frente a referencias históricas;
  exige descuento, margen, actividad y al menos tres snapshots.
- **Hoy:** resumen accionable de Conversiones, Mercado, Oportunidades, Proyecciones
  y Snipeos, con calidad de datos, planes concretos y resultados medidos a 7, 30 y
  90 días.

Las seis vistas comparten búsqueda global, ficha universal por ítem, etiquetas de
calidad y minigráficos de historial real. La lista básica de favoritos permanece
local al navegador; reglas avanzadas, notas, límites y sincronización quedan como
TODO explícito.

Las oportunidades son señales explicables, no garantías: aplican estrés de precio,
fee, liquidez, frescura y persistencia. La shortlist comprueba hasta 20 listings por
item y world; el precio debe confirmarse igualmente en el juego antes de comprar.
Las conversiones mejor rankeadas muestrean además hasta 20 listings de Cactuar para
medir competencia cerca del piso y días de oferta al ritmo de ventas observado.
Los canjes que exigen varias monedas conservan el paquete completo: por ejemplo,
`5 Bozjan Gold Coin + 30 Bozjan Platinum Coin` se valora como un solo canje y nunca
se atribuye todo el retorno a una moneda aislada.

La recolección productiva se ejecuta dos veces al día en Google Cloud. SQLite
mantiene una ventana operativa de 14 snapshots y BigQuery conserva el histórico
analítico antes de cada poda. Cada refresh vuelve a calcular automáticamente las
reglas de los cinco módulos y persiste sus observaciones en el ledger; la watchlist
del usuario permanece privada en su navegador. El catálogo de ítems, iconos,
categorías, recetas e ingredientes se extrae de los archivos locales del juego sin
requests de catálogo adicionales. El navegador convierte las rutas de textura en PNG
mediante XIVAPI v2 y conserva un SVG minimalista como fallback. El ML permanece pospuesto hasta acumular historial
suficiente para medirlo contra estas reglas deterministas.

## Ejecutar pruebas locales

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

## Ejecutar el probe contra APIs reales

```powershell
python tools/probe_sources.py --live --scope Aether
```

El probe usa por defecto 2 requests por segundo, una sola conexión, timeout acotado y reintentos limitados. No descarga todas las tiendas ni todo el Market Board: verifica descubrimiento, shapes, paginación y calcula el presupuesto de una carga completa.

## Guardar un snapshot de mercado

Validación pequeña con tres items:

```powershell
python tools/collect_market_snapshot.py --scope Aether --item-ids 2,3,4
```

Snapshot de todos los items marketables (169 lotes para el catálogo observado el 9 de agosto de 2026):

```powershell
python tools/collect_market_snapshot.py --scope Aether --all-marketable
```

El destino por defecto es `data/gil_intelligence.sqlite3`. Se conservan por separado NQ/HQ, nivel DC/región, fallos reportados por la fuente y frescura por world.

## Actualizar mercado y conversiones

```powershell
python tools/refresh_market_and_values.py --scope Aether
```

En producción, Google Cloud ejecuta el refresh dos veces al día. También se puede
ejecutar manualmente para desarrollo. El conteo observado de requests y los
límites operativos están en [docs/OPERATIONS.md](docs/OPERATIONS.md); el despliegue
se describe en [docs/CLOUD_OPERATIONS.md](docs/CLOUD_OPERATIONS.md) y el análisis
por categorías en [docs/EXPANSION_INTELLIGENCE.md](docs/EXPANSION_INTELLIGENCE.md).

Para el perfil configurado actualmente:

```powershell
python tools/refresh_market_and_values.py --scope Cactuar
python -m http.server 8000 --directory apps/web
```

El dashboard queda disponible localmente en `http://localhost:8000`.

## Verificar los datos estáticos locales

El probe C# usa .NET 10, igual que la versiÃ³n actual de Lumina incluida por XIVLauncher:

```powershell
$dotnet = Join-Path $env:LOCALAPPDATA "CactuarDotnet\dotnet.exe"
& $dotnet build tools\local_data_probe\LocalDataProbe.csproj
& $dotnet tools\local_data_probe\bin\Debug\net10.0\LocalDataProbe.dll
```

Lee `sqpack`, no el proceso del juego. Las rutas detectadas en esta máquina pueden reemplazarse con `FFXIV_GAME_DIR`, `FFXIV_LUMINA_DIR` y `FFXIV_ALLAGAN_DIR`.

Arquitectura: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)  
Currency Exchange: [docs/CURRENCY_EXCHANGE.md](docs/CURRENCY_EXCHANGE.md)
Feasibility spike: [docs/FEASIBILITY.md](docs/FEASIBILITY.md)
Memoria para retomar: [docs/SESSION_HANDOFF.md](docs/SESSION_HANDOFF.md)
