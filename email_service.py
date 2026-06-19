import os
import threading

import requests

BREVO_API_KEY   = os.environ.get("BREVO_API_KEY", "")
BREVO_FROM_EMAIL = os.environ.get("BREVO_FROM_EMAIL", "")
BREVO_FROM_NAME  = os.environ.get("BREVO_FROM_NAME", "ZELO")
BREVO_URL        = "https://api.brevo.com/v3/smtp/email"


def _dispatch(to_email, subject, html, label=""):
    """Envia o email via Brevo em thread de background para não bloquear o worker."""
    def _send():
        if not BREVO_API_KEY or not BREVO_FROM_EMAIL:
            print(f"[email] BREVO_API_KEY ou BREVO_FROM_EMAIL não configurados. Assunto: {subject}")
            return
        try:
            resp = requests.post(
                BREVO_URL,
                headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"},
                json={
                    "sender":      {"name": BREVO_FROM_NAME, "email": BREVO_FROM_EMAIL},
                    "to":          [{"email": to_email}],
                    "subject":     subject,
                    "htmlContent": html,
                },
                timeout=15,
            )
            if not resp.ok:
                print(f"[email] erro ao enviar {label}: {resp.status_code} {resp.text}")
        except Exception as ex:
            print(f"[email] erro ao enviar {label}: {ex}")
    threading.Thread(target=_send, daemon=True).start()


def send_reset_email(to_email, to_name, reset_url):
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
    _dispatch(to_email, "Redefinição de senha — ZELO", html, "reset_email")


def send_join_request_notification(leader_email, leader_name, requester_name, requester_email):
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
    _dispatch(leader_email, f"Nova solicitação de acesso — {requester_name}", html, "join_request")


def send_registration_verification_email(to_email, to_name, code):
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
    _dispatch(to_email, f"{code} é seu código de verificação — ZELO", html, "registration_verification")


def send_otp_email(to_email, to_name, code):
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
    _dispatch(to_email, f"{code} é seu código de acesso — ZELO", html, "otp")
