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

La página `projections.html` apunta a Evercold 8.0 y separa dos conceptos que no deben
confundirse:

- los ítems históricos enseñan un rol de demanda repetible;
- sólo un equivalente actual explícitamente validado puede aparecer como candidato.

Ya no existe matching abierto por categorías como `Leather`, `Cloth` o `Metal`. Esa
regla hacía aparecer el material antiguo que había funcionado, en vez del activo que
podría cumplir su rol en 8.0. El mapping v2 limita el radar previo al lanzamiento a
insumos comprables hoy con una tesis repetible: cristales/clusters persistentes,
Materia XI como posible grado económico de overmeld y el puente de spiritbond. Los
materiales nuevos de monstruos/FATE, leves y precrafts permanecen diferidos hasta que
8.0 revele sus item IDs.

El puntaje suma repetibilidad histórica, ajuste del equivalente actual, uso en recetas
7.4–7.5, aceleración de demanda, precio, liquidez, estabilidad y muestras. Resta
puntos por enfriamiento y volatilidad. No extrapola un precio futuro ni presenta una
probabilidad estadística. El equipo inicial de Bastion y physical ranged permanece
fuera mientras no se aclare cómo el Armoury Update afectará esa demanda histórica.

La página `snipes.html` busca el caso inverso: un listing mínimo anormalmente bajo.
La referencia es el menor valor entre la mediana histórica de listings y la mediana
de ventas. Requiere al menos tres snapshots, 25% de descuento, actividad y margen
después del fee; para ítems muy volátiles exige 50% de descuento. Hasta verificar
el stock detallado, cada resultado es sólo una alerta para comprobar dentro del
juego.
