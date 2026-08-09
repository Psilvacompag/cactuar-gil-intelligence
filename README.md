# FFXIV Gil Intelligence

Dashboard público: https://psilvacompag.github.io/cactuar-gil-intelligence/

Sistema local-first para analizar el Market Board, valorar conversiones de monedas y, más adelante, generar recomendaciones y señales de expansiones/parches.

El repositorio se encuentra en una etapa de factibilidad. Ya incluye pruebas de contratos HTTP, un extractor que lee las tablas estáticas del parche instalado localmente y persistencia de agregados live de Universalis.

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

Actualmente se ejecuta de forma manual. La política propuesta para Windows Task Scheduler, el conteo observado de requests y los límites operativos están en [docs/OPERATIONS.md](docs/OPERATIONS.md).

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
