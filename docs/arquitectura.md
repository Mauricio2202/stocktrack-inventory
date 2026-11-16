# Arquitectura (RNF-20, RNF-21, RNF-22, RNF-23)

Monolito Flask organizado por capas; cada módulo depende solo de la capa inferior.

| Capa | Carpeta | Responsabilidad |
|---|---|---|
| Vistas | `stocktrack/views/` | Un blueprint por módulo (auth, dashboard, products, categories, movements, alerts, users, reports, audit) |
| Plantillas | `stocktrack/templates/` | Jinja2 con macros compartidas (`_macros.html`) y una sola hoja de estilos |
| Servicios | `stocktrack/services/` | Reportes (PDF/Excel, folio, SHA-256) y correo SMTP |
| Modelos | `stocktrack/models/` | Reglas de negocio y SQL; únicas que escriben en la base |
| Seguridad | `stocktrack/security.py` | Matriz única de permisos por rol (`PERMISSIONS`, `can`, `permission_required`) |
| Datos | `stocktrack/schema/`, `db.py` | Esquema SQLite/PostgreSQL con llaves foráneas y restricciones |

Agregar una función = nuevo blueprint + modelo + permiso en la matriz, sin tocar los demás módulos.
Integración ERP: no implementada; `models/` y `services/` no dependen de Flask, por lo que pueden exponerse mediante una API REST.
