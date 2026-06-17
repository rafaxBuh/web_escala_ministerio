# Sistema de Escalas

Sistema web em Flask para gerenciar escalas de voluntários em ministérios de uma igreja.

## Perfis

| Perfil | Acesso |
|--------|--------|
| `volunteer` | Marca disponibilidade no período aberto; vê escala confirmada |
| `ministry_leader` | Abre/fecha períodos, gera e confirma escala, gerencia restrições |
| `general_leader` | Acesso total: cria ministérios, usuários, vê todas as escalas |

## Instalação local

```bash
# 1. Crie e ative o ambiente virtual
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/Mac

# 2. Instale as dependências
pip install -r requirements.txt

# 3. Popule o banco com dados de exemplo
python seed.py

# 4. Inicie o servidor
python app.py
```

Acesse: http://localhost:5000

### Usuários criados pelo seed

| E-mail | Senha | Perfil |
|--------|-------|--------|
| admin@escalas.com | admin123 | Administrador Geral |
| joao@escalas.com | lider123 | Líder (Louvor) |
| maria@escalas.com | vol123 | Voluntária (Louvor) |

## Estrutura

```
web/
├── app.py          # Flask app + todas as rotas
├── database.py     # Conexão SQLite e init_db()
├── models.py       # Funções de acesso ao banco
├── scheduler.py    # Algoritmo de geração de escala
├── seed.py         # Dados de exemplo
├── requirements.txt
├── data/
│   └── escalas.db  # Banco gerado automaticamente
├── static/
│   └── style.css
└── templates/
    ├── base.html
    ├── login.html
    ├── volunteer/dashboard.html
    ├── leader/
    │   ├── dashboard.html
    │   ├── schedule.html
    │   └── restrictions.html
    ├── admin/
    │   ├── dashboard.html
    │   ├── ministries.html
    │   ├── ministry.html
    │   ├── users.html
    │   ├── user_form.html
    │   └── schedules.html
    └── errors/
        ├── 403.html
        └── 404.html
```

## Fluxo de uso

1. **Admin** cria ministérios e usuários (líderes + voluntários)
2. **Líder** abre um período (mês/ano)
3. **Voluntários** fazem login e marcam disponibilidade por semana
4. **Líder** clica em "Gerar Escala" → sistema seleciona duplas automaticamente
5. **Líder** revisa e confirma → escala fica visível para todos

### Algoritmo de escala

O algoritmo realiza rodízio justo entre os voluntários disponíveis:
- Evita repetir pessoas da semana anterior
- Minimiza o uso acumulado (equilíbrio)
- Evita repetir a mesma dupla
- Respeita restrições de par cadastradas

## Deploy no Render

1. Suba o código em um repositório GitHub
2. No Render, crie um **Web Service**:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn app:app`
3. Em **Environment Variables**, adicione:
   - `SECRET_KEY` → uma string aleatória segura (ex.: `python -c "import secrets; print(secrets.token_hex(32))"`)
4. Para persistência do banco SQLite, use um **Persistent Disk** montado em `/data`
   - No `database.py`, ajuste `DATA_DIR` para usar a variável de ambiente:
     ```python
     DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR / "data")))
     ```

> **Nota:** SQLite em disco no Render funciona com Persistent Disk. Para produção com múltiplas instâncias, migre para PostgreSQL.
