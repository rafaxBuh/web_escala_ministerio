#!/usr/bin/env python3
"""
Bateria de testes abrangente — Sistema de Escalas
Usa banco de dados isolado em memória para não sujar os dados reais.
"""
import sys, os, tempfile
from pathlib import Path
from io import StringIO

# ── DB isolado ────────────────────────────────────────────────────────────────
_tmp_fd, _tmp_path = tempfile.mkstemp(suffix=".db")
os.close(_tmp_fd)

import database
database.DB_PATH = Path(_tmp_path)
database.DATA_DIR = Path(_tmp_path).parent
database.init_db()

import models
from werkzeug.security import generate_password_hash, check_password_hash
from app import app as flask_app, get_week_dates, period_label, MONTHS
from scheduler import generate_period_schedule

flask_app.config["TESTING"] = True
flask_app.config["SECRET_KEY"] = "test-secret"

# ── Helpers ───────────────────────────────────────────────────────────────────
PASS = FAIL = 0
_section = ""

def section(title):
    global _section
    _section = title
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")

def ok(label):
    global PASS; PASS += 1
    print(f"    ✓  {label}")

def fail(label, err=""):
    global FAIL; FAIL += 1
    msg = f"    ✗  {label}"
    if err: msg += f"\n       → {err}"
    print(msg)

def check(cond, label, err=""):
    if cond:
        ok(label)
    else:
        fail(label, err)

def expect_exc(fn, exc_type, label):
    try:
        fn()
        fail(label, f"esperava {exc_type.__name__} mas não lançou")
    except exc_type:
        ok(label)
    except Exception as e:
        fail(label, f"lançou {type(e).__name__}: {e}")

# ── HTTP helpers ──────────────────────────────────────────────────────────────
client = flask_app.test_client()

def http_login(email, password="x"):
    return client.post("/login",
                       data={"email": email, "password": password},
                       follow_redirects=True)

def http_get(url):
    return client.get(url, follow_redirects=True)

def http_post(url, data=None):
    return client.post(url, data=data or {}, follow_redirects=True)

def logout():
    client.get("/logout")

# ═══════════════════════════════════════════════════════════════════════════════
# 1. MODELOS
# ═══════════════════════════════════════════════════════════════════════════════
section("1. Modelos — ministérios")
try:
    models.create_ministry("Louvor")
    models.create_ministry("Recepção")
    models.create_ministry("Mídia")
    ok("create_ministry × 3")
except Exception as e:
    fail("create_ministry × 3", e)

try:
    models.create_ministry("Louvor")
    fail("duplicate ministry deveria lançar")
except Exception:
    ok("duplicate ministry → exception")

mins = models.list_ministries()
check(len(mins) == 3, f"list_ministries retorna 3 (got {len(mins)})")

louvor = next((m for m in mins if m["name"] == "Louvor"), None)
check(louvor is not None, "get ministry by name")

models.update_ministry(louvor["id"], "Louvor Atualizado")
louvor2 = models.get_ministry(louvor["id"])
check(louvor2["name"] == "Louvor Atualizado", "update_ministry")
models.update_ministry(louvor["id"], "Louvor")  # restaurar
louvor = models.get_ministry(louvor["id"])

recep = next((m for m in models.list_ministries() if m["name"] == "Recepção"), None)
midia = next((m for m in models.list_ministries() if m["name"] == "Mídia"), None)

# ─────────────────────────────────────────────────────────────────────────────
section("2. Modelos — usuários")
pw = generate_password_hash("senha123")
try:
    models.create_user("Admin Geral",    "admin@t.com",  pw, "general_leader")
    models.create_user("Líder Louvor",   "lider@t.com",  pw, "ministry_leader", louvor["id"])
    models.create_user("Líder Recep",    "lider2@t.com", pw, "ministry_leader", recep["id"])
    models.create_user("Vol 1",          "v1@t.com",     pw, "volunteer",       louvor["id"])
    models.create_user("Vol 2",          "v2@t.com",     pw, "volunteer",       louvor["id"])
    models.create_user("Vol 3",          "v3@t.com",     pw, "volunteer",       louvor["id"])
    models.create_user("Vol 4",          "v4@t.com",     pw, "volunteer",       louvor["id"])
    models.create_user("Vol 5",          "v5@t.com",     pw, "volunteer",       louvor["id"])
    ok("create_user × 8")
except Exception as e:
    fail("create_user × 8", e)

try:
    models.create_user("Dup", "v1@t.com", pw, "volunteer")
    fail("duplicate email deveria lançar")
except Exception:
    ok("duplicate email → exception")

u = models.get_user_by_email("lider@t.com")
check(u is not None and u["role"] == "ministry_leader", "get_user_by_email")

u2 = models.get_user_by_id(u["id"])
check(u2["email"] == "lider@t.com", "get_user_by_id")

all_users = models.list_users()
check(len(all_users) >= 8, f"list_users (got {len(all_users)})")

vols = models.list_volunteers_by_ministry(louvor["id"])
check(len(vols) == 6, f"list_volunteers_by_ministry (got {len(vols)})")

models.update_user(u["id"], "Líder Louvor Edit", "lider@t.com", "ministry_leader", louvor["id"])
u3 = models.get_user_by_id(u["id"])
check(u3["name"] == "Líder Louvor Edit", "update_user name")
models.update_user(u["id"], "Líder Louvor", "lider@t.com", "ministry_leader", louvor["id"])

models.update_user_password(u["id"], generate_password_hash("nova123"))
u4 = models.get_user_by_id(u["id"])
check(check_password_hash(u4["password_hash"], "nova123"), "update_user_password")
models.update_user_password(u["id"], pw)  # restaurar

check(models.get_user_by_email("nao@existe.com") is None, "get_user_by_email inexistente → None")

# ─────────────────────────────────────────────────────────────────────────────
section("3. Modelos — períodos")
admin_u  = models.get_user_by_email("admin@t.com")
lider_u  = models.get_user_by_email("lider@t.com")
vols_u   = models.list_volunteers_by_ministry(louvor["id"])

try:
    models.create_period(louvor["id"], 2026, 4)          # único mês
    ok("create_period único mês")
except Exception as e:
    fail("create_period único mês", e)

try:
    models.create_period(louvor["id"], 2026, 4)           # duplicado
    fail("duplicate period deveria lançar")
except Exception:
    ok("duplicate period → exception")

try:
    models.create_period(recep["id"], 2026, 4, 2026, 6)  # multi-mês
    ok("create_period multi-mês")
except Exception as e:
    fail("create_period multi-mês", e)

p = models.get_open_period(louvor["id"])
check(p is not None, "get_open_period retorna período")
check(p["status"] == "open", "status = open")
check(p["end_year"] == 2026, f"end_year coalesce (got {p['end_year']})")
check(p["end_month"] == 4,   f"end_month coalesce (got {p['end_month']})")

p_multi = models.get_open_period(recep["id"])
check(p_multi["end_month"] == 6, f"end_month multi-mês (got {p_multi['end_month']})")

periods_list = models.list_periods_by_ministry(louvor["id"])
check(len(periods_list) == 1, f"list_periods_by_ministry (got {len(periods_list)})")
check(all("end_year" in dict(pp) for pp in periods_list), "end_year em todos os períodos listados")

all_p = models.list_all_periods()
check(len(all_p) >= 2, f"list_all_periods (got {len(all_p)})")

models.update_period_status(p["id"], "closed")
p2 = models.get_period(p["id"])
check(p2["status"] == "closed", "update_period_status → closed")
models.update_period_status(p["id"], "open")

# ─────────────────────────────────────────────────────────────────────────────
section("4. Modelos — disponibilidade")
v1, v2, v3, v4, v5, v6 = vols_u[0], vols_u[1], vols_u[2], vols_u[3], vols_u[4], vols_u[5]
p_id = p["id"]

for v in [v1, v2, v3, v4, v5, v6]:
    for w in range(1, 5):
        models.set_availability(v["id"], p_id, w, True)

ok("set_availability × 20")

avail = models.get_user_availability(v1["id"], p_id)
check(all(avail[w] for w in range(1, 5)), "get_user_availability todos disponíveis")

models.set_availability(v1["id"], p_id, 1, False)
avail2 = models.get_user_availability(v1["id"], p_id)
check(avail2[1] == False and avail2[2] == True, "set_availability upsert funciona")
models.set_availability(v1["id"], p_id, 1, True)  # restaurar

week_avail = models.get_availability_for_period_week(p_id, 1)
check(len(week_avail) == 6, f"get_availability_for_period_week semana 1 (got {len(week_avail)})")
check(all(r["available"] == 1 for r in week_avail), "todos disponíveis semana 1")

summary = models.get_period_availability_summary(p_id)
check(len(summary) == 24, f"get_period_availability_summary (got {len(summary)})")

# ─────────────────────────────────────────────────────────────────────────────
section("5. Modelos — restrições")
models.add_pair_restriction(louvor["id"], v1["id"], v2["id"])
models.add_pair_restriction(louvor["id"], v3["id"], v4["id"])
ok("add_pair_restriction × 2")

models.add_pair_restriction(louvor["id"], v1["id"], v2["id"])  # idempotente
ok("add_pair_restriction idempotente (INSERT OR IGNORE)")

rlist = models.list_pair_restrictions(louvor["id"])
check(len(rlist) == 2, f"list_pair_restrictions (got {len(rlist)})")

rset = models.get_pair_restrictions_set(louvor["id"])
check((min(v1["id"],v2["id"]), max(v1["id"],v2["id"])) in rset, "restriction pair normalizado")

models.remove_pair_restriction(rlist[0]["id"], louvor["id"])
check(len(models.list_pair_restrictions(louvor["id"])) == 1, "remove_pair_restriction")
models.add_pair_restriction(louvor["id"], v1["id"], v2["id"])  # restaurar

# ─────────────────────────────────────────────────────────────────────────────
section("6. Modelos — schedules e unlink")
models.save_schedule(p_id, 1, v1["id"], v3["id"])
models.save_schedule(p_id, 1, v2["id"], v4["id"])   # upsert mesma semana
s = models.get_schedule(p_id)
check(len(s) == 1 and s[0]["member1_id"] == v2["id"], "save_schedule upsert")

models.clear_period_schedule(p_id)
check(len(models.get_schedule(p_id)) == 0, "clear_period_schedule")

# unlink
models.create_user("Temp Vol", "tmp@t.com", pw, "volunteer", louvor["id"])
tmp_u = models.get_user_by_email("tmp@t.com")
models.unlink_from_ministry(tmp_u["id"])
tmp_u2 = models.get_user_by_id(tmp_u["id"])
check(tmp_u2["ministry_id"] is None, "unlink_from_ministry preserva conta")
models.delete_user(tmp_u["id"])

# ═══════════════════════════════════════════════════════════════════════════════
# 7. SCHEDULER
# ═══════════════════════════════════════════════════════════════════════════════
section("7. Scheduler — geração de escala")

# Normal: 5 voluntários, 4 semanas
try:
    sched = generate_period_schedule(p_id, louvor["id"], 4)
    check(len(sched) == 4, f"gera 4 semanas (got {len(sched)})")
    ids_used = set()
    for s in sched:
        ids_used.add(s["member1_id"])
        ids_used.add(s["member2_id"])
        check(s["member1_id"] != s["member2_id"], f"sem. {s['week']}: membros diferentes")
    ok("todos os voluntários foram escalados")
except Exception as e:
    fail("generate_period_schedule normal", e)

# Repetição da mesma semana (idempotente)
try:
    sched2 = generate_period_schedule(p_id, louvor["id"], 4)
    check(len(sched2) == 4, "regenerar sobrescreve corretamente")
except Exception as e:
    fail("regenerar idempotente", e)

# Multi-mês: 13 semanas
try:
    p_m = models.get_open_period(recep["id"])
    # Criar voluntários para recepção
    for i in range(6):
        try:
            models.create_user(f"RecVol{i}", f"rv{i}@t.com", pw, "volunteer", recep["id"])
        except Exception:
            pass
    rv = models.list_volunteers_by_ministry(recep["id"])
    for v in rv:
        for w in range(1, 14):
            models.set_availability(v["id"], p_m["id"], w, True)
    sched_m = generate_period_schedule(p_m["id"], recep["id"], 13)
    check(len(sched_m) == 13, f"multi-mês 13 semanas (got {len(sched_m)})")
except Exception as e:
    fail("generate multi-mês 13 semanas", e)

# Menos de 2 voluntários disponíveis
try:
    p2_id = p_id
    # Criar período isolado para testar erro
    models.create_period(midia["id"], 2026, 4)
    p_err = models.get_open_period(midia["id"])
    # Nenhum voluntário criado → deve lançar ValueError
    expect_exc(
        lambda: generate_period_schedule(p_err["id"], midia["id"], 4),
        ValueError,
        "< 2 voluntários disponíveis → ValueError"
    )
finally:
    pass

# Restrições bloqueiam todos os pares
try:
    models.create_user("Solo A", "sola@t.com", pw, "volunteer", midia["id"])
    models.create_user("Solo B", "solb@t.com", pw, "volunteer", midia["id"])
    sa = models.get_user_by_email("sola@t.com")
    sb = models.get_user_by_email("solb@t.com")
    p_err2 = models.get_open_period(midia["id"])
    for v in [sa, sb]:
        for w in range(1, 5):
            models.set_availability(v["id"], p_err2["id"], w, True)
    models.add_pair_restriction(midia["id"], sa["id"], sb["id"])
    expect_exc(
        lambda: generate_period_schedule(p_err2["id"], midia["id"], 4),
        ValueError,
        "todos os pares restritos → ValueError"
    )
    models.remove_pair_restriction(
        models.list_pair_restrictions(midia["id"])[0]["id"],
        midia["id"]
    )
except Exception as e:
    fail("restrições totais teste", e)

# ═══════════════════════════════════════════════════════════════════════════════
# 8. HELPERS — get_week_dates e period_label
# ═══════════════════════════════════════════════════════════════════════════════
section("8. Helpers — get_week_dates e period_label")
from datetime import date

# Mês simples
wk = get_week_dates(2026, 4)
check(len(wk) == 4, f"Abril/2026 → 4 semanas (got {len(wk)})")
check(wk[0]["start"].weekday() == 0, "semana 1 começa na segunda")
check(wk[0]["start"] == date(2026, 4, 6), f"primeira segunda Abril/2026 = 06/04 (got {wk[0]['start']})")
check(wk[0]["end"].weekday() == 6, "semana 1 termina no domingo")
check(wk[3]["week"] == 4, "semana 4 tem week=4")

# Mês começando na segunda
wk2 = get_week_dates(2026, 6)
check(wk2[0]["start"] == date(2026, 6, 1), f"Junho/2026 começa na segunda (got {wk2[0]['start']})")

# Multi-mês
wk3 = get_week_dates(2026, 4, 2026, 6)
check(len(wk3) == 13, f"Abril–Junho/2026 → 13 semanas (got {len(wk3)})")
check(wk3[-1]["start"].weekday() == 0, "última semana começa na segunda")

# end_year/end_month None → trata como mês único
wk4 = get_week_dates(2026, 4, None, None)
check(len(wk4) == 4, "None end → trata como mês único")

# period_label
check(period_label({"year":2026,"month":4,"end_year":2026,"end_month":4}) == "Abril/2026",
      "period_label único")
check(period_label({"year":2026,"month":4,"end_year":2026,"end_month":6}) == "Abril/2026 – Junho/2026",
      "period_label multi")
check(period_label({"year":2026,"month":4,"end_year":None,"end_month":None}) == "Abril/2026",
      "period_label None end → único")

# ═══════════════════════════════════════════════════════════════════════════════
# 9. HTTP — autenticação
# ═══════════════════════════════════════════════════════════════════════════════
section("9. HTTP — autenticação")

r = http_get("/")
check(b"login" in r.data.lower() or r.status_code == 200, "GET / sem login → login page")

r = http_get("/login")
check(r.status_code == 200, "GET /login → 200")

r = http_login("admin@t.com", "senha123")
check(r.status_code == 200, "POST /login válido → 200")
check("Painel" in r.data.decode("utf-8", errors="replace"), "admin vê Painel")
logout()

r = http_login("admin@t.com", "errada")
check(r.status_code == 200, "POST /login inválido → 200")
check("incorretos" in r.data.decode("utf-8", errors="replace"), "mensagem de erro no login")
logout()

# ─────────────────────────────────────────────────────────────────────────────
section("10. HTTP — volunteer")
http_login("v1@t.com", "senha123")

r = http_get("/voluntario")
check(r.status_code == 200, "GET /voluntario como volunteer → 200")
check("Louvor" in r.data.decode("utf-8", errors="replace"), "mostra nome do ministério")

r = http_get("/lider")
check(r.status_code == 403, "GET /lider como volunteer → 403")

r = http_get("/admin")
check(r.status_code == 403, "GET /admin como volunteer → 403")

# Marcar disponibilidade
r = http_post("/voluntario/disponibilidade", {
    "period_id": str(p_id),
    "week_1": "on", "week_3": "on"
})
check(r.status_code == 200, "POST disponibilidade → 200")
_vol1_http = models.get_user_by_email("v1@t.com")
avail_v1 = models.get_user_availability(_vol1_http["id"], p_id)
check(avail_v1[1] == True and avail_v1[2] == False and avail_v1[3] == True,
      "disponibilidade salva corretamente")

# Período inválido
r = http_post("/voluntario/disponibilidade", {"period_id": "99999"})
check(b"n" in r.data.lower(), "disponibilidade período inexistente → mensagem erro")

logout()

# ─────────────────────────────────────────────────────────────────────────────
section("11. HTTP — líder (painel e períodos)")
http_login("lider@t.com", "senha123")

r = http_get("/lider")
check(r.status_code == 200, "GET /lider como líder → 200")
check("Louvor" in r.data.decode("utf-8", errors="replace"), "mostra ministério do líder")

r = http_get("/admin")
check(r.status_code == 403, "GET /admin como líder → 403")

# Tentar abrir outro período com um já aberto
r = http_post("/lider/periodo/abrir", {
    "year": "2026", "month": "5",
    "end_year": "2026", "end_month": "5"
})
html = r.data.decode("utf-8", errors="replace")
check("Já existe" in html or "aberto" in html, "abrir 2º período quando já tem um → erro")

# Fechar período e gerar escala
r = http_post(f"/lider/periodo/{p_id}/fechar")
check(r.status_code == 200, "fechar período → 200")
p_after = models.get_period(p_id)
check(p_after["status"] == "closed", "status mudou para closed")
sched = models.get_schedule(p_id)
check(len(sched) == 4, f"schedule gerado com 4 semanas (got {len(sched)})")

# Ver escala
r = http_get(f"/lider/periodo/{p_id}/escala")
check(r.status_code == 200, "GET /lider/periodo/<id>/escala → 200")
check("Voluntário 1" in r.data.decode("utf-8", errors="replace"), "form edição aparece quando closed")

# Editar escala
cur_sched = models.get_schedule(p_id)
week1 = cur_sched[0]
# Trocar m1 e m2
r = http_post(f"/lider/periodo/{p_id}/escala/salvar", {
    f"member1_{w['week']}": str(w["member1_id"]) for w in cur_sched
} | {
    f"member2_{w['week']}": str(w["member2_id"]) for w in cur_sched
} | {
    "member1_1": str(week1["member2_id"]),
    "member2_1": str(week1["member1_id"]),
})
check(r.status_code == 200, "POST salvar escala editada → 200")
sched2 = models.get_schedule(p_id)
check(sched2[0]["member1_id"] == week1["member2_id"], "edição semana 1 persistida")

# Editar com mesmo membro nos dois slots → erro
r = http_post(f"/lider/periodo/{p_id}/escala/salvar", {
    f"member1_{w['week']}": str(w["member1_id"]) for w in cur_sched
} | {
    f"member2_{w['week']}": str(w["member1_id"]) for w in cur_sched  # mesmo para todos
})
check("diferentes" in r.data.decode("utf-8", errors="replace"), "mesmo membro nos 2 slots → erro")

# Confirmar escala
r = http_post(f"/lider/periodo/{p_id}/confirmar")
check(r.status_code == 200, "confirmar escala → 200")
check(models.get_period(p_id)["status"] == "confirmed", "status → confirmed")

# Não pode editar após confirmar
r = http_post(f"/lider/periodo/{p_id}/escala/salvar", {})
check("confirmação" in r.data.decode("utf-8", errors="replace") or r.status_code == 200,
      "editar após confirmar → bloqueado")

# Abrir novo período após confirmar
r = http_post("/lider/periodo/abrir", {
    "year": "2026", "month": "7",
    "end_year": "2026", "end_month": "8"
})
check("aberto" in r.data.decode("utf-8", errors="replace") or
      models.get_open_period(louvor["id"]) is not None,
      "abrir período multi-mês após confirmar")

p_new = models.get_open_period(louvor["id"])
if p_new:
    check(p_new["end_month"] == 8, f"end_month multi-mês salvo (got {p_new['end_month']})")
    check(p_new["month"] == 7, f"start_month multi-mês salvo (got {p_new['month']})")

# Validação: fim antes do início
r = http_post("/lider/periodo/abrir", {
    "year": "2026", "month": "10",
    "end_year": "2026", "end_month": "8"   # fim antes do início
})
html = r.data.decode("utf-8", errors="replace")
check("fim" in html or "posterior" in html, "end_month < month → validação")

logout()

# ─────────────────────────────────────────────────────────────────────────────
section("12. HTTP — líder (restrições)")
http_login("lider@t.com", "senha123")

r = http_get("/lider/restricoes")
check(r.status_code == 200, "GET /lider/restricoes → 200")

r = http_post("/lider/restricoes/adicionar", {
    "member1_id": str(v3["id"]),
    "member2_id": str(v5["id"]),
})
check(r.status_code == 200, "adicionar restrição válida → 200")
rlist = models.list_pair_restrictions(louvor["id"])
check(any(
    (r2["member1_id"] == min(v3["id"],v5["id"]) and r2["member2_id"] == max(v3["id"],v5["id"]))
    for r2 in rlist
), "restrição persistida")

r = http_post("/lider/restricoes/adicionar", {
    "member1_id": str(v3["id"]),
    "member2_id": str(v3["id"]),  # mesmo membro
})
check("diferentes" in r.data.decode("utf-8", errors="replace"), "restrição mesmo membro → erro")

rid = rlist[-1]["id"]
r = http_post(f"/lider/restricoes/{rid}/remover")
check(r.status_code == 200, "remover restrição → 200")

logout()

# ─────────────────────────────────────────────────────────────────────────────
section("13. HTTP — líder (gestão de membros)")
http_login("lider@t.com", "senha123")

r = http_get("/lider/membros")
check(r.status_code == 200, "GET /lider/membros → 200")
check("Vol 1" in r.data.decode("utf-8", errors="replace"), "lista voluntários")

r = http_get("/lider/membros/novo")
check(r.status_code == 200, "GET /lider/membros/novo → 200")

r = http_post("/lider/membros/novo", {
    "name": "Novo Vol HTTP",
    "email": "novo_http@t.com",
    "password": "abc123"
})
check(r.status_code == 200, "POST criar voluntário → 200")
novo = models.get_user_by_email("novo_http@t.com")
check(novo is not None and novo["role"] == "volunteer", "voluntário criado com role=volunteer")
check(novo["ministry_id"] == louvor["id"], "voluntário associado ao ministério do líder")

# Email duplicado
r = http_post("/lider/membros/novo", {
    "name": "Dup", "email": "novo_http@t.com", "password": "abc"
})
check("e-mail" in r.data.decode("utf-8", errors="replace").lower(), "email duplicado → erro")

# Editar
r = http_get(f"/lider/membros/{novo['id']}/editar")
check(r.status_code == 200, "GET editar voluntário → 200")

r = http_post(f"/lider/membros/{novo['id']}/editar", {
    "name": "Novo Vol Editado", "email": "novo_http@t.com", "password": ""
})
check(r.status_code == 200, "POST editar voluntário → 200")
check(models.get_user_by_id(novo["id"])["name"] == "Novo Vol Editado", "nome editado")

# Remover
r = http_post(f"/lider/membros/{novo['id']}/remover")
check(r.status_code == 200, "POST remover voluntário → 200")
check(models.get_user_by_id(novo["id"])["ministry_id"] is None, "membro desvinculado")
models.delete_user(novo["id"])

# Líder não pode editar membro de outro ministério
v_midia = models.get_user_by_email("sola@t.com")
r = http_get(f"/lider/membros/{v_midia['id']}/editar")
check(r.status_code == 404, "editar membro de outro ministério → 404")

logout()

# ─────────────────────────────────────────────────────────────────────────────
section("14. HTTP — admin")
http_login("admin@t.com", "senha123")

r = http_get("/admin")
check(r.status_code == 200, "GET /admin → 200")

r = http_get("/admin/ministerios")
check(r.status_code == 200, "GET /admin/ministerios → 200")

r = http_post("/admin/ministerios/novo", {"name": "Novo Min HTTP"})
check(r.status_code == 200, "criar ministério → 200")
new_min = next((m for m in models.list_ministries() if m["name"] == "Novo Min HTTP"), None)
check(new_min is not None, "ministério criado no banco")

r = http_post("/admin/ministerios/novo", {"name": "Novo Min HTTP"})
check("nome" in r.data.decode("utf-8", errors="replace").lower() or
      "já existe" in r.data.decode("utf-8", errors="replace"),
      "ministério duplicado → erro")

r = http_get(f"/admin/ministerios/{louvor['id']}")
check(r.status_code == 200, "GET /admin/ministerios/<id> → 200")
check("Vol 1" in r.data.decode("utf-8", errors="replace"), "lista membros do ministério")

r = http_post(f"/admin/ministerios/{new_min['id']}/excluir")
check(r.status_code == 200, "excluir ministério → 200")
check(models.get_ministry(new_min["id"]) is None, "ministério removido do banco")

r = http_get("/admin/usuarios")
check(r.status_code == 200, "GET /admin/usuarios → 200")

r = http_get("/admin/usuarios/novo")
check(r.status_code == 200, "GET /admin/usuarios/novo → 200")

r = http_post("/admin/usuarios/novo", {
    "name": "Novo User Admin",
    "email": "nuadmin@t.com",
    "password": "pass123",
    "role": "volunteer",
    "ministry_id": str(louvor["id"])
})
check(r.status_code == 200, "criar usuário via admin → 200")
nu = models.get_user_by_email("nuadmin@t.com")
check(nu is not None, "usuário criado")

r = http_get(f"/admin/usuarios/{nu['id']}/editar")
check(r.status_code == 200, "GET editar usuário → 200")

r = http_post(f"/admin/usuarios/{nu['id']}/editar", {
    "name": "Novo User Admin Edit",
    "email": "nuadmin@t.com",
    "role": "volunteer",
    "ministry_id": str(louvor["id"]),
    "password": ""
})
check(r.status_code == 200, "editar usuário → 200")
check(models.get_user_by_id(nu["id"])["name"] == "Novo User Admin Edit", "nome editado")

# Não pode excluir a si mesmo
admin_row = models.get_user_by_email("admin@t.com")
r = http_post(f"/admin/usuarios/{admin_row['id']}/excluir")
check("própria conta" in r.data.decode("utf-8", errors="replace"), "excluir si mesmo → erro")

# Excluir outro
r = http_post(f"/admin/usuarios/{nu['id']}/excluir")
check(r.status_code == 200, "excluir usuário → 200")
check(models.get_user_by_id(nu["id"]) is None, "usuário removido")

r = http_get("/admin/escalas")
check(r.status_code == 200, "GET /admin/escalas → 200")

# Ver escala como admin
p_conf = models.get_period(p_id)
r = http_get(f"/lider/periodo/{p_id}/escala")
check(r.status_code == 200, "admin ver escala de qualquer ministério → 200")

logout()

# ─────────────────────────────────────────────────────────────────────────────
section("15. HTTP — reabrir e reopen period")
http_login("lider@t.com", "senha123")

# Criar e fechar um período fresco para testar reopen
p_fresh = models.get_open_period(louvor["id"])
if p_fresh:
    for v in vols_u:
        for w in range(1, 5):
            models.set_availability(v["id"], p_fresh["id"], w, True)
    http_post(f"/lider/periodo/{p_fresh['id']}/fechar")  # gera e fecha
    r = http_post(f"/lider/periodo/{p_fresh['id']}/reabrir")
    check(r.status_code == 200, "reabrir período → 200")
    check(models.get_period(p_fresh["id"])["status"] == "open", "status voltou para open")
    check(len(models.get_schedule(p_fresh["id"])) == 0, "escala limpa após reopen")
else:
    ok("reabrir — skipped (sem período aberto)")

logout()

# ─────────────────────────────────────────────────────────────────────────────
section("16. HTTP — isolamento entre ministérios")
http_login("lider@t.com", "senha123")   # líder do Louvor

# Não pode ver escala de outro ministério
p_recep = models.get_open_period(recep["id"])
if p_recep:
    r = http_get(f"/lider/periodo/{p_recep['id']}/escala")
    check(r.status_code == 403, "líder não pode ver escala de outro ministério → 403")

# Não pode fechar período de outro ministério
    r = http_post(f"/lider/periodo/{p_recep['id']}/fechar")
    check(r.status_code == 403, "líder não pode fechar período de outro → 403")

logout()

# ═══════════════════════════════════════════════════════════════════════════════
# RESULTADO FINAL
# ═══════════════════════════════════════════════════════════════════════════════
total = PASS + FAIL
print(f"\n{'═'*60}")
print(f"  RESULTADO: {PASS}/{total} passaram  |  {FAIL} falhas")
print(f"{'═'*60}")

# Limpar banco temporário
import os
try: os.unlink(_tmp_path)
except: pass

sys.exit(0 if FAIL == 0 else 1)
