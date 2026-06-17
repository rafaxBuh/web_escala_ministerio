from database import db_conn


# ── Users ──────────────────────────────────────────────────────────────────────

def get_user_by_id(user_id):
    with db_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()


def get_user_by_email(email):
    with db_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE email = %s", (email.strip().lower(),)
        ).fetchone()


def create_user(name, email, password_hash, role, ministry_id=None):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role, ministry_id) VALUES (%s,%s,%s,%s,%s)",
            (name.strip(), email.strip().lower(), password_hash, role, ministry_id),
        )
        conn.commit()


def update_user(user_id, name, email, role, ministry_id):
    with db_conn() as conn:
        conn.execute(
            "UPDATE users SET name=%s, email=%s, role=%s, ministry_id=%s WHERE id=%s",
            (name.strip(), email.strip().lower(), role, ministry_id, user_id),
        )
        conn.commit()


def update_user_password(user_id, password_hash):
    with db_conn() as conn:
        conn.execute("UPDATE users SET password_hash=%s WHERE id=%s", (password_hash, user_id))
        conn.commit()


def delete_user(user_id):
    with db_conn() as conn:
        conn.execute("DELETE FROM schedules WHERE member1_id=%s OR member2_id=%s", (user_id, user_id))
        conn.execute("DELETE FROM users WHERE id=%s", (user_id,))
        conn.commit()


def list_users():
    with db_conn() as conn:
        return conn.execute("""
            SELECT u.*, m.name AS ministry_name
            FROM users u
            LEFT JOIN ministries m ON m.id = u.ministry_id
            ORDER BY u.name
        """).fetchall()


def list_users_by_ministry(ministry_id):
    with db_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE ministry_id = %s ORDER BY name",
            (ministry_id,),
        ).fetchall()


def list_volunteers_by_ministry(ministry_id):
    with db_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE ministry_id = %s AND role IN ('volunteer', 'recruta', 'ministry_leader') ORDER BY name",
            (ministry_id,),
        ).fetchall()


# ── Ministries ─────────────────────────────────────────────────────────────────

def create_ministry(name):
    with db_conn() as conn:
        conn.execute("INSERT INTO ministries (name) VALUES (%s)", (name.strip(),))
        conn.commit()


def list_ministries():
    with db_conn() as conn:
        return conn.execute("SELECT * FROM ministries ORDER BY name").fetchall()


def get_ministry(ministry_id):
    with db_conn() as conn:
        return conn.execute("SELECT * FROM ministries WHERE id=%s", (ministry_id,)).fetchone()


def update_ministry(ministry_id, name):
    with db_conn() as conn:
        conn.execute("UPDATE ministries SET name=%s WHERE id=%s", (name.strip(), ministry_id))
        conn.commit()


def delete_ministry(ministry_id):
    with db_conn() as conn:
        conn.execute("DELETE FROM ministries WHERE id=%s", (ministry_id,))
        conn.commit()


# ── Periods ────────────────────────────────────────────────────────────────────

def create_period(ministry_id, year, month, end_year=None, end_month=None):
    if end_year is None:
        end_year = year
    if end_month is None:
        end_month = month
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO periods (ministry_id, year, month, end_year, end_month, status)"
            " VALUES (%s,%s,%s,%s,%s,'open')",
            (ministry_id, year, month, end_year, end_month),
        )
        conn.commit()


def get_period(period_id):
    with db_conn() as conn:
        return conn.execute("""
            SELECT p.id, p.ministry_id, p.year, p.month,
                   COALESCE(p.end_year,  p.year)  AS end_year,
                   COALESCE(p.end_month, p.month) AS end_month,
                   p.status,
                   m.name AS ministry_name
            FROM periods p
            JOIN ministries m ON m.id = p.ministry_id
            WHERE p.id = %s
        """, (period_id,)).fetchone()


def get_open_period(ministry_id):
    with db_conn() as conn:
        return conn.execute("""
            SELECT id, ministry_id, year, month,
                   COALESCE(end_year,  year)  AS end_year,
                   COALESCE(end_month, month) AS end_month,
                   status
            FROM periods WHERE ministry_id=%s AND status='open'
        """, (ministry_id,)).fetchone()


def list_periods_by_ministry(ministry_id):
    with db_conn() as conn:
        return conn.execute("""
            SELECT id, ministry_id, year, month,
                   COALESCE(end_year,  year)  AS end_year,
                   COALESCE(end_month, month) AS end_month,
                   status
            FROM periods WHERE ministry_id=%s ORDER BY year DESC, month DESC
        """, (ministry_id,)).fetchall()


def list_all_periods():
    with db_conn() as conn:
        return conn.execute("""
            SELECT p.id, p.ministry_id, p.year, p.month,
                   COALESCE(p.end_year,  p.year)  AS end_year,
                   COALESCE(p.end_month, p.month) AS end_month,
                   p.status,
                   m.name AS ministry_name
            FROM periods p
            JOIN ministries m ON m.id = p.ministry_id
            ORDER BY p.year DESC, p.month DESC, m.name
        """).fetchall()


def update_period_status(period_id, status):
    with db_conn() as conn:
        conn.execute("UPDATE periods SET status=%s WHERE id=%s", (status, period_id))
        conn.commit()


# ── Availability ───────────────────────────────────────────────────────────────

def set_availability(user_id, period_id, week, available):
    with db_conn() as conn:
        conn.execute("""
            INSERT INTO availability (user_id, period_id, week, available)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT(user_id, period_id, week)
            DO UPDATE SET available = excluded.available
        """, (user_id, period_id, week, 1 if available else 0))
        conn.commit()


def get_user_availability(user_id, period_id):
    """Returns dict {week: available_bool} for all weeks in the period."""
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT week, available FROM availability WHERE user_id=%s AND period_id=%s",
            (user_id, period_id),
        ).fetchall()
    result = {w: False for w in range(1, 5)}
    for row in rows:
        result[row["week"]] = bool(row["available"])
    return result


def get_availability_for_period_week(period_id, week):
    """
    Returns all volunteers in the ministry for the given period/week,
    with their availability. Used by the scheduler.
    """
    with db_conn() as conn:
        return conn.execute("""
            SELECT u.id, u.name, u.role,
                   COALESCE(a.available, 0) AS available
            FROM users u
            JOIN periods p ON p.id = %s
            LEFT JOIN availability a
                ON a.user_id = u.id
               AND a.period_id = %s
               AND a.week = %s
            WHERE u.ministry_id = p.ministry_id
              AND u.role IN ('volunteer', 'recruta', 'ministry_leader')
            ORDER BY u.name
        """, (period_id, period_id, week)).fetchall()


def get_period_availability_summary(period_id):
    """For the leader view: who marked availability per week."""
    with db_conn() as conn:
        return conn.execute("""
            SELECT u.name, a.week, a.available
            FROM availability a
            JOIN users u ON u.id = a.user_id
            WHERE a.period_id = %s
            ORDER BY a.week, u.name
        """, (period_id,)).fetchall()


# ── Schedules ──────────────────────────────────────────────────────────────────

def save_schedule(period_id, week, member1_id, member2_id):
    with db_conn() as conn:
        conn.execute("""
            INSERT INTO schedules (period_id, week, member1_id, member2_id)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT(period_id, week)
            DO UPDATE SET member1_id=excluded.member1_id,
                          member2_id=excluded.member2_id
        """, (period_id, week, member1_id, member2_id))
        conn.commit()


def clear_period_schedule(period_id):
    with db_conn() as conn:
        conn.execute("DELETE FROM schedules WHERE period_id=%s", (period_id,))
        conn.commit()


def get_schedule(period_id):
    with db_conn() as conn:
        return conn.execute("""
            SELECT s.week,
                   m1.name AS member1, m1.id AS member1_id,
                   m2.name AS member2, m2.id AS member2_id
            FROM schedules s
            JOIN users m1 ON m1.id = s.member1_id
            JOIN users m2 ON m2.id = s.member2_id
            WHERE s.period_id = %s
            ORDER BY s.week
        """, (period_id,)).fetchall()


# ── Pair Restrictions ──────────────────────────────────────────────────────────

def add_pair_restriction(ministry_id, member1_id, member2_id):
    a, b = sorted([member1_id, member2_id])
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO pair_restrictions (ministry_id, member1_id, member2_id)"
            " VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
            (ministry_id, a, b),
        )
        conn.commit()


def remove_pair_restriction(restriction_id, ministry_id):
    with db_conn() as conn:
        conn.execute(
            "DELETE FROM pair_restrictions WHERE id=%s AND ministry_id=%s",
            (restriction_id, ministry_id),
        )
        conn.commit()


def list_pair_restrictions(ministry_id):
    with db_conn() as conn:
        return conn.execute("""
            SELECT pr.id,
                   m1.name AS member1_name, m1.id AS member1_id,
                   m2.name AS member2_name, m2.id AS member2_id
            FROM pair_restrictions pr
            JOIN users m1 ON m1.id = pr.member1_id
            JOIN users m2 ON m2.id = pr.member2_id
            WHERE pr.ministry_id = %s
            ORDER BY m1.name, m2.name
        """, (ministry_id,)).fetchall()


# ── Leader: member management ──────────────────────────────────────────────────

def unlink_from_ministry(user_id):
    """Remove o vínculo do usuário com o ministério (preserva histórico de escalas)."""
    with db_conn() as conn:
        conn.execute("UPDATE users SET ministry_id=NULL WHERE id=%s", (user_id,))
        conn.commit()


# ── Pair Restrictions ──────────────────────────────────────────────────────────

def get_pair_restrictions_set(ministry_id):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT member1_id, member2_id FROM pair_restrictions WHERE ministry_id=%s",
            (ministry_id,),
        ).fetchall()
    return {tuple(sorted((r["member1_id"], r["member2_id"]))) for r in rows}


# ── Events ─────────────────────────────────────────────────────────────────────

def list_events():
    """Todos os eventos — usado pelo admin geral."""
    with db_conn() as conn:
        return conn.execute(
            "SELECT * FROM events ORDER BY event_date ASC"
        ).fetchall()


def list_events_for_ministry(ministry_id):
    """Eventos do ministério + eventos para líderes."""
    with db_conn() as conn:
        return conn.execute("""
            SELECT * FROM events
            WHERE ministry_id = %s OR for_leaders = TRUE
            ORDER BY event_date ASC
        """, (ministry_id,)).fetchall()


def list_upcoming_events(from_date_iso):
    with db_conn() as conn:
        return conn.execute(
            "SELECT * FROM events WHERE event_date >= %s ORDER BY event_date ASC",
            (from_date_iso,),
        ).fetchall()


def list_upcoming_events_for_user(from_date_iso, ministry_id, role):
    """Filtra eventos futuros de acordo com o papel do usuário."""
    with db_conn() as conn:
        if role == "general_leader":
            return conn.execute(
                "SELECT * FROM events WHERE event_date >= %s ORDER BY event_date ASC",
                (from_date_iso,),
            ).fetchall()
        if role == "ministry_leader":
            return conn.execute("""
                SELECT * FROM events
                WHERE event_date >= %s
                  AND (ministry_id = %s
                       OR for_leaders = TRUE
                       OR (ministry_id IS NULL AND for_leaders = FALSE))
                ORDER BY event_date ASC
            """, (from_date_iso, ministry_id)).fetchall()
        # volunteer / recruta: retorna eventos do ministério sem for_leaders
        # A rota decide quais mostrar com base na escala e notify_all
        return conn.execute("""
            SELECT * FROM events
            WHERE event_date >= %s
              AND for_leaders = FALSE
              AND (ministry_id = %s OR ministry_id IS NULL)
            ORDER BY event_date ASC
        """, (from_date_iso, ministry_id)).fetchall()


def get_event(event_id):
    with db_conn() as conn:
        return conn.execute(
            "SELECT * FROM events WHERE id = %s", (event_id,)
        ).fetchone()


def create_event(title, event_date_iso, description=None, ministry_id=None, for_leaders=False, notify_all=False, event_time=None):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO events (title, event_date, event_time, description, ministry_id, for_leaders, notify_all) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (title.strip(), event_date_iso, event_time or None, description, ministry_id, for_leaders, notify_all),
        )
        conn.commit()


def create_event_if_not_exists(title, event_date_iso, description=None, ministry_id=None, for_leaders=False):
    """Cria evento apenas se ainda não existe um com o mesmo título, data e ministério."""
    with db_conn() as conn:
        exists = conn.execute(
            "SELECT id FROM events WHERE title = %s AND event_date = %s AND ministry_id IS NOT DISTINCT FROM %s",
            (title, event_date_iso, ministry_id),
        ).fetchone()
        if exists:
            return
        conn.execute(
            "INSERT INTO events (title, event_date, description, ministry_id, for_leaders) VALUES (%s,%s,%s,%s,%s)",
            (title, event_date_iso, description, ministry_id, for_leaders),
        )
        conn.commit()


def delete_event(event_id):
    with db_conn() as conn:
        conn.execute("DELETE FROM events WHERE id = %s", (event_id,))
        conn.commit()


# ── Password Reset Tokens ──────────────────────────────────────────────────────

def create_reset_token(user_id, token, expires_at):
    with db_conn() as conn:
        # Invalida tokens anteriores do mesmo usuário
        conn.execute(
            "UPDATE password_reset_tokens SET used = TRUE WHERE user_id = %s AND used = FALSE",
            (user_id,)
        )
        conn.execute(
            "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (%s, %s, %s)",
            (user_id, token, expires_at),
        )
        conn.commit()


def get_valid_reset_token(token):
    with db_conn() as conn:
        return conn.execute("""
            SELECT * FROM password_reset_tokens
            WHERE token = %s AND used = FALSE AND expires_at > NOW()
        """, (token,)).fetchone()


def mark_token_used(token):
    with db_conn() as conn:
        conn.execute(
            "UPDATE password_reset_tokens SET used = TRUE WHERE token = %s",
            (token,)
        )
        conn.commit()


# ── Email OTP ──────────────────────────────────────────────────────────────────

def create_otp(user_id, code, expires_at):
    with db_conn() as conn:
        conn.execute(
            "UPDATE email_otps SET used = TRUE WHERE user_id = %s AND used = FALSE",
            (user_id,),
        )
        conn.execute(
            "INSERT INTO email_otps (user_id, code, expires_at) VALUES (%s, %s, %s)",
            (user_id, code, expires_at),
        )
        conn.commit()


def get_valid_otp(user_id, code):
    with db_conn() as conn:
        return conn.execute("""
            SELECT * FROM email_otps
            WHERE user_id = %s AND code = %s AND used = FALSE AND expires_at > NOW()
        """, (user_id, code)).fetchone()


def mark_otp_used(user_id):
    with db_conn() as conn:
        conn.execute(
            "UPDATE email_otps SET used = TRUE WHERE user_id = %s AND used = FALSE",
            (user_id,),
        )
        conn.commit()


# ── Push Subscriptions ─────────────────────────────────────────────────────────

def save_push_subscription(user_id, endpoint, subscription_json):
    with db_conn() as conn:
        conn.execute("""
            INSERT INTO push_subscriptions (user_id, endpoint, subscription_json)
            VALUES (%s, %s, %s)
            ON CONFLICT (endpoint) DO UPDATE SET user_id = EXCLUDED.user_id
        """, (user_id, endpoint, subscription_json))
        conn.commit()


def delete_push_subscription(endpoint):
    with db_conn() as conn:
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = %s", (endpoint,))
        conn.commit()


def get_user_subscriptions(user_id):
    with db_conn() as conn:
        return conn.execute(
            "SELECT subscription_json FROM push_subscriptions WHERE user_id = %s",
            (user_id,),
        ).fetchall()


def get_ministry_subscriptions(ministry_id):
    with db_conn() as conn:
        return conn.execute("""
            SELECT ps.subscription_json
            FROM push_subscriptions ps
            JOIN users u ON u.id = ps.user_id
            WHERE u.ministry_id = %s
        """, (ministry_id,)).fetchall()


def get_all_subscriptions():
    with db_conn() as conn:
        return conn.execute(
            "SELECT user_id, subscription_json FROM push_subscriptions"
        ).fetchall()


def get_confirmed_periods_all():
    with db_conn() as conn:
        return conn.execute("""
            SELECT p.*, m.name AS ministry_name
            FROM periods p
            JOIN ministries m ON m.id = p.ministry_id
            WHERE p.status = 'confirmed'
        """).fetchall()


# ── Recruta Companions ─────────────────────────────────────────────────────────

def list_recruta_companions(recruta_id):
    """Retorna lista de voluntários que podem acompanhar o recruta."""
    with db_conn() as conn:
        return conn.execute("""
            SELECT u.id, u.name, u.role, rc.id AS companion_entry_id
            FROM recruta_companions rc
            JOIN users u ON u.id = rc.companion_id
            WHERE rc.recruta_id = %s
            ORDER BY u.name
        """, (recruta_id,)).fetchall()


def get_recruta_companions_dict(ministry_id):
    """
    Retorna dict {recruta_id: set(companion_ids)} para recrutas com pelo menos
    um acompanhante definido, no ministério informado.
    """
    with db_conn() as conn:
        rows = conn.execute("""
            SELECT rc.recruta_id, rc.companion_id
            FROM recruta_companions rc
            JOIN users u ON u.id = rc.recruta_id
            WHERE u.ministry_id = %s
        """, (ministry_id,)).fetchall()

    result = {}
    for row in rows:
        result.setdefault(row["recruta_id"], set()).add(row["companion_id"])
    return result


def add_recruta_companion(recruta_id, companion_id):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO recruta_companions (recruta_id, companion_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
            (recruta_id, companion_id),
        )
        conn.commit()


def remove_recruta_companion(entry_id, recruta_id):
    with db_conn() as conn:
        conn.execute(
            "DELETE FROM recruta_companions WHERE id = %s AND recruta_id = %s",
            (entry_id, recruta_id),
        )
        conn.commit()


def mark_as_recruta(user_id):
    """Marca um voluntário como recruta."""
    with db_conn() as conn:
        conn.execute(
            "UPDATE users SET role = 'recruta' WHERE id = %s AND role = 'volunteer'",
            (user_id,),
        )
        conn.commit()


def promote_recruta(user_id):
    """Promove um recruta para voluntário."""
    with db_conn() as conn:
        conn.execute(
            "UPDATE users SET role = 'volunteer' WHERE id = %s AND role = 'recruta'",
            (user_id,),
        )
        conn.commit()


# ── Join Requests ──────────────────────────────────────────────────────────────

def create_join_request(user_id):
    """Cria solicitação de acesso, invalidando qualquer pendente anterior."""
    with db_conn() as conn:
        conn.execute(
            "UPDATE join_requests SET status = 'rejected' WHERE user_id = %s AND status = 'pending'",
            (user_id,),
        )
        conn.execute(
            "INSERT INTO join_requests (user_id) VALUES (%s)",
            (user_id,),
        )
        conn.commit()


def get_pending_request_for_user(user_id):
    with db_conn() as conn:
        return conn.execute(
            "SELECT * FROM join_requests WHERE user_id = %s AND status = 'pending'",
            (user_id,),
        ).fetchone()


def list_pending_requests_for_ministry(ministry_id):
    with db_conn() as conn:
        return conn.execute("""
            SELECT jr.id, jr.created_at, u.id AS user_id, u.name, u.email
            FROM join_requests jr
            JOIN users u ON u.id = jr.user_id
            WHERE u.ministry_id = %s AND jr.status = 'pending'
            ORDER BY jr.created_at ASC
        """, (ministry_id,)).fetchall()


def count_pending_requests_for_ministry(ministry_id):
    with db_conn() as conn:
        row = conn.execute("""
            SELECT COUNT(*) AS n FROM join_requests jr
            JOIN users u ON u.id = jr.user_id
            WHERE u.ministry_id = %s AND jr.status = 'pending'
        """, (ministry_id,)).fetchone()
        return row["n"] if row else 0


def approve_join_request(request_id):
    with db_conn() as conn:
        conn.execute(
            "UPDATE join_requests SET status = 'approved' WHERE id = %s",
            (request_id,),
        )
        conn.commit()


def reject_join_request(request_id):
    with db_conn() as conn:
        conn.execute(
            "UPDATE join_requests SET status = 'rejected' WHERE id = %s",
            (request_id,),
        )
        conn.commit()


def get_join_request(request_id):
    with db_conn() as conn:
        return conn.execute(
            "SELECT jr.*, u.id AS user_id, u.name, u.email, u.ministry_id"
            " FROM join_requests jr JOIN users u ON u.id = jr.user_id"
            " WHERE jr.id = %s",
            (request_id,),
        ).fetchone()


# ── Pending Registrations ──────────────────────────────────────────────────────

def create_pending_registration(name, email, ministry_id):
    with db_conn() as conn:
        # Invalida cadastros anteriores com o mesmo email
        conn.execute(
            "UPDATE pending_registrations SET status='rejected'"
            " WHERE email=%s AND status='pending'",
            (email.strip().lower(),),
        )
        conn.execute(
            "INSERT INTO pending_registrations (name, email, ministry_id)"
            " VALUES (%s, %s, %s)",
            (name.strip(), email.strip().lower(), ministry_id),
        )
        conn.commit()


def list_pending_registrations_for_ministry(ministry_id):
    with db_conn() as conn:
        return conn.execute("""
            SELECT pr.id, pr.name, pr.email, pr.created_at
            FROM pending_registrations pr
            WHERE pr.ministry_id = %s AND pr.status = 'pending'
            ORDER BY pr.created_at ASC
        """, (ministry_id,)).fetchall()


def count_pending_registrations_for_ministry(ministry_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM pending_registrations"
            " WHERE ministry_id=%s AND status='pending'",
            (ministry_id,),
        ).fetchone()
        return row["n"] if row else 0


def get_pending_registration(reg_id):
    with db_conn() as conn:
        return conn.execute(
            "SELECT * FROM pending_registrations WHERE id=%s",
            (reg_id,),
        ).fetchone()


def approve_pending_registration(reg_id):
    with db_conn() as conn:
        conn.execute(
            "UPDATE pending_registrations SET status='approved' WHERE id=%s",
            (reg_id,),
        )
        conn.commit()


def reject_pending_registration(reg_id):
    with db_conn() as conn:
        conn.execute(
            "UPDATE pending_registrations SET status='rejected' WHERE id=%s",
            (reg_id,),
        )
        conn.commit()
