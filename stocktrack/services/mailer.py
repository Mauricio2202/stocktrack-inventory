"""Envío de alertas de escasez por correo (SMTP)."""
from __future__ import annotations

import logging
import smtplib
import threading
from email.message import EmailMessage

from ..models import alerts as alerts_model
from ..timeutil import fmt_local

log = logging.getLogger("stocktrack.mail")


def build_message(ctx: dict, recipients: list[str], config: dict) -> EmailMessage:
    created = fmt_local(ctx["created_at"], config["TIMEZONE"])
    subject = f"[StockTrack] Alerta de escasez: {ctx['name']} ({ctx['sku']})"
    text = (
        "Alerta de escasez de inventario\n"
        "================================\n\n"
        f"Producto:       {ctx['name']}\n"
        f"SKU:            {ctx['sku']}\n"
        f"Categoría:      {ctx.get('category') or '-'}\n"
        f"Ubicación:      {ctx.get('location') or '-'}\n"
        f"Stock disponible: {ctx['available']} unidades (físico {ctx['stock']}, reservado {ctx['reserved']})\n"
        f"Stock mínimo:   {ctx['min_stock']} unidades\n"
        f"Detectada:      {created}\n\n"
        "Acción sugerida: generar la orden de reposición con el proveedor.\n"
        "Este aviso se envía una sola vez por alerta; se cierra solo cuando el stock supera el mínimo.\n\n"
        "-- StockTrack · Control total de inventarios\n"
    )
    html = f"""<html><body style="font-family:Arial,sans-serif;color:#10243b">
<h2 style="color:#b45309;margin-bottom:4px">Alerta de escasez de inventario</h2>
<p style="margin-top:0">{config.get('COMPANY_NAME', '')}</p>
<table cellpadding="6" style="border-collapse:collapse;border:1px solid #d5dde6">
<tr><td><b>Producto</b></td><td>{_esc(ctx['name'])}</td></tr>
<tr><td><b>SKU</b></td><td>{_esc(ctx['sku'])}</td></tr>
<tr><td><b>Categoría</b></td><td>{_esc(ctx.get('category') or '-')}</td></tr>
<tr><td><b>Ubicación</b></td><td>{_esc(ctx.get('location') or '-')}</td></tr>
<tr><td><b>Stock disponible</b></td><td style="color:#b91c1c"><b>{ctx['available']}</b> unidades (físico {ctx['stock']}, reservado {ctx['reserved']})</td></tr>
<tr><td><b>Stock mínimo</b></td><td>{ctx['min_stock']} unidades</td></tr>
<tr><td><b>Detectada</b></td><td>{created}</td></tr>
</table>
<p>Acción sugerida: generar la orden de reposición con el proveedor.</p>
<p style="color:#5b6b7e;font-size:12px">StockTrack · Control total de inventarios</p>
</body></html>"""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config["MAIL_FROM"]
    msg["To"] = ", ".join(recipients)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def _esc(value) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def send_smtp(msg: EmailMessage, config: dict) -> None:
    host, port, timeout = config["MAIL_HOST"], int(config["MAIL_PORT"]), config["MAIL_TIMEOUT"]
    if config["MAIL_USE_SSL"]:
        server = smtplib.SMTP_SSL(host, port, timeout=timeout)
    else:
        server = smtplib.SMTP(host, port, timeout=timeout)
    with server:
        if config["MAIL_USE_TLS"] and not config["MAIL_USE_SSL"]:
            server.starttls()
        if config["MAIL_USER"]:
            server.login(config["MAIL_USER"], config["MAIL_PASSWORD"])
        server.send_message(msg)


def _deliver(db, config: dict, alert_id: int) -> str:
    """Envía el correo de una alerta y guarda el resultado. Devuelve el estado final."""
    conn = db.connect()
    try:
        ctx = alerts_model.get_context(conn, alert_id)
        if not ctx:
            return "error"
        if not config["MAIL_ENABLED"]:
            alerts_model.set_email_result(conn, alert_id, "omitido", "Envío de correo deshabilitado (MAIL_ENABLED)")
            return "omitido"
        recipients = alerts_model.email_recipients(conn, config.get("ALERT_EMAIL_TO"))
        if not recipients:
            alerts_model.set_email_result(conn, alert_id, "omitido", "Sin destinatarios configurados")
            return "omitido"
        try:
            send_smtp(build_message(ctx, recipients, config), config)
        except Exception as exc:  # la alerta interna ya existe; solo se registra el fallo del correo
            log.warning("No se pudo enviar el correo de la alerta %s: %s", alert_id, exc)
            alerts_model.set_email_result(conn, alert_id, "error", f"{type(exc).__name__}: {exc}")
            return "error"
        alerts_model.set_email_result(conn, alert_id, "enviado", f"Enviado a {len(recipients)} destinatario(s)")
        return "enviado"
    finally:
        conn.close()


def dispatch_alert(db, config: dict, alert_id: int, *, wait: bool = False) -> str | None:
    """Despacha el correo de una alerta. Por defecto en segundo plano para no frenar la petición web."""
    if config.get("MAIL_ASYNC") and not wait:
        threading.Thread(target=_deliver, args=(db, dict(config), alert_id), daemon=True,
                         name=f"alert-mail-{alert_id}").start()
        return None
    return _deliver(db, config, alert_id)
