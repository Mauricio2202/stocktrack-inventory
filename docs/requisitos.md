# Trazabilidad de requerimientos

Fuente: «Requerimientos por usuario – StockTrack». Generado a partir de `tests/acceptance/`; los casos son de `docs/acceptance/StockTrack_Pruebas_de_Aceptacion.xlsx`.

## Requerimientos funcionales

| ID | Rol | Requerimiento | Casos de prueba |
|---|---|---|---|
| RF-01 | Administrador | Inicio de sesión por correo y contraseña | RU-A.1 |
| RF-02 | Administrador | Dashboard administrativo | RU-A.1 |
| RF-03 | Administrador | Gestión de usuarios (registrar, consultar, modificar, desactivar) | RU-A.2 |
| RF-04 | Administrador | Gestión de roles y permisos | RN-01.1, RU-A.2 |
| RF-05 | Administrador | Registro de productos | RU-A.3 |
| RF-06 | Administrador | Modificación de productos | RU-A.3 |
| RF-07 | Administrador | Desactivación de productos | RU-A.3 |
| RF-08 | Administrador | Gestión de categorías | RU-A.3 |
| RF-09 | Administrador | Configuración de stock mínimo | RU-A.3 |
| RF-10 | Administrador | Consulta de inventario | RU-A.5 |
| RF-11 | Administrador | Consulta de movimientos | RU-A.5 |
| RF-12 | Administrador | Supervisión de alertas | RU-A.5 |
| RF-13 | Administrador | Reportes generales de inventario y movimientos (4 tipos de movimiento) | RU-A.6 |
| RF-14 | Administrador | Exportación PDF y Excel, 4 tipos de reporte, foliados e incorruptibles | RU-A.6, RU-A.7 |
| RF-15 | Administrador | Historial de actividades | RU-A.5 |
| RF-16 | Administrador | Validación de reservas de stock (segundo nivel) | RU-A.4 |
| RF-17 | Encargado | Inicio de sesión | RU-E.1 |
| RF-18 | Encargado | Dashboard de inventario | RU-E.1 |
| RF-19 | Encargado | Consulta de productos | RU-E.1 |
| RF-20 | Encargado | Consulta de existencias | RU-E.1 |
| RF-21 | Encargado | Registro de entradas (Entrada por Compra) | RU-E.2 |
| RF-22 | Encargado | Registro de salidas (Venta, Devolución, Reserva segundo nivel) | RU-E.2 |
| RF-23 | Encargado | Validación de existencias antes de una salida | RU-E.2 |
| RF-24 | Encargado | Actualización automática del inventario | RU-E.2 |
| RF-25 | Encargado | Consulta de movimientos | RU-E.2 |
| RF-26 | Encargado | Consulta de alertas | RU-E.3 |
| RF-27 | Encargado | Atención de alertas | RU-E.3 |
| RF-28 | Encargado | Reportes generales foliados e incorruptibles | RU-A.7, RU-E.4 |
| RF-29 | Consulta | Inicio de sesión | RU-C.1 |
| RF-30 | Consulta | Dashboard de consulta | RU-C.1 |
| RF-31 | Consulta | Consulta de productos | RU-C.2 |
| RF-32 | Consulta | Búsqueda por nombre, código, marca o categoría | RU-C.2 |
| RF-33 | Consulta | Consulta de categorías | RU-C.2 |
| RF-34 | Consulta | Consulta de existencias | RU-C.2 |

## Requerimientos no funcionales

| ID | Categoría | Requerimiento | Casos / evidencia |
|---|---|---|---|
| RNF-01 | Seguridad | Autenticación por correo y contraseña | RU-A.1 |
| RNF-02 | Seguridad | Contraseñas con hash seguro | — |
| RNF-03 | Seguridad | Control de acceso por rol | RN-01.1, RU-C.1 |
| RNF-04 | Seguridad | Cierre de sesión por inactividad configurable | RNF.1 |
| RNF-05 | Seguridad | Protección contra accesos no autorizados | RN-01.1, RNF.1 |
| RNF-06 | Rendimiento | 10 usuarios simultáneos | PA-03.1 |
| RNF-07 | Rendimiento | Consultas en máximo 3 s | PA-03.1, RN-02.2 |
| RNF-08 | Rendimiento | Movimientos en máximo 3 s | PA-03.1 |
| RNF-09 | Rendimiento | Reportes en tiempo razonable | PA-01.1, PA-01.2, RN-02.2 |
| RNF-10 | Usabilidad | Interfaz intuitiva y navegación entre módulos | RNF.5; Revisión de diseño: menú lateral por rol; validar con usuarios del cliente (Por validar con el cliente) |
| RNF-11 | Usabilidad | Textos, etiquetas y mensajes claros | RNF.5 |
| RNF-12 | Usabilidad | Campos obligatorios indicados y mensajes de error | RNF.5 |
| RNF-13 | Usabilidad | Uniformidad de colores, botones, menús, tablas y formularios | RNF.5; Revisión de diseño: una sola hoja de estilos y macros compartidas (templates/_macros.html) (Revisión manual) |
| RNF-14 | Usabilidad | Adaptación a computadoras, tabletas y móviles | RNF.6 |
| RNF-15 | Confiabilidad | Sin pérdida ni duplicación de movimientos | RNF.2 |
| RNF-16 | Confiabilidad | Entradas y salidas mediante transacciones | PA-03.3, RNF.3 |
| RNF-17 | Confiabilidad | Sin actualizaciones parciales ante errores | RNF.3 |
| RNF-18 | Compatibilidad | Chrome, Edge y Firefox | RNF.6; Automatizado solo en Chromium; Edge (mismo motor) y Firefox no probados en este entorno (Parcial) |
| RNF-19 | Compatibilidad | Funciones principales en distintas resoluciones | RNF.6 |
| RNF-20 | Mantenibilidad | Código organizado en módulos | Inspección: paquetes models/, services/, views/, templates/ (docs/arquitectura.md) (Revisión manual) |
| RNF-21 | Mantenibilidad | Arquitectura que permite agregar funciones sin afectar módulos | Inspección: blueprints independientes y matriz de permisos única (security.py) (Revisión manual) |
| RNF-22 | Mantenibilidad | Base de datos extensible (categorías, productos, usuarios) | RU-A.3 |
| RNF-23 | Mantenibilidad | Preparado para integraciones futuras (ERP) | Preparado, no implementado: capa de modelos/servicios separada; no hay API ni conector ERP (No implementado) |
| RNF-24 | Integridad | Identificador único por producto | RNF.4 |
| RNF-25 | Integridad | Consistencia entre existencias y movimientos | PA-03.3, RNF.4 |
| RNF-26 | Integridad | Movimientos con usuario, fecha, hora, tipo y cantidad | RU-E.2 |
| RNF-27 | Integridad | Integridad referencial | RNF.4 |

## Interpretaciones y límites

- Se eliminó el movimiento «ajuste»; los tipos son Entrada por Compra, Salida por Venta, Salida por Devolución (resta stock) y Reserva de Stock.
- Reserva: el encargado la solicita y retiene unidades (disponible = existencias − reservado); el administrador la valida (sale del stock) o la rechaza (se libera).
- El administrador valida reservas; los movimientos los registra el encargado.
- RF-04: asignación de rol por usuario; los permisos de cada rol son fijos.
- «Incorruptible» = a prueba de alteraciones detectables: folio `ST-AAAA-NNNNNN`, SHA-256 registrado, página de verificación, PDF con edición bloqueada y Excel protegido; no es firma electrónica.
- Probado en Chromium; Edge y Firefox no probados. PostgreSQL/Docker no ejecutados. ERP (RNF-23) solo preparado. La aceptación del cliente está pendiente.
