# StockTrack · Control total de inventarios

Aplicación web de gestión de inventario para una tienda de electrónicos en Monterrey, N.L.:
productos y existencias, movimientos con trazabilidad, alertas de escasez (correo y notificaciones),
reportes en PDF y Excel, y acceso multiusuario por roles.

## Arquitectura monolítica · Model-View-Template

| Capa | Dónde | Responsabilidad |
|---|---|---|
| **Modelo** | `stocktrack/models/` | Reglas de negocio y acceso a datos (productos, movimientos, alertas, usuarios, auditoría) |
| **Vista** | `stocktrack/views/` | Rutas HTTP por módulo (blueprints), permisos y validación de la petición |
| **Plantilla** | `stocktrack/templates/` | HTML renderizado en el servidor (Jinja2), sin JavaScript pesado |
| Servicios | `stocktrack/services/` | Generación de reportes (PDF/Excel) y envío de correo (SMTP) |

**Decisión de stack.** Se eligió **Flask + Jinja2** (de las opciones Django/Flask del requerimiento) porque el repositorio
declara una arquitectura monolítica MVT. **No se usó React**: la interfaz es HTML del lado del servidor. Si el cliente
exige una SPA, la capa de modelos se puede exponer como API sin reescribir la lógica de negocio.

## Requerimientos y dónde se cumplen

| Requerimiento | Implementación |
|---|---|
| Gestión de productos en stock | `models/products.py`, `models/stock.py`; el stock **solo** cambia con movimientos (Entrada por Compra, Salida por Venta, Salida por Devolución, Reserva de Stock con validación del administrador) y nunca queda negativo |
| Reportes PDF y Excel | `services/reports.py` (diario, mensual, reservas y devoluciones; inventario y movimientos), foliados (`ST-AAAA-NNNNNN`) con SHA-256 y página de verificación; PDF con edición bloqueada y Excel protegido |
| Alertas de escasez | `models/alerts.py`: una alerta vigente por producto (`stock ≤ mínimo`), notificación interna y correo SMTP; se resuelve sola al reponer |
| Multiusuario con roles | Administrador, Encargado de inventario y Usuario de consulta; ingreso por correo; cierre por inactividad (`SESSION_IDLE_MINUTES`, 30 por defecto) (`security.py`) |
| Máx. 100,000 registros activos | `MAX_ACTIVE_RECORDS`; bloqueo transaccional (también para altas simultáneas); archivar libera capacidad |
| 10 usuarios concurrentes | Transacciones atómicas por movimiento; ver `docs/acceptance/` |
| Escalabilidad | Índices, paginación en servidor, reportes por lotes (Excel en modo memoria constante), múltiples procesos con gunicorn |
| Logo | `stocktrack/static/img/` (`logo.png`, `icon.png`, `favicon.png`) |
| Requerimientos | `docs/requisitos.md` (matriz RF/RNF ↔ pruebas), `docs/arquitectura.md` |
| Kanban | `docs/kanban.md` |
| ISO 9001 | `docs/iso9001.md` (matriz de trazabilidad; ver el alcance que declara) |
| Pruebas de aceptación | `tests/acceptance/`, `docs/acceptance/*.xlsx` y `*.pptx` |

## Puesta en marcha local (SQLite, sin instalar nada más)

**Linux / macOS (bash)**

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m flask --app stocktrack create-user --role admin        # primer administrador
python -m flask --app stocktrack seed-demo                       # opcional: catálogo y usuarios de demostración
python -m flask --app stocktrack run                             # http://127.0.0.1:5000
```

**Windows (PowerShell)** — ejecuta los comandos uno por uno (en PowerShell 5.1 no existe `&&`):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1          # si lo bloquea la política de scripts: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
pip install -r requirements-dev.txt # si falla psycopg2-binary y solo usarás SQLite: pip install Flask XlsxWriter reportlab pytest requests openpyxl pypdf tzdata
python -m flask --app stocktrack create-user --role admin
python -m flask --app stocktrack seed-demo                       # opcional
python -m flask --app stocktrack run                             # http://127.0.0.1:5000
```

Las variables de entorno se definen distinto en PowerShell: `$env:DATABASE_URL = "postgresql://usuario:clave@localhost:5432/stocktrack"`
(en bash: `export DATABASE_URL=...`). Esta guía de Windows no se probó en Windows; el proyecto se desarrolló y probó en Linux.

Usuarios de demostración (**solo para pruebas; contraseñas públicas**): `admin@stocktrack.local / Admin12345`, `encargado@stocktrack.local / Encargado12345`, `consulta@stocktrack.local / Consulta12345`.

## Producción (PostgreSQL)

```bash
cp .env.example .env            # define SECRET_KEY, DATABASE_URL, correo, etc.
pip install -r requirements.txt
gunicorn -w 4 --threads 2 -b 0.0.0.0:8000 wsgi:app     # detrás de un proxy con HTTPS
# o:  SECRET_KEY=... docker compose up --build
```

Esquema SQL: `stocktrack/schema/postgresql.sql` (se crea solo al arrancar). Revisión periódica de alertas con cron:
`python -m flask --app stocktrack check-alerts` (por ejemplo, cada hora).

> **Importante: PostgreSQL y Docker no se ejecutaron en este desarrollo.** El entorno de construcción no tenía el controlador
> `psycopg2` ni red para instalarlo; todas las pruebas corrieron sobre SQLite. El código usa SQL común y bloqueos propios de
> PostgreSQL (`FOR UPDATE`, bloqueo consultivo), pero **debe correrse la suite contra PostgreSQL antes de producción**:
> `DATABASE_URL=postgresql://... python -m pytest tests`.

## Pruebas

```bash
python -m pytest tests                      # 57 pruebas: 16 casos de aceptación + unitarias y de seguridad
python scripts/build_acceptance_excel.py    # Excel de pruebas de aceptación (desde docs/acceptance/results.json)
node scripts/build_status_pptx.js           # gráfica de estatus en pptx
```

## Seguridad

Contraseñas con PBKDF2-SHA256; bloqueo temporal tras intentos fallidos; token CSRF en todos los formularios; cookies
`HttpOnly`/`SameSite`; cabeceras (CSP estricta, X-Frame-Options); consultas parametrizadas; escape de HTML; redirecciones
solo internas; bitácora de auditoría de accesos, cambios, movimientos y descargas de reportes.

## Estructura

```
stocktrack/        aplicación (models, views, templates, services, static, schema)
tests/             unitarias, seguridad y tests/acceptance (casos PA-01…RNF)
docs/              kanban.md, iso9001.md y docs/acceptance (Excel, pptx, results.json)
scripts/           Excel y pptx de aceptación
```

## Extensión futura: ERP

Puntos de integración previstos: exponer `models/products.py` y `models/stock.py` mediante una API REST con tokens,
y publicar los movimientos como eventos hacia el ERP. No está implementado en esta fase.
