import os
import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

GMAIL_USER         = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
FROM_NAME          = "ZELO — Escalas"
_SMTP_TIMEOUT      = 15


def _dispatch(msg, to_email, label=""):
    """Envia o email em thread de background para não bloquear o worker."""
    def _send():
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=_SMTP_TIMEOUT) as smtp:
                smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                smtp.sendmail(GMAIL_USER, to_email, msg.as_string())
        except Exception as ex:
            print(f"[email] erro ao enviar {label}: {ex}")
    threading.Thread(target=_send, daemon=True).start()


def send_reset_email(to_email, to_name, reset_url):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print(f"[email] GMAIL_USER ou GMAIL_APP_PASSWORD não configurados. Link: {reset_url}")
        return

    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:2rem;">
      <h2 style="font-family:Georgia,serif;letter-spacing:.1em;text-transform:uppercase;">ZELO</h2>
      <p>Olá, <strong>{to_name}</strong>.</p>
      <p>Recebemos uma solicitação para redefinir a senha da sua conta.</p>
      <p style="margin:1.5rem 0;">
        <a href="{reset_url}"
           style="background:#1F1F24;color:#fff;padding:.75rem 1.5rem;border-radius:8px;
                  text-decoration:none;font-weight:600;">
          Redefinir senha
        </a>
      </p>
      <p style="color:#888;font-size:.875rem;">
        Este link expira em <strong>1 hora</strong>.<br>
        Se você não solicitou isso, ignore este email.
      </p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Redefinição de senha — ZELO"
    msg["From"]    = f"{FROM_NAME} <{GMAIL_USER}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(html, "html"))
    _dispatch(msg, to_email, "reset_email")


def send_join_request_notification(leader_email, leader_name, requester_name, requester_email):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print(f"[email] credenciais não configuradas. Solicitação de {requester_name} ({requester_email})")
        return

    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:2rem;">
      <h2 style="font-family:Georgia,serif;letter-spacing:.1em;text-transform:uppercase;">ZELO</h2>
      <p>Olá, <strong>{leader_name}</strong>.</p>
      <p><strong>{requester_name}</strong> ({requester_email}) solicitou acesso ao seu ministério.</p>
      <p style="color:#888;font-size:.875rem;">
        Acesse o painel para aprovar ou recusar a solicitação.
      </p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Nova solicitação de acesso — {requester_name}"
    msg["From"]    = f"{FROM_NAME} <{GMAIL_USER}>"
    msg["To"]      = leader_email
    msg.attach(MIMEText(html, "html"))
    _dispatch(msg, leader_email, "join_request")


def send_registration_verification_email(to_email, to_name, code):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print(f"[email] credenciais não configuradas. Código de verificação de cadastro: {code}")
        return

    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:2rem;">
      <h2 style="font-family:Georgia,serif;letter-spacing:.1em;text-transform:uppercase;">ZELO</h2>
      <p>Olá, <strong>{to_name}</strong>.</p>
      <p>Use o código abaixo para confirmar seu e-mail e concluir a solicitação de acesso:</p>
      <div style="font-size:2.5rem;font-weight:700;letter-spacing:.4em;
                  text-align:center;padding:1.5rem;margin:1.5rem 0;
                  background:#f4f4f5;border-radius:12px;">
        {code}
      </div>
      <p style="color:#888;font-size:.875rem;">
        Este código expira em <strong>15 minutos</strong>.<br>
        Se você não solicitou isso, ignore este email.
      </p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{code} é seu código de verificação — ZELO"
    msg["From"]    = f"{FROM_NAME} <{GMAIL_USER}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(html, "html"))
    _dispatch(msg, to_email, "registration_verification")


def send_otp_email(to_email, to_name, code):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print(f"[email] credenciais não configuradas. Código OTP: {code}")
        return

    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:2rem;">
      <h2 style="font-family:Georgia,serif;letter-spacing:.1em;text-transform:uppercase;">ZELO</h2>
      <p>Olá, <strong>{to_name}</strong>.</p>
      <p>Use o código abaixo para acessar sua conta:</p>
      <div style="font-size:2.5rem;font-weight:700;letter-spacing:.4em;
                  text-align:center;padding:1.5rem;margin:1.5rem 0;
                  background:#f4f4f5;border-radius:12px;">
        {code}
      </div>
      <p style="color:#888;font-size:.875rem;">
        Este código expira em <strong>15 minutos</strong>.<br>
        Se você não solicitou isso, ignore este email.
      </p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{code} é seu código de acesso — ZELO"
    msg["From"]    = f"{FROM_NAME} <{GMAIL_USER}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(html, "html"))
    _dispatch(msg, to_email, "otp")
