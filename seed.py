"""
Script de seed: cria dados iniciais para testar o sistema.
Execute uma vez após criar o banco:  python seed.py
"""
from werkzeug.security import generate_password_hash
import database
import models

database.init_db()

# ── Admin geral ────────────────────────────────────────────────────────────────
try:
    models.create_user(
        name="Rafael",
        email="rafael.buhll@gmail.com",
        password_hash=generate_password_hash("21051977"),
        role="general_leader",
    )
    print("Admin criado: rafael.buhll@gmail.com / 21051977")
except Exception:
    print("Admin já existe.")

# ── Ministérios de exemplo ─────────────────────────────────────────────────────
for nome in ["Louvor", "Recepção", "Mídia"]:
    try:
        models.create_ministry(nome)
        print(f"Ministério criado: {nome}")
    except Exception:
        print(f"Ministério já existe: {nome}")

ministerios = {m["name"]: m["id"] for m in models.list_ministries()}

# ── Líder do Louvor ────────────────────────────────────────────────────────────
try:
    models.create_user(
        name="João Silva",
        email="joao@escalas.com",
        password_hash=generate_password_hash("lider123"),
        role="ministry_leader",
        ministry_id=ministerios.get("Louvor"),
    )
    print("Líder criado: joao@escalas.com / lider123 (Louvor)")
except Exception:
    print("Líder já existe.")

# ── Voluntários do Louvor ──────────────────────────────────────────────────────
voluntarios_louvor = [
    ("Maria Santos", "maria@escalas.com"),
    ("Pedro Oliveira", "pedro@escalas.com"),
    ("Ana Costa", "ana@escalas.com"),
    ("Carlos Lima", "carlos@escalas.com"),
    ("Lucia Ferreira", "lucia@escalas.com"),
]

for nome, email in voluntarios_louvor:
    try:
        models.create_user(
            name=nome,
            email=email,
            password_hash=generate_password_hash("vol123"),
            role="volunteer",
            ministry_id=ministerios.get("Louvor"),
        )
        print(f"Voluntário criado: {email} / vol123")
    except Exception:
        print(f"Voluntário já existe: {email}")

print("\nSeed concluído!")
print("Acesse /login com:")
print("  Admin:      admin@escalas.com / admin123")
print("  Líder:      joao@escalas.com  / lider123")
print("  Voluntário: maria@escalas.com / vol123")
