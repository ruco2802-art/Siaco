# -*- coding: utf-8 -*-
import os
import smtplib
import webbrowser
import urllib.parse
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


class Notificador:
    """Envío de alertas SECOP II por WhatsApp Web y/o Gmail."""

    def __init__(self, preferencia: str = "whatsapp"):
        """preferencia: 'whatsapp' | 'gmail' | 'ambos'"""
        self.preferencia = preferencia

    def enviar_whatsapp(self, contacto: str, mensaje: str):
        """Abre WhatsApp Web con mensaje pre-cargado."""
        url = f"https://web.whatsapp.com/send?phone={contacto}&text={urllib.parse.quote(mensaje)}"
        webbrowser.open(url)
        time.sleep(3)

    def enviar_gmail(self, destinatario: str, asunto: str, mensaje: str):
        """Envía correo electrónico via SMTP SSL con credenciales del entorno."""
        gmail_user = os.environ.get("GMAIL_USER", "")
        gmail_pass = os.environ.get("GMAIL_APP_PASSWORD", "")
        if not gmail_user or not gmail_pass:
            raise ValueError("Configura GMAIL_USER y GMAIL_APP_PASSWORD como variables de entorno")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto
        msg["From"] = gmail_user
        msg["To"] = destinatario
        msg.attach(MIMEText(mensaje, "plain", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
            srv.login(gmail_user, gmail_pass)
            srv.sendmail(gmail_user, destinatario, msg.as_string())

    def formatear_alerta(self, contrato: dict, score: int, dias_restantes: int) -> str:
        """Mensaje estructurado con prefijo URGENTE si dias_restantes < 48."""
        prefijo = "🚨 URGENTE — " if dias_restantes < 48 else ""
        try:
            valor_fmt = f"${float(contrato.get('precio_base', 0)):,.0f} COP"
        except Exception:
            valor_fmt = str(contrato.get("precio_base", "N/A"))

        url_data = contrato.get("urlproceso", {})
        url_final = (url_data.get("url") if isinstance(url_data, dict) else url_data) or "Ver en SECOP II"

        return (
            f"{prefijo}*SIACO v3.0 — ALERTA SECOP II*\n\n"
            f"🏢 *Proceso:* {contrato.get('nombre_del_procedimiento', 'N/A')}\n"
            f"🏛️ *Entidad:* {contrato.get('entidad', 'N/A')}\n"
            f"💰 *Valor:* {valor_fmt}\n"
            f"🎯 *Score SIACO:* {score}/100\n"
            f"⏰ *Días para cierre:* {dias_restantes}\n"
            f"🔗 {url_final}"
        )

    def enviar_alerta(
        self,
        contrato: dict,
        score: int,
        dias_restantes: int,
        contacto_whatsapp: str = "",
        contacto_email: str = "",
    ):
        """Despacha la alerta según preferencia del cliente."""
        mensaje = self.formatear_alerta(contrato, score, dias_restantes)
        asunto = f"⚡ SIACO — {contrato.get('nombre_del_procedimiento', '')[:50]}"

        if self.preferencia in ("whatsapp", "ambos") and contacto_whatsapp:
            self.enviar_whatsapp(contacto_whatsapp, mensaje)
        if self.preferencia in ("gmail", "ambos") and contacto_email:
            self.enviar_gmail(contacto_email, asunto, mensaje)
