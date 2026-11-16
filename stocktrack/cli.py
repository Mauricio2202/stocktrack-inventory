"""Comandos de línea de comandos:  flask --app stocktrack <comando>"""
from __future__ import annotations

import click

from .errors import AppError
from .models import alerts, users
from .services import mailer


def register(app) -> None:
    db = app.extensions["stocktrack_db"]

    @app.cli.command("init-db")
    def init_db() -> None:
        """Crea las tablas si no existen."""
        db.init_schema()
        click.echo("Base de datos lista.")

    @app.cli.command("create-user")
    @click.option("--email", prompt="Correo", help="Correo: es el identificador de acceso.")
    @click.option("--full-name", prompt="Nombre completo")
    @click.option("--role", type=click.Choice(users.ROLES), default="admin", show_default=True)
    @click.option("--receive-alerts/--no-receive-alerts", default=False, help="Recibir alertas por correo.")
    @click.password_option()
    def create_user(email, full_name, role, receive_alerts, password) -> None:
        """Crea un usuario (el primer administrador se crea con este comando)."""
        conn = db.connect()
        try:
            users.create(conn, email=email, full_name=full_name, password=password,
                         role=role, receive_alerts=receive_alerts,
                         min_password_length=app.config["PASSWORD_MIN_LENGTH"])
        except AppError as exc:
            raise click.ClickException(f"{exc} {getattr(exc, 'errors', '')}")
        finally:
            conn.close()
        click.echo(f"Usuario «{email}» creado con rol {role}.")

    @app.cli.command("seed-demo")
    @click.option("--force", is_flag=True, help="Cargar aunque ya existan productos.")
    def seed_demo(force: bool) -> None:
        """Carga usuarios y un catálogo de ejemplo (SOLO para demostración; contraseñas conocidas)."""
        from .seed import seed

        summary = seed(db, app.config, force=force)
        click.echo(summary)
        click.echo("ATENCIÓN: las contraseñas de demostración son públicas; no uses estos usuarios en producción.")

    @app.cli.command("check-alerts")
    def check_alerts() -> None:
        """Revisa todo el inventario, crea las alertas faltantes y envía sus correos.
        Pensado para ejecutarse con cron (por ejemplo, cada hora)."""
        conn = db.connect()
        try:
            new_ids = alerts.scan_all(conn)
        finally:
            conn.close()
        for alert_id in new_ids:
            status = mailer.dispatch_alert(db, app.config, alert_id, wait=True)
            click.echo(f"Alerta {alert_id}: correo {status}")
        click.echo(f"Revisión completa: {len(new_ids)} alerta(s) nueva(s).")
