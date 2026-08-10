# Roadmap

## Activo: Mi radar

- Favoritos privados sincronizados por cuenta, sin importar datos desde `localStorage`.
- Objetivos personales de compra y venta, capital máximo, notas y World preferido.
- Estados automáticos: comprar, salida lista, vigilar, enfriándose, fuera de precio y sin datos.
- Historial privado desde que el ítem entra al radar.
- Alertas dentro de la página y notificaciones del navegador mientras la página está abierta.
- Reevaluación automática después de cada actualización de mercado.

## Segunda etapa: documentada, todavía no activa

1. **Notificaciones con la página cerrada.** Web Push o correo con suscripción explícita, control de frecuencia y deduplicación.
2. **Auditoría administrativa.** Registro consultable de altas, suspensiones, cambios de rol y accesos, sin exponer reglas privadas del radar.
3. **Mayor frecuencia para snipeos.** Pipeline corto independiente del refresh general, sujeto a presupuesto y límites responsables de Universalis.
4. **Evaluación real de señales.** Medir automáticamente cada recomendación contra resultados posteriores, por ventana temporal, costos, fees y liquidez.
5. **ML con historial suficiente.** Entrenar sólo después de definir un benchmark temporal sin fuga de datos y exigir que supere las reglas deterministas fuera de muestra.

La segunda etapa no debe presentarse como disponible hasta contar con implementación, pruebas y operación productiva verificadas.
