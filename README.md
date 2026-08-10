# FFXIV Gil Intelligence

Dashboard público: https://psilvacompag.github.io/cactuar-gil-intelligence/

Backend público de sólo lectura: https://cactuar-api-mpkrb3h6wa-uc.a.run.app/

Sistema para analizar el Market Board, valorar conversiones de monedas y construir
señales de demanda para expansiones y parches.

La web tiene tres exploradores:

- **Conversiones:** recompensas comprables con monedas y su gil neto por moneda.
- **Mercado:** rankings buscables, historial de precio y rentabilidad de recetas para gathering y crafting.
- **Oportunidades:** cruces conservadores entre mundos de Aether, stock verificado y optimizador de capital para vender en Cactuar.

Las oportunidades son señales explicables, no garantías: aplican estrés de precio,
fee, liquidez, frescura y persistencia. La shortlist comprueba hasta 20 listings por
item y world; el precio debe confirmarse igualmente en el juego antes de comprar.

La recolección productiva se ejecuta dos veces al día en Google Cloud. SQLite
mantiene una ventana operativa de 14 snapshots y BigQuery conserva el histórico
analítico antes de cada poda. El catálogo de ítems y sus categorías se extrae de
los archivos locales del juego, incluidas recetas e ingredientes, sin requests
adicionales a servicios públicos. El ML permanece pospuesto hasta acumular historial
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

El probe C# compila con el SDK instalado y se ejecuta con el runtime incluido por XIVLauncher:

```powershell
dotnet build tools\local_data_probe\LocalDataProbe.csproj
$env:DOTNET_ROLL_FORWARD = "Major"
& "$env:APPDATA\XIVLauncher\runtime\dotnet.exe" tools\local_data_probe\bin\Debug\net8.0\LocalDataProbe.dll
```

Lee `sqpack`, no el proceso del juego. Las rutas detectadas en esta máquina pueden reemplazarse con `FFXIV_GAME_DIR`, `FFXIV_LUMINA_DIR` y `FFXIV_ALLAGAN_DIR`.

Arquitectura: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)  
Currency Exchange: [docs/CURRENCY_EXCHANGE.md](docs/CURRENCY_EXCHANGE.md)
Feasibility spike: [docs/FEASIBILITY.md](docs/FEASIBILITY.md)
