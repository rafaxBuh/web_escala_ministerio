from flask import (
    Flask, render_template, redirect, url_for,
    request, flash, abort,
)
from flask_login import (
    LoginManager, UserMixin, login_user, login_required,
    logout_user, current_user,
)
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, timedelta, datetime, timezone
import secrets

import database
import models
import push
import email_service
from scheduler import generate_period_schedule

# ── App setup ──────────────────────────────────────────────────────────────────

import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-insecure-key")

@app.context_processor
def inject_vapid():
    return {"vapid_public_key": os.environ.get("VAPID_PUBLIC_KEY", "").strip()}

def get_week_dates(year, month, end_year=None, end_month=None):
    """
    Retorna lista de dicts para cada semana segunda→domingo do período.
    Suporta períodos multi-mês: passa end_year/end_month para expandir.
    """
    end_year = end_year or year
    end_month = end_month or month

    first_day = date(year, month, 1)
    days_until_monday = (7 - first_day.weekday()) % 7
    first_monday = first_day + timedelta(days=days_until_monday)

    # último dia do mês final
    if end_month == 12:
        last_day = date(end_year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(end_year, end_month + 1, 1) - timedelta(days=1)

    weeks = []
    current = first_monday
    while current <= last_day:
        end_sun = current + timedelta(days=6)
        label = f"{current.day:02d}/{current.month:02d} – {end_sun.day:02d}/{end_sun.month:02d}"
        weeks.append({"week": len(weeks) + 1, "start": current, "end": end_sun, "label": label})
        current += timedelta(weeks=1)
    return weeks


def _create_default_events(year, month, end_year, end_month, ministry_id=None):
    """Cria Sábado Way e Culto da Família para cada semana do período."""
    for wk in get_week_dates(year, month, end_year, end_month):
        saturday = wk["start"] + timedelta(days=5)
        sunday   = wk["start"] + timedelta(days=6)
        models.create_event_if_not_exists("Sábado Way",       saturday.isoformat(), "19h", ministry_id=ministry_id)
        models.create_event_if_not_exists("Culto da Família", sunday.isoformat(),   "19h", ministry_id=ministry_id)


def period_label(period):
    """Retorna 'Abril/2026' ou 'Abril/2026 – Junho/2026' conforme o período."""
    ey = period["end_year"] or period["year"]
    em = period["end_month"] or period["month"]
    if ey == period["year"] and em == period["month"]:
        return f"{MONTHS[period['month']]}/{period['year']}"
    return f"{MONTHS[period['month']]}/{period['year']} – {MONTHS[em]}/{ey}"


MONTHS = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}

# ── Flask-Login ────────────────────────────────────────────────────────────────

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Faça login para continuar."
login_manager.login_message_category = "warning"


class User(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.name = row["name"]
        self.email = row["email"]
        self.role = row["role"]
        self.ministry_id = row["ministry_id"]


@login_manager.user_loader
def load_user(user_id):
    row = models.get_user_by_id(int(user_id))
    return User(row) if row else None


# ── Role decorators ────────────────────────────────────────────────────────────

def leader_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role not in ("ministry_leader", "general_leader"):
            abort(403)
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role != "general_leader":
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ── Template helpers ───────────────────────────────────────────────────────────

@app.context_processor
def inject_globals():
    pending = 0
    try:
        if current_user.is_authenticated and current_user.role == "ministry_leader" and current_user.ministry_id:
            mid = current_user.ministry_id
            pending = (models.count_pending_requests_for_ministry(mid)
                       + models.count_pending_registrations_for_ministry(mid))
    except Exception:
        pass
    return dict(MONTHS=MONTHS, today=date.today(),
                get_week_dates=get_week_dates, period_label=period_label,
                pending_requests=pending)


# ── PWA ────────────────────────────────────────────────────────────────────────

@app.route("/sw.js")
def service_worker():
    return app.send_static_file("sw.js")


# ── Push ───────────────────────────────────────────────────────────────────────

@app.route("/push/subscribe", methods=["POST"])
@login_required
def push_subscribe():
    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint", "")
    if not endpoint:
        return "", 400
    models.save_push_subscription(
        current_user.id,
        endpoint,
        __import__("json").dumps(data),
    )
    return "", 201


@app.route("/push/debug")
@login_required
def push_debug():
    """Diagnóstico de push — acesse /push/debug no browser para ver o status."""
    import json as _json
    pub = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    priv = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    subs = models.get_user_subscriptions(current_user.id)
    info = {
        "VAPID_PUBLIC_KEY_set": bool(pub),
        "VAPID_PUBLIC_KEY_len": len(pub),
        "VAPID_PRIVATE_KEY_set": bool(priv),
        "VAPID_PRIVATE_KEY_len": len(priv),
        "subscriptions_count": len(subs),
    }
    from flask import Response
    return Response(_json.dumps(info, indent=2), mimetype="application/json")


@app.route("/push/unsubscribe", methods=["POST"])
@login_required
def push_unsubscribe():
    data = request.get_json(silent=True) or {}
    models.delete_push_subscription(data.get("endpoint", ""))
    return "", 204


@app.route("/push/cron")
def push_cron():
    secret = os.environ.get("CRON_SECRET", "")
    if not secret or request.args.get("secret") != secret:
        abort(403)

    today = date.today()
    sent = 0

    # 1. Semana de servir ──────────────────────────────────────────────────────
    for period in models.get_confirmed_periods_all():
        week_dates = get_week_dates(
            period["year"], period["month"],
            period["end_year"], period["end_month"],
        )
        schedule = models.get_schedule(period["id"])
        sched_map = {row["week"]: row for row in schedule}
        for wk in week_dates:
            if wk["start"] <= today <= wk["end"]:
                row = sched_map.get(wk["week"])
                if row:
                    for uid in filter(None, (row["member1_id"], row["member2_id"], row.get("member3_id"))):
                        push.notify_user(
                            uid,
                            "Esta é a sua semana de servir!",
                            f"{period['ministry_name']} — {wk['label']}",
                            "/voluntario",
                        )
                        sent += 1
                break

    # 2. Lembrete de eventos (próximos 2 dias) ─────────────────────────────────
    upcoming = models.list_upcoming_events(today.isoformat())
    for ev in upcoming:
        ev_date = date.fromisoformat(ev["event_date"])
        delta = (ev_date - today).days
        if 0 <= delta <= 2:
            label = "hoje" if delta == 0 else ("amanhã" if delta == 1 else "em 2 dias")
            for row in models.get_all_subscriptions():
                push._send(
                    __import__("json").loads(row["subscription_json"]),
                    f"Lembrete: {ev['title']}",
                    f"Ocorre {label} ({ev['event_date'][8:10]}/{ev['event_date'][5:7]})",
                    "/voluntario/agenda",
                )
                sent += 1

    return __import__("json").dumps({"sent": sent}), 200, {"Content-Type": "application/json"}


# ── Auth helpers ───────────────────────────────────────────────────────────────

def _notify_leader(ministry_id, requester_name, requester_email):
    """Envia e-mail ao líder do ministério sobre nova solicitação (best-effort)."""
    try:
        from database import db_conn as _db
        with _db() as conn:
            leader = conn.execute(
                "SELECT * FROM users WHERE ministry_id=%s AND role='ministry_leader' LIMIT 1",
                (ministry_id,),
            ).fetchone()
        if leader:
            email_service.send_join_request_notification(
                leader["email"], leader["name"], requester_name, requester_email
            )
    except Exception:
        pass


# ── Auth ───────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if not current_user.is_authenticated:
        return redirect(url_for("login"))
    if current_user.role == "general_leader":
        return redirect(url_for("admin_dashboard"))
    if current_user.role == "ministry_leader":
        return redirect(url_for("leader_dashboard"))
    return redirect(url_for("volunteer_dashboard"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        row = models.get_user_by_email(email)
        if row and check_password_hash(row["password_hash"], password):
            login_user(User(row))
            return redirect(request.args.get("next") or url_for("index"))
        flash("E-mail ou senha incorretos.", "error")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/primeiro-acesso", methods=["GET", "POST"])
@app.route("/cadastrar", methods=["GET", "POST"])
def first_access():
    """
    Fluxo unificado de primeiro acesso:
    - Usuário existente → cria join_request (já cadastrado pelo admin)
    - Usuário novo      → cria pending_registration (nunca esteve no sistema)
    Em ambos os casos o líder precisa aprovar antes do OTP ser enviado.
    """
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    ministries = models.list_ministries()

    if request.method == "POST":
        name        = request.form.get("name", "").strip()
        email       = request.form.get("email", "").strip().lower()
        ministry_id = request.form.get("ministry_id", type=int)

        if not email or not ministry_id:
            flash("Preencha e-mail e ministério.", "error")
            return render_template("first_access.html", ministries=ministries)

        existing_user = models.get_user_by_email(email)

        if existing_user:
            # Usuário já cadastrado — pedido de acesso ao líder
            if existing_user["ministry_id"] == ministry_id:
                models.create_join_request(existing_user["id"])
                _notify_leader(ministry_id, existing_user["name"], email)
        else:
            # Usuário novo — cadastro pendente
            if not name:
                flash("Informe seu nome para criar uma conta.", "error")
                return render_template("first_access.html", ministries=ministries)
            models.create_pending_registration(name, email, ministry_id)
            _notify_leader(ministry_id, name, email)

        flash("Solicitação enviada! Aguarde a aprovação do líder do seu ministério.", "info")
        return redirect(url_for("first_access"))

    return render_template("first_access.html", ministries=ministries)


@app.route("/verificar-codigo", methods=["GET", "POST"])
def verify_otp():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        code  = request.form.get("code", "").strip()

        user = models.get_user_by_email(email) if email else None
        otp  = models.get_valid_otp(user["id"], code) if user else None

        if not otp:
            flash("Código inválido, expirado ou e-mail incorreto.", "error")
            return render_template("verify_otp.html", email=email)

        models.mark_otp_used(user["id"])
        row = models.get_user_by_id(user["id"])
        login_user(User(row))
        return redirect(url_for("index"))

    return render_template("verify_otp.html", email="")


@app.route("/esqueci-senha", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = models.get_user_by_email(email)
        # Sempre mostra a mesma mensagem para não revelar se o email existe
        flash("Se este e-mail estiver cadastrado, você receberá um link em breve.", "info")
        if user:
            token = secrets.token_urlsafe(32)
            expires = datetime.now(timezone.utc) + timedelta(hours=1)
            models.create_reset_token(user["id"], token, expires)
            reset_url = url_for("reset_password", token=token, _external=True)
            email_service.send_reset_email(user["email"], user["name"], reset_url)
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


@app.route("/resetar-senha/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    record = models.get_valid_reset_token(token)
    if not record:
        flash("Link inválido ou expirado. Solicite um novo.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password  = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        if len(password) < 6:
            flash("A senha deve ter pelo menos 6 caracteres.", "error")
            return render_template("reset_password.html", token=token)
        if password != password2:
            flash("As senhas não coincidem.", "error")
            return render_template("reset_password.html", token=token)

        models.update_user_password(record["user_id"], generate_password_hash(password))
        models.mark_token_used(token)
        flash("Senha redefinida com sucesso! Faça login.", "success")
        return redirect(url_for("login"))

    return render_template("reset_password.html", token=token)


# ── Volunteer ──────────────────────────────────────────────────────────────────

@app.route("/voluntario")
@login_required
def volunteer_dashboard():
    if current_user.role == "general_leader":
        return redirect(url_for("admin_dashboard"))
    if current_user.role == "ministry_leader":
        return redirect(url_for("leader_dashboard"))

    ministry = None
    open_period = None
    availability = {}
    confirmed_schedule = None
    confirmed_period = None

    if current_user.ministry_id:
        ministry = models.get_ministry(current_user.ministry_id)
        open_period = models.get_open_period(current_user.ministry_id)

        if open_period:
            availability = models.get_user_availability(
                current_user.id, open_period["id"]
            )

        for p in models.list_periods_by_ministry(current_user.ministry_id):
            if p["status"] == "confirmed":
                confirmed_period = p
                confirmed_schedule = models.get_schedule(p["id"])
                break

    next_event = None
    upcoming = models.list_upcoming_events_for_user(
        date.today().isoformat(),
        current_user.ministry_id,
        current_user.role,
    )
    if upcoming:
        # Voluntário/recruta só vê o próximo evento das suas semanas escaladas ou notify_all
        if current_user.role in ("volunteer", "recruta"):
            my_week_ranges_dash = []
            if confirmed_schedule:
                wk_dates = get_week_dates(
                    confirmed_period["year"], confirmed_period["month"],
                    confirmed_period["end_year"], confirmed_period["end_month"],
                )
                for row in confirmed_schedule:
                    if current_user.id in (row["member1_id"], row["member2_id"], row.get("member3_id")):
                        wk = wk_dates[row["week"] - 1]
                        my_week_ranges_dash.append((wk["start"], wk["end"]))
            for ev in upcoming:
                ev_date = date.fromisoformat(ev["event_date"])
                if any(s <= ev_date <= e for s, e in my_week_ranges_dash) or ev.get("notify_all"):
                    next_event = ev
                    break
        else:
            next_event = upcoming[0]

    return render_template(
        "volunteer/dashboard.html",
        ministry=ministry,
        open_period=open_period,
        availability=availability,
        confirmed_schedule=confirmed_schedule,
        confirmed_period=confirmed_period,
        next_event=next_event,
    )


@app.route("/voluntario/disponibilidade", methods=["POST"])
@login_required
def save_availability():
    if current_user.role not in ("volunteer", "recruta", "ministry_leader"):
        abort(403)

    period_id = request.form.get("period_id", type=int)
    if not period_id:
        abort(400)

    period = models.get_period(period_id)
    if not period or period["status"] != "open":
        flash("Este período não está aberto.", "error")
        return redirect(url_for("volunteer_dashboard"))

    if period["ministry_id"] != current_user.ministry_id:
        abort(403)

    weeks = get_week_dates(
        period["year"], period["month"],
        period["end_year"], period["end_month"],
    )
    for wk in weeks:
        available = f"week_{wk['week']}" in request.form
        models.set_availability(current_user.id, period_id, wk["week"], available)

    flash("Disponibilidade salva com sucesso!", "success")
    if current_user.role == "ministry_leader":
        return redirect(url_for("leader_dashboard"))
    return redirect(url_for("volunteer_dashboard"))





@app.route("/voluntario/agenda")
@login_required
def volunteer_agenda():
    if current_user.role == "general_leader":
        return redirect(url_for("admin_events"))

    today_iso = date.today().isoformat()
    all_events = models.list_upcoming_events_for_user(
        today_iso, current_user.ministry_id, current_user.role
    )

    my_week_ranges = []
    if current_user.ministry_id:
        for p in models.list_periods_by_ministry(current_user.ministry_id):
            if p["status"] == "confirmed":
                schedule = models.get_schedule(p["id"])
                week_dates = get_week_dates(
                    p["year"], p["month"], p["end_year"], p["end_month"]
                )
                for row in schedule:
                    if current_user.id in (row["member1_id"], row["member2_id"], row.get("member3_id")):
                        wk = week_dates[row["week"] - 1]
                        my_week_ranges.append((wk["start"], wk["end"]))
                break

    my_events, notify_all_events = [], []
    seen_ids = set()
    for ev in all_events:
        ev_date = date.fromisoformat(ev["event_date"])
        in_my_week = any(s <= ev_date <= e for s, e in my_week_ranges)
        if in_my_week:
            my_events.append(ev)
            seen_ids.add(ev["id"])
        elif ev.get("notify_all"):
            notify_all_events.append(ev)

    return render_template(
        "volunteer/agenda.html",
        my_events=my_events,
        notify_all_events=notify_all_events,
    )


# ── Ministry Leader ────────────────────────────────────────────────────────────

@app.route("/lider")
@leader_required
def leader_dashboard():
    if not current_user.ministry_id:
        flash("Você não está associado a nenhum ministério.", "warning")
        return render_template(
            "leader/dashboard.html",
            ministry=None, periods=[], open_period=None,
            members=[], availability_summary={},
        )

    mid = current_user.ministry_id
    ministry = models.get_ministry(mid)
    periods = models.list_periods_by_ministry(mid)
    open_period = models.get_open_period(mid)
    members = models.list_users_by_ministry(mid)

    availability_summary = {}
    leader_availability = {}
    if open_period:
        for row in models.get_period_availability_summary(open_period["id"]):
            w = row["week"]
            if w not in availability_summary:
                availability_summary[w] = []
            if row["available"]:
                availability_summary[w].append(row["name"])
        leader_availability = models.get_user_availability(
            current_user.id, open_period["id"]
        )

    return render_template(
        "leader/dashboard.html",
        ministry=ministry,
        periods=periods,
        open_period=open_period,
        members=members,
        availability_summary=availability_summary,
        leader_availability=leader_availability,
    )


@app.route("/lider/periodo/abrir", methods=["POST"])
@leader_required
def open_period():
    mid = current_user.ministry_id
    if not mid:
        abort(403)

    year      = request.form.get("year",      type=int)
    month     = request.form.get("month",     type=int)
    end_year  = request.form.get("end_year",  type=int)
    end_month = request.form.get("end_month", type=int)

    if not all([year, month, end_year, end_month]):
        flash("Preencha início e fim do período.", "error")
        return redirect(url_for("leader_dashboard"))

    if not (1 <= month <= 12) or not (1 <= end_month <= 12):
        flash("Mês inválido.", "error")
        return redirect(url_for("leader_dashboard"))

    if (end_year, end_month) < (year, month):
        flash("A data de fim deve ser igual ou posterior ao início.", "error")
        return redirect(url_for("leader_dashboard"))

    if models.get_open_period(mid):
        flash("Já existe um período aberto para este ministério.", "error")
        return redirect(url_for("leader_dashboard"))

    try:
        models.create_period(mid, year, month, end_year, end_month)
        label = period_label({'year':year,'month':month,'end_year':end_year,'end_month':end_month})
        _create_default_events(year, month, end_year, end_month, ministry_id=mid)
        flash(f"Período {label} aberto!", "success")
        push.notify_ministry(
            mid,
            "Novo período aberto!",
            f"Marque sua disponibilidade para {label}",
            "/voluntario",
        )
    except Exception:
        flash("Este período já existe para o ministério.", "error")

    return redirect(url_for("leader_dashboard"))


@app.route("/lider/periodo/<int:period_id>/fechar", methods=["POST"])
@leader_required
def close_period(period_id):
    period = models.get_period(period_id)
    if not period or period["ministry_id"] != current_user.ministry_id:
        abort(403)
    if period["status"] != "open":
        flash("Este período não está aberto.", "error")
        return redirect(url_for("leader_dashboard"))

    try:
        total_weeks = len(get_week_dates(
            period["year"], period["month"],
            period["end_year"], period["end_month"],
        ))
        generate_period_schedule(period_id, current_user.ministry_id, total_weeks)
        models.update_period_status(period_id, "closed")
        flash("Escala gerada! Revise e confirme.", "success")
        push.notify_ministry(
            current_user.ministry_id,
            "Escala gerada!",
            "O líder gerou a escala. Aguarde a confirmação.",
            "/voluntario",
        )
        return redirect(url_for("view_schedule", period_id=period_id))
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("leader_dashboard"))


@app.route("/lider/periodo/<int:period_id>/escala")
@leader_required
def view_schedule(period_id):
    period = models.get_period(period_id)
    if not period:
        abort(404)

    if (
        current_user.role != "general_leader"
        and period["ministry_id"] != current_user.ministry_id
    ):
        abort(403)

    schedule = models.get_schedule(period_id)
    ministry = models.get_ministry(period["ministry_id"])
    volunteers = models.list_volunteers_by_ministry(period["ministry_id"])

    return render_template(
        "leader/schedule.html",
        period=period,
        schedule=schedule,
        ministry=ministry,
        volunteers=volunteers,
    )


@app.route("/lider/periodo/<int:period_id>/escala/salvar", methods=["POST"])
@leader_required
def save_schedule_edits(period_id):
    period = models.get_period(period_id)
    if not period or period["ministry_id"] != current_user.ministry_id:
        abort(403)
    if period["status"] == "open":
        flash("A escala não pode ser editada enquanto o período está aberto.", "error")
        return redirect(url_for("view_schedule", period_id=period_id))

    week_dates = get_week_dates(
        period["year"], period["month"],
        period["end_year"], period["end_month"],
    )
    errors = []
    for wk in week_dates:
        m1 = request.form.get(f"member1_{wk['week']}", type=int)
        m2 = request.form.get(f"member2_{wk['week']}", type=int)
        m3 = request.form.get(f"member3_{wk['week']}", type=int) or None
        if not m1 or not m2:
            errors.append(f"{wk['label']}: selecione dois voluntários.")
            continue
        if m1 == m2:
            errors.append(f"{wk['label']}: os dois voluntários precisam ser diferentes.")
            continue
        models.save_schedule(period_id, wk["week"], m1, m2, m3)

    if errors:
        for e in errors:
            flash(e, "error")
    else:
        flash("Escala salva com sucesso!", "success")

    return redirect(url_for("view_schedule", period_id=period_id))


@app.route("/lider/periodo/<int:period_id>/confirmar", methods=["POST"])
@leader_required
def confirm_period(period_id):
    period = models.get_period(period_id)
    if not period or period["ministry_id"] != current_user.ministry_id:
        abort(403)
    if period["status"] != "closed":
        flash("A escala precisa ser gerada antes de confirmar.", "error")
        return redirect(url_for("leader_dashboard"))

    models.update_period_status(period_id, "confirmed")
    flash("Escala confirmada! Já está visível para todos do ministério.", "success")
    push.notify_ministry(
        period["ministry_id"],
        "Escala confirmada!",
        f"A escala de {period_label(period)} está disponível.",
        "/voluntario",
    )
    return redirect(url_for("view_schedule", period_id=period_id))


@app.route("/lider/periodo/<int:period_id>/reabrir", methods=["POST"])
@leader_required
def reopen_period(period_id):
    period = models.get_period(period_id)
    if not period or period["ministry_id"] != current_user.ministry_id:
        abort(403)
    if period["status"] != "closed":
        flash("Só é possível reabrir períodos fechados.", "error")
        return redirect(url_for("leader_dashboard"))

    models.clear_period_schedule(period_id)
    models.update_period_status(period_id, "open")
    flash("Período reaberto. Voluntários podem atualizar disponibilidade.", "success")
    return redirect(url_for("leader_dashboard"))


@app.route("/lider/restricoes")
@leader_required
def list_restrictions():
    mid = current_user.ministry_id
    if not mid:
        abort(403)

    restrictions = models.list_pair_restrictions(mid)
    members = models.list_volunteers_by_ministry(mid)

    return render_template(
        "leader/restrictions.html",
        restrictions=restrictions,
        members=members,
    )


@app.route("/lider/restricoes/adicionar", methods=["POST"])
@leader_required
def add_restriction():
    mid = current_user.ministry_id
    if not mid:
        abort(403)

    m1 = request.form.get("member1_id", type=int)
    m2 = request.form.get("member2_id", type=int)

    if not m1 or not m2 or m1 == m2:
        flash("Selecione dois voluntários diferentes.", "error")
        return redirect(url_for("list_restrictions"))

    models.add_pair_restriction(mid, m1, m2)
    flash("Restrição adicionada.", "success")
    return redirect(url_for("list_restrictions"))


@app.route("/lider/restricoes/<int:restriction_id>/remover", methods=["POST"])
@leader_required
def remove_restriction(restriction_id):
    mid = current_user.ministry_id
    if not mid:
        abort(403)

    models.remove_pair_restriction(restriction_id, mid)
    flash("Restrição removida.", "success")
    return redirect(url_for("list_restrictions"))


# ── Leader: member management ─────────────────────────────────────────────────

@app.route("/lider/membros")
@leader_required
def leader_members():
    mid = current_user.ministry_id
    if not mid:
        abort(403)
    members = models.list_users_by_ministry(mid)
    companion_counts = models.get_recruta_companion_counts(mid)
    return render_template("leader/members.html", members=members, companion_counts=companion_counts)


@app.route("/lider/membros/novo", methods=["GET", "POST"])
@leader_required
def leader_create_member():
    mid = current_user.ministry_id
    if not mid:
        abort(403)

    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role     = request.form.get("role", "volunteer")

        if role not in ("volunteer", "recruta"):
            role = "volunteer"

        if not name or not email or not password:
            flash("Preencha todos os campos.", "error")
            return render_template("leader/member_form.html", user=None)

        try:
            models.create_user(
                name, email,
                generate_password_hash(password),
                role=role,
                ministry_id=mid,
            )
            label = "Recruta" if role == "recruta" else "Voluntário"
            flash(f'{label} "{name}" criado com sucesso!', "success")
            return redirect(url_for("leader_members"))
        except Exception:
            flash("Já existe um usuário com este e-mail.", "error")

    return render_template("leader/member_form.html", user=None)


@app.route("/lider/membros/<int:user_id>/editar", methods=["GET", "POST"])
@leader_required
def leader_edit_member(user_id):
    mid = current_user.ministry_id
    if not mid:
        abort(403)

    user_row = models.get_user_by_id(user_id)
    if not user_row or user_row["ministry_id"] != mid:
        abort(404)

    if request.method == "POST":
        name         = request.form.get("name", "").strip()
        email        = request.form.get("email", "").strip().lower()
        new_password = request.form.get("password", "").strip()
        new_role     = request.form.get("role", user_row["role"])

        # Líder só pode alternar entre volunteer e recruta
        if user_row["role"] in ("volunteer", "recruta") and new_role in ("volunteer", "recruta"):
            role_to_save = new_role
        else:
            role_to_save = user_row["role"]

        if not name or not email:
            flash("Nome e e-mail são obrigatórios.", "error")
            return render_template("leader/member_form.html", user=user_row)

        try:
            models.update_user(user_id, name, email, role_to_save, mid)
            if new_password:
                models.update_user_password(user_id, generate_password_hash(new_password))
            flash("Membro atualizado.", "success")
            return redirect(url_for("leader_members"))
        except Exception as e:
            flash(f"Erro: {e}", "error")

    return render_template("leader/member_form.html", user=user_row)


@app.route("/lider/membros/<int:user_id>/remover", methods=["POST"])
@leader_required
def leader_remove_member(user_id):
    mid = current_user.ministry_id
    if not mid:
        abort(403)

    user_row = models.get_user_by_id(user_id)
    if not user_row or user_row["ministry_id"] != mid:
        abort(404)

    if user_id == current_user.id:
        flash("Você não pode se remover do ministério por aqui.", "error")
        return redirect(url_for("leader_members"))

    models.unlink_from_ministry(user_id)
    flash(f'"{user_row["name"]}" removido do ministério (conta preservada).', "success")
    return redirect(url_for("leader_members"))


@app.route("/lider/membros/<int:user_id>/recrutar", methods=["POST"])
@leader_required
def leader_mark_recruta(user_id):
    mid = current_user.ministry_id
    if not mid:
        abort(403)

    user_row = models.get_user_by_id(user_id)
    if not user_row or user_row["ministry_id"] != mid or user_row["role"] != "volunteer":
        abort(404)

    try:
        models.mark_as_recruta(user_id)
        flash(f'"{user_row["name"]}" marcado como recruta.', "success")
    except Exception as e:
        flash(f"Erro ao marcar como recruta: {e}", "error")
    return redirect(url_for("leader_members"))


@app.route("/lider/membros/<int:user_id>/promover", methods=["POST"])
@leader_required
def leader_promote_recruta(user_id):
    mid = current_user.ministry_id
    if not mid:
        abort(403)

    user_row = models.get_user_by_id(user_id)
    if not user_row or user_row["ministry_id"] != mid or user_row["role"] != "recruta":
        abort(404)

    try:
        models.promote_recruta(user_id)
        flash(f'"{user_row["name"]}" promovido a voluntário!', "success")
    except Exception as e:
        flash(f"Erro ao promover: {e}", "error")
    return redirect(url_for("leader_members"))


@app.route("/lider/recrutas/<int:user_id>/acompanhantes")
@leader_required
def leader_recruta_companions(user_id):
    mid = current_user.ministry_id
    if not mid:
        abort(403)

    user_row = models.get_user_by_id(user_id)
    if not user_row or user_row["ministry_id"] != mid or user_row["role"] != "recruta":
        abort(404)

    companions = models.list_recruta_companions(user_id)
    all_members = models.list_volunteers_by_ministry(mid)
    companion_ids = {c["id"] for c in companions}
    eligible = [m for m in all_members if m["id"] != user_id and m["id"] not in companion_ids]

    return render_template(
        "leader/recruta_companions.html",
        recruta=user_row,
        companions=companions,
        eligible=eligible,
    )


@app.route("/lider/recrutas/<int:user_id>/acompanhantes/adicionar", methods=["POST"])
@leader_required
def leader_add_companion(user_id):
    mid = current_user.ministry_id
    if not mid:
        abort(403)

    user_row = models.get_user_by_id(user_id)
    if not user_row or user_row["ministry_id"] != mid or user_row["role"] != "recruta":
        abort(404)

    companion_id = request.form.get("companion_id", type=int)
    if not companion_id:
        flash("Selecione um acompanhante.", "error")
        return redirect(url_for("leader_recruta_companions", user_id=user_id))

    companion = models.get_user_by_id(companion_id)
    if not companion or companion["ministry_id"] != mid:
        abort(400)

    models.add_recruta_companion(user_id, companion_id)
    flash(f'"{companion["name"]}" adicionado como acompanhante.', "success")
    return redirect(url_for("leader_recruta_companions", user_id=user_id))


@app.route("/lider/recrutas/<int:user_id>/acompanhantes/<int:entry_id>/remover", methods=["POST"])
@leader_required
def leader_remove_companion(user_id, entry_id):
    mid = current_user.ministry_id
    if not mid:
        abort(403)

    user_row = models.get_user_by_id(user_id)
    if not user_row or user_row["ministry_id"] != mid or user_row["role"] != "recruta":
        abort(404)

    models.remove_recruta_companion(entry_id, user_id)
    flash("Acompanhante removido.", "success")
    return redirect(url_for("leader_recruta_companions", user_id=user_id))


# ── Leader: join requests ──────────────────────────────────────────────────────

@app.route("/lider/solicitacoes")
@leader_required
def leader_join_requests():
    mid = current_user.ministry_id
    if not mid:
        abort(403)
    requests_list = models.list_pending_requests_for_ministry(mid)
    registrations  = models.list_pending_registrations_for_ministry(mid)
    return render_template("leader/join_requests.html",
                           requests=requests_list,
                           registrations=registrations)


@app.route("/lider/solicitacoes/<int:request_id>/aprovar", methods=["POST"])
@leader_required
def leader_approve_request(request_id):
    mid = current_user.ministry_id
    if not mid:
        abort(403)

    req = models.get_join_request(request_id)
    if not req or req["ministry_id"] != mid:
        abort(404)

    try:
        models.approve_join_request(request_id)

        # Gera e envia OTP
        code    = f"{secrets.randbelow(1000000):06d}"
        expires = datetime.now(timezone.utc) + timedelta(minutes=15)
        models.create_otp(req["user_id"], code, expires)
        email_service.send_otp_email(req["email"], req["name"], code)

        flash(f"Solicitação de {req['name']} aprovada. Código de acesso enviado por e-mail.", "success")
    except Exception as e:
        flash(f"Erro ao aprovar: {e}", "error")

    return redirect(url_for("leader_join_requests"))


@app.route("/lider/solicitacoes/<int:request_id>/recusar", methods=["POST"])
@leader_required
def leader_reject_request(request_id):
    mid = current_user.ministry_id
    if not mid:
        abort(403)

    req = models.get_join_request(request_id)
    if not req or req["ministry_id"] != mid:
        abort(404)

    models.reject_join_request(request_id)
    flash(f"Solicitação de {req['name']} recusada.", "info")
    return redirect(url_for("leader_join_requests"))


@app.route("/lider/cadastros/<int:reg_id>/aprovar", methods=["POST"])
@leader_required
def leader_approve_registration(reg_id):
    mid = current_user.ministry_id
    if not mid:
        abort(403)

    reg = models.get_pending_registration(reg_id)
    if not reg or reg["ministry_id"] != mid:
        abort(404)

    # Verifica se e-mail já foi cadastrado entre a solicitação e aprovação
    existing = models.get_user_by_email(reg["email"])
    if existing:
        models.approve_pending_registration(reg_id)
        flash(f"E-mail {reg['email']} já possui conta. Solicitação descartada.", "warning")
        return redirect(url_for("leader_join_requests"))

    try:
        from werkzeug.security import generate_password_hash as _gph
        pw_hash = _gph(secrets.token_hex(24))  # senha aleatória inacessível
        models.create_user(reg["name"], reg["email"], pw_hash, "volunteer", mid)
        user = models.get_user_by_email(reg["email"])

        models.approve_pending_registration(reg_id)

        # Gera e envia OTP
        code    = f"{secrets.randbelow(1000000):06d}"
        expires = datetime.now(timezone.utc) + timedelta(minutes=15)
        models.create_otp(user["id"], code, expires)
        email_service.send_otp_email(reg["email"], reg["name"], code)

        flash(f"Cadastro de {reg['name']} aprovado. Código de acesso enviado por e-mail.", "success")
    except Exception as e:
        flash(f"Erro ao aprovar cadastro: {e}", "error")

    return redirect(url_for("leader_join_requests"))


@app.route("/lider/cadastros/<int:reg_id>/recusar", methods=["POST"])
@leader_required
def leader_reject_registration(reg_id):
    mid = current_user.ministry_id
    if not mid:
        abort(403)

    reg = models.get_pending_registration(reg_id)
    if not reg or reg["ministry_id"] != mid:
        abort(404)

    models.reject_pending_registration(reg_id)
    flash(f"Cadastro de {reg['name']} recusado.", "info")
    return redirect(url_for("leader_join_requests"))


# ── Admin (General Leader) ─────────────────────────────────────────────────────

@app.route("/admin")
@admin_required
def admin_dashboard():
    ministries = models.list_ministries()
    users = models.list_users()
    periods = models.list_all_periods()

    stats = {
        "ministries": len(ministries),
        "users": len(users),
        "open_periods": sum(1 for p in periods if p["status"] == "open"),
        "confirmed_periods": sum(1 for p in periods if p["status"] == "confirmed"),
    }

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        periods=periods[:15],
    )


@app.route("/admin/ministerios")
@admin_required
def admin_ministries():
    ministries = models.list_ministries()
    return render_template("admin/ministries.html", ministries=ministries)


@app.route("/admin/ministerios/novo", methods=["POST"])
@admin_required
def admin_create_ministry():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Informe o nome do ministério.", "error")
        return redirect(url_for("admin_ministries"))

    try:
        models.create_ministry(name)
        flash(f'Ministério "{name}" criado!', "success")
    except Exception:
        flash("Já existe um ministério com este nome.", "error")

    return redirect(url_for("admin_ministries"))


@app.route("/admin/ministerios/<int:ministry_id>")
@admin_required
def admin_ministry_detail(ministry_id):
    ministry = models.get_ministry(ministry_id)
    if not ministry:
        abort(404)

    members = models.list_users_by_ministry(ministry_id)
    periods = models.list_periods_by_ministry(ministry_id)

    return render_template(
        "admin/ministry.html",
        ministry=ministry,
        members=members,
        periods=periods,
    )


@app.route("/admin/ministerios/<int:ministry_id>/excluir", methods=["POST"])
@admin_required
def admin_delete_ministry(ministry_id):
    models.delete_ministry(ministry_id)
    flash("Ministério removido.", "success")
    return redirect(url_for("admin_ministries"))


@app.route("/admin/usuarios")
@admin_required
def admin_users():
    users = models.list_users()
    return render_template("admin/users.html", users=users)


@app.route("/admin/usuarios/novo", methods=["GET", "POST"])
@admin_required
def admin_create_user():
    ministries = models.list_ministries()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "volunteer")
        ministry_id = request.form.get("ministry_id", type=int) or None

        if not name or not email or not password:
            flash("Preencha todos os campos obrigatórios.", "error")
            return render_template(
                "admin/user_form.html", ministries=ministries, user=None
            )

        if role not in ("volunteer", "recruta", "ministry_leader", "general_leader"):
            flash("Perfil inválido.", "error")
            return render_template(
                "admin/user_form.html", ministries=ministries, user=None
            )

        try:
            models.create_user(name, email, generate_password_hash(password), role, ministry_id)
            flash(f'Usuário "{name}" criado!', "success")
            return redirect(url_for("admin_users"))
        except Exception:
            flash("Já existe um usuário com este e-mail.", "error")

    return render_template("admin/user_form.html", ministries=ministries, user=None)


@app.route("/admin/usuarios/<int:user_id>/editar", methods=["GET", "POST"])
@admin_required
def admin_edit_user(user_id):
    user_row = models.get_user_by_id(user_id)
    if not user_row:
        abort(404)

    ministries = models.list_ministries()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        role = request.form.get("role", "volunteer")
        ministry_id = request.form.get("ministry_id", type=int) or None
        new_password = request.form.get("password", "").strip()

        if not name or not email:
            flash("Nome e e-mail são obrigatórios.", "error")
            return render_template(
                "admin/user_form.html", ministries=ministries, user=user_row
            )

        try:
            models.update_user(user_id, name, email, role, ministry_id)
            if new_password:
                models.update_user_password(
                    user_id, generate_password_hash(new_password)
                )
            flash("Usuário atualizado.", "success")
            return redirect(url_for("admin_users"))
        except Exception as e:
            flash(f"Erro ao atualizar: {e}", "error")

    return render_template(
        "admin/user_form.html", ministries=ministries, user=user_row
    )


@app.route("/admin/usuarios/<int:user_id>/excluir", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    if user_id == current_user.id:
        flash("Você não pode excluir sua própria conta.", "error")
        return redirect(url_for("admin_users"))

    models.delete_user(user_id)
    flash("Usuário removido.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/escalas")
@admin_required
def admin_schedules():
    periods = models.list_all_periods()
    return render_template("admin/schedules.html", periods=periods)


@app.route("/admin/eventos")
@admin_required
def admin_events():
    events = models.list_events()
    return render_template("admin/events.html", events=events)


@app.route("/admin/eventos/novo", methods=["POST"])
@admin_required
def admin_create_event():
    title       = request.form.get("title", "").strip()
    event_date  = request.form.get("event_date", "").strip()
    end_date    = request.form.get("end_date", "").strip() or None
    event_time  = request.form.get("event_time", "").strip() or None
    description = request.form.get("description", "").strip() or None
    if not title or not event_date:
        flash("Título e data são obrigatórios.", "error")
        return redirect(url_for("admin_events"))
    for_leaders = request.form.get("target") != "all"
    notify_all = not for_leaders
    models.create_event(title, event_date, description, for_leaders=for_leaders, notify_all=notify_all, event_time=event_time, end_date=end_date)
    audience = "líderes" if for_leaders else "todos"
    flash(f'Evento "{title}" criado para {audience}!', "success")
    return redirect(url_for("admin_events"))


# ── Leader Events ──────────────────────────────────────────────────────────────

@app.route("/lider/eventos")
@leader_required
def leader_events():
    mid = current_user.ministry_id
    if not mid:
        abort(403)
    events = models.list_events_for_ministry(mid)
    return render_template("leader/events.html", events=events)


@app.route("/lider/eventos/novo", methods=["POST"])
@leader_required
def leader_create_event():
    mid = current_user.ministry_id
    if not mid:
        abort(403)
    title       = request.form.get("title", "").strip()
    event_date  = request.form.get("event_date", "").strip()
    end_date    = request.form.get("end_date", "").strip() or None
    event_time  = request.form.get("event_time", "").strip() or None
    description = request.form.get("description", "").strip() or None
    if not title or not event_date:
        flash("Título e data são obrigatórios.", "error")
        return redirect(url_for("leader_events"))
    models.create_event(title, event_date, description, ministry_id=mid, notify_all=True, event_time=event_time, end_date=end_date)
    flash(f'Evento "{title}" criado!', "success")
    return redirect(url_for("leader_events"))


@app.route("/lider/eventos/<int:event_id>/excluir", methods=["POST"])
@leader_required
def leader_delete_event(event_id):
    event = models.get_event(event_id)
    if not event or event["ministry_id"] != current_user.ministry_id:
        abort(403)
    models.delete_event(event_id)
    flash("Evento removido.", "success")
    return redirect(url_for("leader_events"))


@app.route("/admin/eventos/<int:event_id>/excluir", methods=["POST"])
@admin_required
def admin_delete_event(event_id):
    event = models.get_event(event_id)
    if not event:
        abort(404)
    models.delete_event(event_id)
    flash("Evento removido.", "success")
    return redirect(url_for("admin_events"))


# ── Errors ─────────────────────────────────────────────────────────────────────

@app.errorhandler(403)
def forbidden(e):
    return render_template("errors/403.html"), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("errors/404.html"), 404


# ── Init ───────────────────────────────────────────────────────────────────────

with app.app_context():
    database.init_db()


if __name__ == "__main__":
    app.run(debug=True, port=5001)
