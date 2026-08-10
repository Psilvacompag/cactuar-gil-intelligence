# Evidencia histórica de lanzamientos

La primera base curada vive en
[`docs/data/expansion_launch_evidence.json`](data/expansion_launch_evidence.json).
Se diseñó para complementar, no sustituir, el histórico cuantitativo.

## Criterio

- `COMMUNITY_OBSERVED`: reporte contemporáneo de precio, volumen o demanda.
- `COMMUNITY_RETROSPECTIVE`: recuerdo posterior; se conserva con menor confianza.
- `OFFICIAL_RECIPE_DEMAND`: una receta oficial demuestra necesidad estructural, no
  ventas completadas.
- Cada entrada conserva expansión, fase, fecha, fuente y confianza. No se convierte
  un autorreporte de Reddit en un promedio global.

Las fases importan más que una etiqueta genérica de lanzamiento:

```text
launch_0_72h -> launch_leveling -> pre_savage -> savage_day -> savage_week_1
```

## Cobertura y siguiente extracción

- Dawntrail: Universalis todavía devuelve ventas de junio-julio de 2024. Conviene
  cuantificar primero los ítems de esta lista para Aether y separar Cactuar mediante
  `worldID=79`.
- Endwalker: el API público no devolvió ventas de diciembre de 2021 en una prueba
  con ítems básicos; el corte observado no es una garantía oficial de retención.
- Shadowbringers y Endwalker quedan como evidencia manual hasta obtener un dump o
  una fuente histórica reproducible.

Al descargar historia de Universalis se deben eliminar nombres de compradores y
guardar únicamente transacciones, unidades, gil, precio ponderado, mediana y
ventas por día observado.
