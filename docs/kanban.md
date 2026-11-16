# Tablero Kanban · StockTrack

El cliente exige Kanban (flujo continuo). Este documento define el tablero, sus políticas y el estado de las tarjetas
al momento de la entrega. Se puede copiar tal cual a Trello, Jira o GitHub Projects.

## Columnas y límites de trabajo en curso (WIP)

| Columna | Límite WIP | Regla de salida (definición de «listo» para pasar a la siguiente) |
|---|---|---|
| Backlog | — | Tarjeta con criterio de aceptación escrito |
| Listo para iniciar | 5 | Dependencias resueltas y alguien disponible |
| En desarrollo | 3 | Código escrito con sus pruebas automatizadas |
| En revisión / pruebas | 2 | Suite completa en verde y revisión de código hecha |
| Aceptación del cliente | 3 | Cliente registra «Aceptado» (hoja *Casos* del Excel de aceptación) |
| Hecho | — | Entregado y documentado |

**Políticas.** Se jala trabajo (no se empuja); si una columna llega a su límite, se ayuda a destrabar antes de tomar algo nuevo;
los defectos urgentes pasan al frente («carril expreso», máximo 1 a la vez); se mide *lead time* y se revisa cada semana.

## Estado de las tarjetas a la entrega

**Hecho (probado automáticamente; falta la aceptación del cliente)**

| # | Tarjeta | Evidencia |
|---|---|---|
| 1 | Modelo de datos y esquema SQLite/PostgreSQL | `stocktrack/schema/` |
| 2 | Productos: alta, edición, archivo, búsqueda, paginación | `tests/test_models.py` |
| 3 | Movimientos de inventario atómicos y trazables | PA-03.2, PA-03.3 |
| 4 | Alertas de escasez: notificación interna y correo SMTP | PA-02.1 … PA-02.5 |
| 5 | Reportes PDF y Excel (inventario y movimientos) | PA-01.1 … PA-01.5 |
| 6 | Usuarios y 3 roles (Administrador, Encargado, Consulta); bloqueo por intentos; inactividad | RN-01.1, RU-A/E/C, `tests/test_security.py` |
| 6b | Reservas de stock con validación del administrador; reportes foliados | RU-A, RU-E, PA-01 |
| 7 | Límite de 100,000 registros activos | RN-02.1, RN-02.2 |
| 8 | Concurrencia de 10 usuarios | PA-03.1 |
| 9 | Bitácora de auditoría | `models/audit.py` |
| 10 | Logo StockTrack (proporcionado por el cliente) | `stocktrack/static/img/` |
| 11 | Pruebas de aceptación: Excel y gráfica pptx | `docs/acceptance/` |

**En «Aceptación del cliente»:** los 35 casos de `docs/acceptance/StockTrack_Pruebas_de_Aceptacion.xlsx` (columna J).

**Backlog (no incluido en esta fase)**

| # | Tarjeta | Nota |
|---|---|---|
| 12 | Ejecutar la suite contra PostgreSQL y SMTP real | Requisito previo a producción |
| 13 | Despliegue con HTTPS y respaldos automáticos | Docker/compose incluidos, sin probar |
| 14 | Prueba de carga en el servidor real | La de PA-03 fue local, por loopback |
| 15 | Importación masiva de productos desde Excel/CSV | Útil para la carga inicial |
| 16 | Integración con ERP (API REST + eventos) | Extensión posible mencionada por el cliente |
| 17 | Recuperación de contraseña por correo | Hoy la restablece un administrador |

## Métricas sugeridas para la revisión semanal

*Lead time* (de «Listo» a «Hecho»), *throughput* (tarjetas por semana), edad del trabajo en curso y tasa de tarjetas que regresan
de revisión.
