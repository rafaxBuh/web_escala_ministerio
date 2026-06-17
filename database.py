import os
import datetime
import psycopg2
import psycopg2.extras
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DATABASE_URL", "")
# Render às vezes entrega "postgres://", psycopg2 exige "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)


def _serialize(row):
    """Converte datetime/date para string ISO para compatibilidade com templates."""
    if row is None:
        return None
    return {
        k: v.isoformat() if isinstance(v, (datetime.datetime, datetime.date)) else v
        for k, v in row.items()
    }


class _Cursor:
    """Cursor wrapper que converte datas automaticamente."""

    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        return _serialize(self._cur.fetchone())

    def fetchall(self):
        return [_serialize(r) for r in self._cur.fetchall()]


class _Conn:
    """Wrapper fino sobre psycopg2 que imita a API do sqlite3.Connection."""

    def __init__(self, raw_conn):
        self._conn = raw_conn
        self._cur = raw_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def execute(self, sql, params=None):
        self._cur.execute(sql, params)
        return _Cursor(self._cur)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._cur.close()
        self._conn.close()


def get_connection():
    return _Conn(psycopg2.connect(DATABASE_URL))


@contextmanager
def db_conn():
    """Context manager que sempre fecha a conexão, mesmo em exceção."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def _migrate_role_constraint():
    raw = psycopg2.connect(DATABASE_URL)
    raw.autocommit = True
    cur = raw.cursor()
    try:
        # Drop constraints antigas que mencionam 'role' (exceto a correta)
        cur.execute(
            "SELECT conname FROM pg_constraint"
            " WHERE conrelid = 'users'::regclass"
            "   AND contype = 'c'"
            "   AND pg_get_constraintdef(oid) LIKE %s"
            "   AND conname != 'users_role_check'",
            ('%role%',),
        )
        for (name,) in cur.fetchall():
            cur.execute(
                psycopg2.sql.SQL("ALTER TABLE users DROP CONSTRAINT IF EXISTS {}").format(
                    psycopg2.sql.Identifier(name)
                )
            )
        # Adiciona sem erro se já existir
        cur.execute("""
            DO $$ BEGIN
                ALTER TABLE users ADD CONSTRAINT users_role_check
                    CHECK(role IN ('volunteer', 'recruta', 'ministry_leader', 'general_leader'));
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
        """)
    finally:
        cur.close()
        raw.close()


def init_db():
    with db_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ministries (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('volunteer', 'recruta', 'ministry_leader', 'general_leader')),
                ministry_id INTEGER REFERENCES ministries(id) ON DELETE SET NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS periods (
                id SERIAL PRIMARY KEY,
                ministry_id INTEGER NOT NULL REFERENCES ministries(id) ON DELETE CASCADE,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                end_year INTEGER,
                end_month INTEGER,
                status TEXT NOT NULL DEFAULT 'open'
                    CHECK(status IN ('open', 'closed', 'confirmed')),
                UNIQUE(ministry_id, year, month)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS availability (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                period_id INTEGER NOT NULL REFERENCES periods(id) ON DELETE CASCADE,
                week INTEGER NOT NULL,
                available INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, period_id, week)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS schedules (
                id SERIAL PRIMARY KEY,
                period_id INTEGER NOT NULL REFERENCES periods(id) ON DELETE CASCADE,
                week INTEGER NOT NULL,
                member1_id INTEGER NOT NULL REFERENCES users(id),
                member2_id INTEGER NOT NULL REFERENCES users(id),
                member3_id INTEGER REFERENCES users(id),
                UNIQUE(period_id, week)
            )
        """)
        conn.execute("ALTER TABLE schedules ADD COLUMN IF NOT EXISTS member3_id INTEGER REFERENCES users(id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS pair_restrictions (
                id SERIAL PRIMARY KEY,
                ministry_id INTEGER NOT NULL REFERENCES ministries(id) ON DELETE CASCADE,
                member1_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                member2_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(ministry_id, member1_id, member2_id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                event_date TEXT NOT NULL,
                event_time TEXT,
                description TEXT,
                ministry_id INTEGER REFERENCES ministries(id) ON DELETE CASCADE,
                for_leaders BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Migração: garante colunas em tabelas existentes
        conn.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS ministry_id INTEGER REFERENCES ministries(id) ON DELETE CASCADE")
        conn.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS for_leaders BOOLEAN NOT NULL DEFAULT FALSE")
        conn.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS notify_all BOOLEAN NOT NULL DEFAULT FALSE")
        conn.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS end_date TEXT")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS event_schedule_members (
                id SERIAL PRIMARY KEY,
                event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                slot_date TEXT NOT NULL,
                period TEXT NOT NULL CHECK(period IN ('manha', 'tarde', 'noite')),
                member_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(event_id, slot_date, period, member_id)
            )
        """)
        conn.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS event_time TEXT")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token TEXT NOT NULL UNIQUE,
                expires_at TIMESTAMP NOT NULL,
                used BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_otps (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                code TEXT NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                used BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                endpoint TEXT NOT NULL UNIQUE,
                subscription_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS recruta_companions (
                id SERIAL PRIMARY KEY,
                recruta_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                companion_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(recruta_id, companion_id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS join_requests (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'approved', 'rejected')),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_registrations (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                ministry_id INTEGER NOT NULL REFERENCES ministries(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'approved', 'rejected')),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        conn.commit()

    # Migração da constraint de role feita em conexão separada com autocommit
    # para garantir que DDL seja aplicado mesmo em bancos existentes.
    _migrate_role_constraint()
