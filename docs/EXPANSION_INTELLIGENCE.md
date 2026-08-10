# Inteligencia de lanzamientos

## Qué queda medido

Cada snapshot de Universalis se conserva en BigQuery con precio, calidad, nivel
geográfico y velocidad diaria de venta por ítem. El catálogo `sqpack` agrega la
categoría de Market Board (`ItemSearchCategory`) y la categoría de interfaz
(`ItemUICategory`) sin hacer requests externos adicionales.

La consulta [`sql/expansion_category_rank.sql`](sql/expansion_category_rank.sql)
recibe el mundo y la fecha de lanzamiento. Compara los 28 días previos con los
primeros 14 días, ordena las categorías por velocidad observada y calcula su
multiplicador frente a la línea base.

## Interpretación

`daily_sale_velocity` es la estimación agregada que entrega Universalis en el
momento del snapshot y se calcula sobre las ventas de los últimos cuatro días.
Sirve para detectar cambios de demanda y ordenar ítems o categorías, pero no
equivale a un libro completo de transacciones. Para contar ventas exactas se
necesitaría recolectar además el historial incremental de ventas y deduplicarlo
por transacción.

El histórico propio empieza con la primera ejecución archivada. No se deben
presentar ventanas de expansiones anteriores como datos observados si BigQuery
no contiene snapshots de esas fechas. La misma consulta sí sirve para el próximo
lanzamiento porque ya estamos construyendo su línea base desde ahora.

## Uso

En la consola de BigQuery, pegar la consulta y crear dos parámetros:

- `scope` (STRING), por ejemplo `Cactuar`.
- `launch_at` (TIMESTAMP), con la fecha oficial cuando Square Enix la publique.

Para profundizar, se reemplaza la selección final por una agrupación a nivel de
`item_id`; así se obtienen los ítems que explican el crecimiento de cada categoría.

## Radar web actual

La página `projections.html` usa reglas deterministas y recalculables. Suma señales
de aceleración de demanda, precio, liquidez, estabilidad, cantidad de snapshots y
coincidencias con la evidencia curada de lanzamientos. Resta puntos por enfriamiento
y volatilidad. No extrapola un precio futuro ni presenta probabilidad estadística.

La página `snipes.html` busca el caso inverso: un listing mínimo anormalmente bajo.
La referencia es el menor valor entre la mediana histórica de listings y la mediana
de ventas. Requiere al menos tres snapshots, 25% de descuento, actividad y margen
después del fee; para ítems muy volátiles exige 50% de descuento. Hasta verificar
el stock detallado, cada resultado es sólo una alerta para comprobar dentro del
juego.
