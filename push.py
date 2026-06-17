import os
import json
from pywebpush import webpush, WebPushException
import models


def _keys():
    """Lê as chaves VAPID em tempo de execução, com strip para evitar
    problemas com espaços/newlines vindos do painel do Render."""
    return (
        os.environ.get("VAPID_PUBLIC_KEY",  "").strip(),
        os.environ.get("VAPID_PRIVATE_KEY", "").strip(),
        os.environ.get("VAPID_CLAIMS_EMAIL", "admin@zeloscalas.com").strip(),
    )


def _send(sub_json, title, body, url="/"):
    _, private_key, email = _keys()
    if not private_key:
        print("[push] VAPID_PRIVATE_KEY não configurada — push ignorado")
        return
    try:
        webpush(
            subscription_info=sub_json,
            data=json.dumps({"title": title, "body": body, "url": url}),
            vapid_private_key=private_key,
            vapid_claims={"sub": f"mailto:{email}"},
        )
    except WebPushException as ex:
        if ex.response and ex.response.status_code in (404, 410):
            models.delete_push_subscription(sub_json.get("endpoint", ""))
        else:
            print(f"[push] WebPushException: {ex}")
    except Exception as ex:
        print(f"[push] erro inesperado: {ex}")


def notify_user(user_id, title, body, url="/"):
    for row in models.get_user_subscriptions(user_id):
        _send(json.loads(row["subscription_json"]), title, body, url)


def notify_ministry(ministry_id, title, body, url="/"):
    for row in models.get_ministry_subscriptions(ministry_id):
        _send(json.loads(row["subscription_json"]), title, body, url)
