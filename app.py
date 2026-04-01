from __future__ import annotations

import csv
import io
import logging
import os
import re
import secrets
import sqlite3
import sys
import threading
from collections.abc import Iterable
from contextlib import closing
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any

from flask import Flask, Response, flash, g, has_app_context, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from core.access_control import VALID_ROLES, has_permission

try:
    from openpyxl import Workbook
except Exception:
    Workbook = None

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
except Exception:
    A4 = None
    pdfmetrics = None
    TTFont = None
    canvas = None

try:
    from waitress import serve as waitress_serve
except Exception:
    waitress_serve = None

SOURCE_DIR = Path(__file__).resolve().parent
IS_FROZEN = getattr(sys, 'frozen', False)
BASE_DIR = Path(getattr(sys, '_MEIPASS', SOURCE_DIR)).resolve() if IS_FROZEN else SOURCE_DIR


def resolve_data_dir() -> Path:
    if not IS_FROZEN:
        return SOURCE_DIR

    explicit = (os.getenv('INFINANCE_DATA_DIR') or '').strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    local_app_data = (os.getenv('LOCALAPPDATA') or '').strip()
    if local_app_data:
        return Path(local_app_data).resolve() / 'INFinance'

    return Path(sys.executable).resolve().parent


DATA_DIR = resolve_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE = DATA_DIR / 'infinance.db'
PDF_FONT_NAME = 'INFinanceUnicode'
SECRET_FILE = DATA_DIR / '.infinance.secret'
_BOOTSTRAP_LOCK = threading.Lock()
_BOOTSTRAP_ONCE = threading.Event()

AUTHORS = [
    {
        'name': 'INformigados',
        'role': 'Criador e desenvolvedor principal',
        'github_url': 'https://github.com/informigados',
        'github_display': 'github.com/informigados',
        'image': 'images/authors/informigados.webp',
    },
    {
        'name': 'Alex Brito',
        'role': 'Co-desenvolvedor',
        'github_url': 'https://github.com/AlexBritoDEV',
        'github_display': 'github.com/AlexBritoDEV',
        'image': 'images/authors/alex-brito-dev.webp',
    },
]

PUBLIC_ENDPOINTS = {
    'static',
    'login',
    'favicon_legacy',
}

POST_LOGIN_ENDPOINTS = {
    'dashboard',
    'about',
    'company',
    'clients',
    'services',
    'transactions',
    'expenses',
    'simulator',
    'das_advanced',
    'monthly_report',
    'users',
}
POST_LOGIN_SESSION_KEY = '_post_login_endpoint'

ADMIN_ENDPOINTS = {
    'users',
    'update_user_role',
    'reset_user_password',
}

WRITE_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}
WRITE_EXEMPT_ENDPOINTS = {'logout'}
CLIENTS_PER_PAGE = 12
SERVICES_PER_PAGE = 12
TRANSACTIONS_PER_PAGE = 20
EXPENSES_PER_PAGE = 20
CSRF_EXPIRED_MESSAGE = 'Sua sessão expirou ou o formulário está desatualizado. Recarregue a página e tente novamente.'


def resolve_secret_key() -> str:
    env_key = os.getenv('INFINANCE_SECRET_KEY') or os.getenv('SECRET_KEY')
    if env_key:
        return env_key

    if SECRET_FILE.exists():
        file_key = SECRET_FILE.read_text(encoding='utf-8').strip()
        if file_key:
            return file_key

    # Fallback seguro para execução local com persistência em arquivo.
    generated = secrets.token_hex(32)
    try:
        SECRET_FILE.write_text(generated, encoding='utf-8')
    except OSError as exc:
        logging.getLogger(__name__).warning('Nao foi possivel persistir SECRET_FILE: %s', exc)
    return generated


def resolve_session_cookie_secure() -> bool:
    explicit = (os.getenv('INFINANCE_SESSION_COOKIE_SECURE') or '').strip().lower()
    if explicit in {'1', 'true', 'yes', 'on'}:
        return True
    if explicit in {'0', 'false', 'no', 'off'}:
        return False

    host_raw = (os.getenv('INFINANCE_HOST') or os.getenv('FLASK_RUN_HOST') or '127.0.0.1').strip().lower()
    host = host_raw.split(':', 1)[0]
    return host not in {'127.0.0.1', 'localhost', '::1'}

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / 'templates'),
    static_folder=str(BASE_DIR / 'static'),
)
app.config['SECRET_KEY'] = resolve_secret_key()
app.config['DATABASE'] = str(DATABASE)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = resolve_session_cookie_secure()

SERVICE_TYPES = {
    'operacional': {'label': 'Operacional / Gestão / Suporte', 'default_rate': 0.06},
    'intelectual': {'label': 'Intelectual / Desenvolvimento / Consultoria', 'default_rate': 0.155},
    'personalizado': {'label': 'Personalizado', 'default_rate': 0.0},
}

CHANNELS = {
    'PJ': 'Pessoa Jurídica',
    'PF': 'Pessoa Física',
}

TRANSACTION_STATUS = {
    'recebido': 'Recebido',
    'a_receber': 'A receber',
    'parcial': 'Parcial',
}

EXPENSE_CATEGORIES = {
    'impostos': 'Impostos e Taxas',
    'ferramentas': 'Ferramentas e Software',
    'operacional': 'Operacional',
    'marketing': 'Marketing',
    'financeiro': 'Financeiro',
    'outros': 'Outros',
}

ANNEX_OPTIONS = {
    'I': 'Anexo I',
    'II': 'Anexo II',
    'III': 'Anexo III',
    'IV': 'Anexo IV',
    'V': 'Anexo V',
    'III_V': 'Anexo III ou V (Fator R)',
}

DAS_BRACKETS = {
    'I': [
        {'limit': 180000.0, 'nominal': 0.04, 'deduction': 0.0},
        {'limit': 360000.0, 'nominal': 0.073, 'deduction': 5940.0},
        {'limit': 720000.0, 'nominal': 0.095, 'deduction': 13860.0},
        {'limit': 1800000.0, 'nominal': 0.107, 'deduction': 22500.0},
        {'limit': 3600000.0, 'nominal': 0.143, 'deduction': 87300.0},
        {'limit': 4800000.0, 'nominal': 0.19, 'deduction': 378000.0},
    ],
    'II': [
        {'limit': 180000.0, 'nominal': 0.045, 'deduction': 0.0},
        {'limit': 360000.0, 'nominal': 0.078, 'deduction': 5940.0},
        {'limit': 720000.0, 'nominal': 0.10, 'deduction': 13860.0},
        {'limit': 1800000.0, 'nominal': 0.112, 'deduction': 22500.0},
        {'limit': 3600000.0, 'nominal': 0.147, 'deduction': 85500.0},
        {'limit': 4800000.0, 'nominal': 0.30, 'deduction': 720000.0},
    ],
    'III': [
        {'limit': 180000.0, 'nominal': 0.06, 'deduction': 0.0},
        {'limit': 360000.0, 'nominal': 0.112, 'deduction': 9360.0},
        {'limit': 720000.0, 'nominal': 0.135, 'deduction': 17640.0},
        {'limit': 1800000.0, 'nominal': 0.16, 'deduction': 35640.0},
        {'limit': 3600000.0, 'nominal': 0.21, 'deduction': 125640.0},
        {'limit': 4800000.0, 'nominal': 0.33, 'deduction': 648000.0},
    ],
    'IV': [
        {'limit': 180000.0, 'nominal': 0.045, 'deduction': 0.0},
        {'limit': 360000.0, 'nominal': 0.09, 'deduction': 8100.0},
        {'limit': 720000.0, 'nominal': 0.102, 'deduction': 12420.0},
        {'limit': 1800000.0, 'nominal': 0.14, 'deduction': 39780.0},
        {'limit': 3600000.0, 'nominal': 0.22, 'deduction': 183780.0},
        {'limit': 4800000.0, 'nominal': 0.33, 'deduction': 828000.0},
    ],
    'V': [
        {'limit': 180000.0, 'nominal': 0.155, 'deduction': 0.0},
        {'limit': 360000.0, 'nominal': 0.18, 'deduction': 4500.0},
        {'limit': 720000.0, 'nominal': 0.195, 'deduction': 9900.0},
        {'limit': 1800000.0, 'nominal': 0.205, 'deduction': 17100.0},
        {'limit': 3600000.0, 'nominal': 0.23, 'deduction': 62100.0},
        {'limit': 4800000.0, 'nominal': 0.305, 'deduction': 540000.0},
    ],
}

ALLOWED_SCHEMA_ALTERS: dict[str, dict[str, str]] = {
    'transactions': {
        'status': "TEXT NOT NULL DEFAULT 'recebido'",
        'invoice_number': 'TEXT',
        'invoice_description': 'TEXT',
        'expected_pf_tax': 'REAL NOT NULL DEFAULT 0',
    },
    'services': {
        'cnae_description': 'TEXT',
        'annex': "TEXT NOT NULL DEFAULT 'III'",
        'factor_r_applicable': 'INTEGER NOT NULL DEFAULT 1',
    },
}


def get_db() -> sqlite3.Connection:
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
        g.db.execute('PRAGMA journal_mode = WAL')
        g.db.execute('PRAGMA synchronous = NORMAL')
    return g.db


@app.teardown_appcontext
def close_db(exception: Exception | None) -> None:
    db = g.pop('db', None)
    if db is not None:
        db.close()


def ensure_column(cur: sqlite3.Cursor, table: str, column: str, ddl: str) -> None:
    table_rules = ALLOWED_SCHEMA_ALTERS.get(table)
    if table_rules is None or table_rules.get(column) != ddl:
        raise ValueError(f'Alteração de schema não permitida para {table}.{column}.')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', table) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', column):
        raise ValueError('Identificador de schema inválido.')

    columns = [row['name'] for row in cur.execute(f'PRAGMA table_info({table})').fetchall()]
    if column not in columns:
        cur.execute(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}')


def init_db() -> None:
    if not has_app_context():
        with app.app_context():
            init_db()
        return

    db = get_db()
    with closing(db.cursor()) as cur:
        cur.execute('PRAGMA journal_mode = WAL')
        cur.execute('PRAGMA synchronous = NORMAL')
        cur.executescript(
            '''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'viewer',
                must_change_password INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            );

            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                person_type TEXT NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                service_type TEXT NOT NULL,
                tax_rate REAL NOT NULL,
                cnae TEXT,
                cnae_description TEXT,
                annex TEXT NOT NULL DEFAULT 'III',
                factor_r_applicable INTEGER NOT NULL DEFAULT 1,
                description_template TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                service_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                channel TEXT NOT NULL,
                invoice_issued INTEGER NOT NULL DEFAULT 0,
                invoice_number TEXT,
                invoice_description TEXT,
                expected_pf_tax REAL NOT NULL DEFAULT 0,
                date_received TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'recebido',
                notes TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (client_id) REFERENCES clients(id),
                FOREIGN KEY (service_id) REFERENCES services(id)
            );

            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'outros',
                amount REAL NOT NULL,
                date_incurred TEXT NOT NULL,
                is_fixed INTEGER NOT NULL DEFAULT 0,
                notes TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS company_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                company_name TEXT NOT NULL DEFAULT 'INFinance Company',
                legal_name TEXT,
                tax_regime TEXT NOT NULL DEFAULT 'Simples Nacional',
                employees_count INTEGER NOT NULL DEFAULT 1,
                payroll_monthly REAL NOT NULL DEFAULT 0,
                prolabore_monthly REAL NOT NULL DEFAULT 0,
                notes TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date_received);
            CREATE INDEX IF NOT EXISTS idx_transactions_client_id ON transactions(client_id);
            CREATE INDEX IF NOT EXISTS idx_transactions_service_id ON transactions(service_id);
            CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(date_incurred);
            '''
        )

        ensure_column(cur, 'transactions', 'status', "TEXT NOT NULL DEFAULT 'recebido'")
        ensure_column(cur, 'transactions', 'invoice_number', 'TEXT')
        ensure_column(cur, 'transactions', 'invoice_description', 'TEXT')
        ensure_column(cur, 'transactions', 'expected_pf_tax', 'REAL NOT NULL DEFAULT 0')
        ensure_column(cur, 'services', 'cnae_description', 'TEXT')
        ensure_column(cur, 'services', 'annex', "TEXT NOT NULL DEFAULT 'III'")
        ensure_column(cur, 'services', 'factor_r_applicable', 'INTEGER NOT NULL DEFAULT 1')

        db.commit()


def seed_data() -> None:
    if not has_app_context():
        with app.app_context():
            seed_data()
        return

    db = get_db()
    cur = db.cursor()

    user_count = cur.execute('SELECT COUNT(*) AS total FROM users').fetchone()['total']
    client_count = cur.execute('SELECT COUNT(*) AS total FROM clients').fetchone()['total']
    service_count = cur.execute('SELECT COUNT(*) AS total FROM services').fetchone()['total']
    expense_count = cur.execute('SELECT COUNT(*) AS total FROM expenses').fetchone()['total']
    company_count = cur.execute('SELECT COUNT(*) AS total FROM company_settings').fetchone()['total']

    now = datetime.now().isoformat(timespec='seconds')
    today = datetime.now().strftime('%Y-%m-%d')

    if user_count == 0:
        admin_username = (os.getenv('INFINANCE_ADMIN_USER') or 'admin').strip() or 'admin'
        admin_password = (os.getenv('INFINANCE_ADMIN_PASSWORD') or 'Admin@123').strip() or 'Admin@123'
        must_change_password = 0 if os.getenv('INFINANCE_ADMIN_PASSWORD') else 1

        cur.execute(
            '''INSERT INTO users (username, password_hash, role, must_change_password, created_at)
               VALUES (?, ?, 'admin', ?, ?)''',
            (admin_username, generate_password_hash(admin_password), must_change_password, now),
        )

    if client_count == 0:
        cur.executemany(
            'INSERT INTO clients (name, person_type, notes, created_at) VALUES (?, ?, ?, ?)',
            [
                ('Cliente Exemplo PF', 'PF', 'Cliente pessoa física para testes', now),
                ('Cliente Exemplo PJ', 'PJ', 'Cliente pessoa jurídica para testes', now),
            ],
        )

    if service_count == 0:
        cur.executemany(
            '''INSERT INTO services (name, service_type, tax_rate, cnae, cnae_description, annex, factor_r_applicable, description_template, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            [
                (
                    'Gerenciamento de site',
                    'operacional',
                    0.06,
                    '6319-4/00',
                    'Portais, provedores de conteúdo e outros serviços de informação na internet',
                    'III',
                    1,
                    'Prestação de serviços de gerenciamento, manutenção e administração operacional de website, incluindo atualização de conteúdo, monitoramento e suporte técnico.',
                    now,
                ),
                (
                    'Desenvolvimento web sob demanda',
                    'intelectual',
                    0.155,
                    '6201-5/01',
                    'Desenvolvimento de programas de computador sob encomenda',
                    'III_V',
                    1,
                    'Prestação de serviços técnicos especializados em desenvolvimento e implementação de soluções web sob demanda.',
                    now,
                ),
            ],
        )

    if expense_count == 0:
        cur.executemany(
            '''INSERT INTO expenses (description, category, amount, date_incurred, is_fixed, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            [
                ('Plano de hospedagem', 'ferramentas', 89.9, today, 1, 'Infra mensal', now),
                ('Contabilidade', 'operacional', 250.0, today, 1, 'Assessoria mensal', now),
            ],
        )

    if company_count == 0:
        cur.execute(
            '''INSERT INTO company_settings (
                   id, company_name, legal_name, tax_regime, employees_count,
                   payroll_monthly, prolabore_monthly, notes, updated_at
               ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                'Minha Empresa',
                '',
                'Simples Nacional',
                1,
                0.0,
                0.0,
                'Configure os dados da empresa para melhorar simulações e relatórios.',
                now,
            ),
        )

    db.commit()


def fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    return get_db().execute(query, params).fetchall()


def fetch_one(query: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
    return get_db().execute(query, params).fetchone()


def execute(query: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
    db = get_db()
    cursor = db.execute(query, params)
    db.commit()
    return cursor


def normalize_username(raw_value: str) -> str:
    return (raw_value or '').strip().lower()


def get_default_system_username() -> str:
    return normalize_username((os.getenv('INFINANCE_ADMIN_USER') or 'admin').strip() or 'admin')


def is_protected_system_user(user_row: sqlite3.Row | dict[str, Any] | None) -> bool:
    if user_row is None:
        return False
    try:
        user_id = int(user_row['id'])
    except (TypeError, ValueError, KeyError):
        user_id = 0
    username = normalize_username(str(user_row.get('username', '') if isinstance(user_row, dict) else user_row['username']))
    return user_id == 1 or username == get_default_system_username()


def count_users() -> int:
    row = fetch_one('SELECT COUNT(*) AS total FROM users')
    return int(row['total'] or 0) if row is not None else 0


def get_user_by_id(user_id: int) -> sqlite3.Row | None:
    return fetch_one('SELECT * FROM users WHERE id = ?', (user_id,))


def get_user_by_username(username: str) -> sqlite3.Row | None:
    return fetch_one('SELECT * FROM users WHERE username = ?', (normalize_username(username),))


def get_current_user() -> dict[str, Any] | None:
    cached = g.get('current_user_cache')
    if cached is not None:
        return cached

    user_id = session.get('user_id')
    if not user_id:
        g.current_user_cache = None
        return None

    row = get_user_by_id(int(user_id))
    if row is None:
        session.clear()
        g.current_user_cache = None
        return None

    g.current_user_cache = {
        'id': row['id'],
        'username': row['username'],
        'role': row['role'],
        'must_change_password': bool(row['must_change_password']),
    }
    return g.current_user_cache


def queue_post_login_endpoint(endpoint: str | None) -> None:
    if endpoint in POST_LOGIN_ENDPOINTS:
        session[POST_LOGIN_SESSION_KEY] = endpoint
        return
    session.pop(POST_LOGIN_SESSION_KEY, None)


def consume_post_login_target() -> str:
    endpoint = session.pop(POST_LOGIN_SESSION_KEY, None)
    if endpoint in POST_LOGIN_ENDPOINTS:
        return url_for(endpoint)
    return url_for('dashboard')


def static_file_version(filename: str) -> str:
    normalized = (filename or '').replace('\\', '/').lstrip('/')
    if not normalized:
        return '0'

    static_root = (BASE_DIR / 'static').resolve()
    candidate = (static_root / normalized).resolve()
    if static_root != candidate and static_root not in candidate.parents:
        return '0'

    try:
        return str(int(candidate.stat().st_mtime))
    except OSError:
        return '0'


def asset_url(filename: str) -> str:
    return url_for('static', filename=filename, v=static_file_version(filename))


def sign_in_user(user_row: sqlite3.Row) -> None:
    session['user_id'] = int(user_row['id'])
    session['username'] = user_row['username']
    session['role'] = user_row['role']
    execute(
        'UPDATE users SET last_login_at = ? WHERE id = ?',
        (datetime.now().isoformat(timespec='seconds'), int(user_row['id'])),
    )


def sign_out_user() -> None:
    for key in ('user_id', 'username', 'role'):
        session.pop(key, None)


def is_admin_user() -> bool:
    user = get_current_user()
    return has_permission(user['role'], 'admin') if user else False


def can_write_data() -> bool:
    user = get_current_user()
    return has_permission(user['role'], 'write') if user else False


def admin_required(view_function):
    @wraps(view_function)
    def wrapper(*args, **kwargs):
        if not is_admin_user():
            flash('Acesso restrito a administradores.', 'error')
            return redirect(url_for('dashboard'))
        return view_function(*args, **kwargs)

    return wrapper

def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_percent_input(raw_value: str) -> float:
    normalized = str(raw_value or '').replace(',', '.').strip()
    parsed = safe_float(normalized, 0.0)
    if parsed is None:
        return 0.0
    if parsed < 0:
        return 0.0
    # O campo recebe percentual em escala humana: 6 => 6%.
    return parsed / 100


def parse_date_or_default(raw_value: str, default: str | None = None) -> str:
    value = (raw_value or '').strip()
    if not value:
        return default or datetime.now().strftime('%Y-%m-%d')
    try:
        datetime.strptime(value, '%Y-%m-%d')
        return value
    except ValueError:
        return default or datetime.now().strftime('%Y-%m-%d')


def parse_month_or_default(raw_month: str) -> str:
    month = (raw_month or '').strip()
    try:
        datetime.strptime(month, '%Y-%m')
        return month
    except ValueError:
        return datetime.now().strftime('%Y-%m')


def parse_month_or_none(raw_month: str) -> str | None:
    month = (raw_month or '').strip()
    if not month:
        return None
    try:
        datetime.strptime(month, '%Y-%m')
        return month
    except ValueError:
        return None


def parse_page_or_default(raw_page: str, default: int = 1) -> int:
    try:
        page = int((raw_page or '').strip())
        return page if page > 0 else default
    except (TypeError, ValueError, AttributeError):
        return default


def parse_search_term(raw_value: str, max_length: int = 80) -> str:
    return (raw_value or '').strip()[:max_length]


def build_pagination(total_items: int, requested_page: int, per_page: int) -> dict[str, int | bool]:
    safe_total = max(int(total_items or 0), 0)
    safe_per_page = max(int(per_page or 1), 1)
    total_pages = max((safe_total + safe_per_page - 1) // safe_per_page, 1)
    current_page = min(max(int(requested_page or 1), 1), total_pages)
    offset = (current_page - 1) * safe_per_page
    start_page = max(1, current_page - 2)
    end_page = min(total_pages, current_page + 2)
    return {
        'total_items': safe_total,
        'per_page': safe_per_page,
        'total_pages': total_pages,
        'current_page': current_page,
        'offset': offset,
        'pages': list(range(start_page, end_page + 1)),
        'has_prev': current_page > 1,
        'has_next': current_page < total_pages,
        'prev_page': current_page - 1,
        'next_page': current_page + 1,
    }


def month_to_date_range(month: str) -> tuple[str, str] | None:
    parsed_month = parse_month_or_none(month)
    if parsed_month is None:
        return None
    month_start = datetime.strptime(parsed_month, '%Y-%m').replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    return month_start.strftime('%Y-%m-%d'), next_month.strftime('%Y-%m-%d')


def parse_annex(raw_annex: str, default: str = 'III') -> str:
    annex = (raw_annex or '').strip().upper()
    if annex in ANNEX_OPTIONS:
        return annex
    return default


def to_bool(raw_value: Any) -> bool:
    return str(raw_value).strip().lower() in {'1', 'true', 'on', 'yes', 'sim'}


def format_brl_plain(value: float) -> str:
    formatted = f'{float(value):,.2f}'
    return 'R$ ' + formatted.replace(',', 'X').replace('.', ',').replace('X', '.')


def get_company_settings() -> sqlite3.Row:
    row = fetch_one('SELECT * FROM company_settings WHERE id = 1')
    if row is not None:
        return row

    now = datetime.now().isoformat(timespec='seconds')
    execute(
        '''INSERT INTO company_settings (
               id, company_name, legal_name, tax_regime, employees_count,
               payroll_monthly, prolabore_monthly, notes, updated_at
           ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)''',
        ('Minha Empresa', '', 'Simples Nacional', 1, 0.0, 0.0, '', now),
    )
    return fetch_one('SELECT * FROM company_settings WHERE id = 1')


def calculate_transaction(amount: float, channel: str, invoice_issued: bool, service_tax_rate: float, expected_pf_tax: float) -> dict[str, float]:
    gross = round(max(amount, 0.0), 2)
    invoice_tax = 0.0
    pf_tax = 0.0

    if channel == 'PJ' and invoice_issued:
        invoice_tax = round(gross * max(service_tax_rate, 0.0), 2)
    elif channel == 'PF':
        pf_tax = round(max(expected_pf_tax, 0.0), 2)

    total_tax = round(invoice_tax + pf_tax, 2)
    net = round(gross - total_tax, 2)
    effective_rate = round((total_tax / gross) * 100, 2) if gross > 0 else 0.0

    return {
        'gross': gross,
        'invoice_tax': invoice_tax,
        'pf_tax': pf_tax,
        'total_tax': total_tax,
        'net': net,
        'effective_rate': effective_rate,
    }


def calculate_das_advanced(
    monthly_revenue: float,
    rbt12: float,
    payroll_12m: float,
    annex_mode: str = 'III_V',
    forced_annex: str | None = None,
) -> dict[str, Any]:
    monthly_revenue = max(monthly_revenue, 0.0)
    rbt12 = max(rbt12, 0.0)
    payroll_12m = max(payroll_12m, 0.0)

    if rbt12 <= 0:
        return {
            'error': 'Informe uma receita bruta acumulada dos últimos 12 meses (RBT12) maior que zero.',
        }

    if rbt12 > 4_800_000:
        return {
            'error': 'RBT12 acima de R$ 4.800.000,00. O cálculo simplificado aqui não cobre esse regime.',
        }

    if forced_annex is not None and forced_annex not in DAS_BRACKETS:
        return {
            'error': 'Anexo forçado inválido. Use I, II, III, IV ou V.',
        }

    factor_r = payroll_12m / rbt12
    annex_mode = parse_annex(annex_mode, 'III_V')

    if forced_annex in DAS_BRACKETS:
        annex = forced_annex
        uses_factor_r = forced_annex in {'III', 'V'} and annex_mode == 'III_V'
    elif annex_mode == 'III_V':
        annex = 'III' if factor_r >= 0.28 else 'V'
        uses_factor_r = True
    else:
        annex = annex_mode if annex_mode in DAS_BRACKETS else 'III'
        uses_factor_r = False

    bracket = DAS_BRACKETS[annex][-1]
    for item in DAS_BRACKETS[annex]:
        if rbt12 <= item['limit']:
            bracket = item
            break

    effective_rate = ((rbt12 * bracket['nominal']) - bracket['deduction']) / rbt12
    effective_rate = max(effective_rate, 0.0)
    estimated_das = monthly_revenue * effective_rate

    return {
        'error': None,
        'annex': annex,
        'monthly_revenue': monthly_revenue,
        'rbt12': rbt12,
        'payroll_12m': payroll_12m,
        'factor_r': factor_r,
        'factor_r_percent': factor_r * 100,
        'annex_mode': annex_mode,
        'uses_factor_r': uses_factor_r,
        'nominal_rate': bracket['nominal'],
        'effective_rate': effective_rate,
        'deduction': bracket['deduction'],
        'estimated_das': estimated_das,
        'target_rate_28_gap': max((0.28 * rbt12) - payroll_12m, 0.0) if uses_factor_r else 0.0,
        'bracket_limit': bracket['limit'],
    }


def get_transactions_filtered(
    month: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    search: str | None = None,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where_clauses: list[str] = []

    if month:
        month_range = month_to_date_range(month)
        if month_range is not None:
            month_start, next_month_start = month_range
            where_clauses.append('t.date_received >= ? AND t.date_received < ?')
            params.extend((month_start, next_month_start))

    if search:
        like_term = f'%{search.lower()}%'
        where_clauses.append(
            '('
            "LOWER(c.name) LIKE ? OR "
            "LOWER(s.name) LIKE ? OR "
            "LOWER(COALESCE(t.invoice_number, '')) LIKE ? OR "
            "LOWER(COALESCE(t.notes, '')) LIKE ?"
            ')'
        )
        params.extend((like_term, like_term, like_term, like_term))

    query = '''
        SELECT t.*, c.name AS client_name, c.person_type AS client_person_type,
               s.name AS service_name, s.tax_rate, s.service_type, s.cnae,
               s.cnae_description, s.annex AS service_annex, s.factor_r_applicable
        FROM transactions t
        JOIN clients c ON c.id = t.client_id
        JOIN services s ON s.id = t.service_id
    '''
    if where_clauses:
        query += ' WHERE ' + ' AND '.join(where_clauses)
    query += ' ORDER BY date(t.date_received) DESC, t.id DESC'

    if limit is not None and limit > 0:
        query += ' LIMIT ? OFFSET ?'
        params.extend((int(limit), max(int(offset), 0)))

    rows = fetch_all(query, tuple(params))

    rendered: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item['calc'] = calculate_transaction(
            amount=row['amount'],
            channel=row['channel'],
            invoice_issued=bool(row['invoice_issued']),
            service_tax_rate=row['tax_rate'],
            expected_pf_tax=row['expected_pf_tax'],
        )
        rendered.append(item)

    return rendered


def count_transactions_filtered(month: str | None = None, search: str | None = None) -> int:
    params: list[Any] = []
    where_clauses: list[str] = []

    if month:
        month_range = month_to_date_range(month)
        if month_range is not None:
            month_start, next_month_start = month_range
            where_clauses.append('t.date_received >= ? AND t.date_received < ?')
            params.extend((month_start, next_month_start))

    if search:
        like_term = f'%{search.lower()}%'
        where_clauses.append(
            '('
            "LOWER(c.name) LIKE ? OR "
            "LOWER(s.name) LIKE ? OR "
            "LOWER(COALESCE(t.invoice_number, '')) LIKE ? OR "
            "LOWER(COALESCE(t.notes, '')) LIKE ?"
            ')'
        )
        params.extend((like_term, like_term, like_term, like_term))

    query = '''
        SELECT COUNT(*) AS total
        FROM transactions t
        JOIN clients c ON c.id = t.client_id
        JOIN services s ON s.id = t.service_id
    '''
    if where_clauses:
        query += ' WHERE ' + ' AND '.join(where_clauses)

    row = fetch_one(query, tuple(params))
    return int(row['total'] or 0) if row is not None else 0


def summarize_transactions_sql(month: str | None = None) -> dict[str, float | int]:
    params: list[Any] = []
    where_clauses: list[str] = []

    if month:
        month_range = month_to_date_range(month)
        if month_range is not None:
            month_start, next_month_start = month_range
            where_clauses.append('t.date_received >= ? AND t.date_received < ?')
            params.extend((month_start, next_month_start))

    query = '''
        SELECT
            COALESCE(SUM(t.amount), 0) AS gross_total,
            COALESCE(SUM(CASE WHEN t.channel = 'PJ' AND t.invoice_issued = 1 THEN t.amount * s.tax_rate ELSE 0 END), 0) AS invoice_tax_total,
            COALESCE(SUM(CASE WHEN t.channel = 'PF' THEN t.expected_pf_tax ELSE 0 END), 0) AS pf_tax_total,
            COALESCE(SUM(CASE WHEN t.channel = 'PJ' THEN t.amount ELSE 0 END), 0) AS pj_total,
            COALESCE(SUM(CASE WHEN t.channel = 'PF' THEN t.amount ELSE 0 END), 0) AS pf_total,
            COALESCE(SUM(CASE WHEN t.invoice_issued = 1 THEN 1 ELSE 0 END), 0) AS invoice_count
        FROM transactions t
        JOIN services s ON s.id = t.service_id
    '''
    if where_clauses:
        query += ' WHERE ' + ' AND '.join(where_clauses)

    row = fetch_one(query, tuple(params))
    if row is None:
        return {
            'gross_total': 0.0,
            'net_total': 0.0,
            'invoice_tax_total': 0.0,
            'pf_tax_total': 0.0,
            'total_tax_total': 0.0,
            'pj_total': 0.0,
            'pf_total': 0.0,
            'invoice_count': 0,
        }

    gross_total = float(row['gross_total'] or 0.0)
    invoice_tax_total = float(row['invoice_tax_total'] or 0.0)
    pf_tax_total = float(row['pf_tax_total'] or 0.0)
    total_tax_total = invoice_tax_total + pf_tax_total
    net_total = gross_total - total_tax_total
    return {
        'gross_total': gross_total,
        'net_total': net_total,
        'invoice_tax_total': invoice_tax_total,
        'pf_tax_total': pf_tax_total,
        'total_tax_total': total_tax_total,
        'pj_total': float(row['pj_total'] or 0.0),
        'pf_total': float(row['pf_total'] or 0.0),
        'invoice_count': int(row['invoice_count'] or 0),
    }


def get_expenses_filtered(
    month: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    search: str | None = None,
) -> list[sqlite3.Row]:
    query = 'SELECT * FROM expenses'
    params: list[Any] = []
    where_clauses: list[str] = []

    if month:
        month_range = month_to_date_range(month)
        if month_range is not None:
            month_start, next_month_start = month_range
            where_clauses.append('date_incurred >= ? AND date_incurred < ?')
            params.extend((month_start, next_month_start))

    if search:
        like_term = f'%{search.lower()}%'
        where_clauses.append(
            '('
            "LOWER(description) LIKE ? OR "
            "LOWER(COALESCE(notes, '')) LIKE ? OR "
            "LOWER(category) LIKE ?"
            ')'
        )
        params.extend((like_term, like_term, like_term))

    if where_clauses:
        query += ' WHERE ' + ' AND '.join(where_clauses)

    query += ' ORDER BY date(date_incurred) DESC, id DESC'
    if limit is not None and limit > 0:
        query += ' LIMIT ? OFFSET ?'
        params.extend((int(limit), max(int(offset), 0)))

    return fetch_all(query, tuple(params))


def count_expenses_filtered(month: str | None = None, search: str | None = None) -> int:
    query = 'SELECT COUNT(*) AS total FROM expenses'
    params: list[Any] = []
    where_clauses: list[str] = []

    if month:
        month_range = month_to_date_range(month)
        if month_range is not None:
            month_start, next_month_start = month_range
            where_clauses.append('date_incurred >= ? AND date_incurred < ?')
            params.extend((month_start, next_month_start))

    if search:
        like_term = f'%{search.lower()}%'
        where_clauses.append(
            '('
            "LOWER(description) LIKE ? OR "
            "LOWER(COALESCE(notes, '')) LIKE ? OR "
            "LOWER(category) LIKE ?"
            ')'
        )
        params.extend((like_term, like_term, like_term))

    if where_clauses:
        query += ' WHERE ' + ' AND '.join(where_clauses)

    row = fetch_one(query, tuple(params))
    return int(row['total'] or 0) if row is not None else 0


def summarize_expenses_total(month: str | None = None, search: str | None = None) -> float:
    query = 'SELECT COALESCE(SUM(amount), 0) AS total FROM expenses'
    params: list[Any] = []
    where_clauses: list[str] = []

    if month:
        month_range = month_to_date_range(month)
        if month_range is not None:
            month_start, next_month_start = month_range
            where_clauses.append('date_incurred >= ? AND date_incurred < ?')
            params.extend((month_start, next_month_start))

    if search:
        like_term = f'%{search.lower()}%'
        where_clauses.append(
            '('
            "LOWER(description) LIKE ? OR "
            "LOWER(COALESCE(notes, '')) LIKE ? OR "
            "LOWER(category) LIKE ?"
            ')'
        )
        params.extend((like_term, like_term, like_term))

    if where_clauses:
        query += ' WHERE ' + ' AND '.join(where_clauses)

    row = fetch_one(query, tuple(params))
    return float(row['total'] or 0.0) if row is not None else 0.0


def build_monthly_report_data(month: str) -> dict[str, Any]:
    transactions = get_transactions_filtered(month)
    expenses = get_expenses_filtered(month)

    income_totals = summarize_transactions_sql(month)
    expense_total = sum(float(row['amount']) for row in expenses)
    profit_after_expenses = float(income_totals['net_total']) - expense_total

    by_category: dict[str, float] = {}
    for expense in expenses:
        key = expense['category']
        by_category[key] = by_category.get(key, 0.0) + float(expense['amount'])

    report_data = {
        'month': month,
        'transactions': transactions,
        'expenses': expenses,
        'income_totals': income_totals,
        'expense_total': expense_total,
        'profit_after_expenses': profit_after_expenses,
        'expense_by_category': by_category,
    }
    report_data['insights'] = build_monthly_insights(report_data)
    return report_data


def build_monthly_insights(report_data: dict[str, Any]) -> list[str]:
    insights: list[str] = []
    gross = float(report_data['income_totals']['gross_total'])
    net = float(report_data['income_totals']['net_total'])
    expense_total = float(report_data['expense_total'])
    result = float(report_data['profit_after_expenses'])

    if gross > 0:
        margin = (result / gross) * 100
        insights.append(f'Margem operacional estimada: {margin:.2f}% sobre a receita bruta do período.')
    else:
        insights.append('Sem receita no período para cálculo de margem operacional.')

    if expense_total > 0:
        top_category = max(report_data['expense_by_category'].items(), key=lambda item: item[1])
        insights.append(
            f'Maior categoria de despesas: {EXPENSE_CATEGORIES.get(top_category[0], top_category[0])} em {format_brl_plain(top_category[1])}.'
        )
    else:
        insights.append('Não há despesas registradas no período selecionado.')

    tax_total = float(report_data['income_totals']['total_tax_total'])
    if net > 0:
        tax_rate = (tax_total / gross) * 100 if gross > 0 else 0.0
        insights.append(f'Pressão tributária estimada: {tax_rate:.2f}% da receita bruta.')

    return insights


def csv_response(filename: str, rows: list[list[Any]]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerows(rows)
    # BOM UTF-8 garante abertura correta no Excel (Windows) com acentuação.
    data = '\ufeff' + buffer.getvalue()
    response = Response(data, mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def xlsx_response(filename: str, sheets: list[tuple[str, list[list[Any]]]]):
    if Workbook is None:
        flash('Exportação XLSX indisponível: pacote openpyxl não instalado.', 'error')
        return None

    workbook = Workbook()
    first_sheet = True
    for sheet_name, rows in sheets:
        if first_sheet:
            ws = workbook.active
            ws.title = sheet_name
            first_sheet = False
        else:
            ws = workbook.create_sheet(sheet_name)

        for row in rows:
            ws.append(row)

    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


def txt_response(filename: str, lines: list[str]) -> Response:
    content = '\n'.join(lines) + '\n'
    response = Response(content, mimetype='text/plain; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def resolve_pdf_font() -> str:
    if pdfmetrics is None or TTFont is None:
        return 'Helvetica'
    if PDF_FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return PDF_FONT_NAME

    font_candidates: Iterable[Path] = (
        BASE_DIR / 'static' / 'fonts' / 'DejaVuSans.ttf',
        Path(r'C:\Windows\Fonts\arial.ttf'),
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        Path('/Library/Fonts/Arial Unicode.ttf'),
    )
    for candidate in font_candidates:
        if not candidate.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont(PDF_FONT_NAME, str(candidate)))
            return PDF_FONT_NAME
        except (OSError, ValueError, RuntimeError):
            continue
    return 'Helvetica'


def pdf_response(filename: str, lines: list[str]):
    if canvas is None or A4 is None:
        flash('Exportação PDF indisponível: pacote reportlab não instalado.', 'error')
        return None

    width, height = A4
    output = io.BytesIO()
    doc = canvas.Canvas(output, pagesize=A4)
    doc.setFont(resolve_pdf_font(), 10)
    y = height - 40

    for raw_line in lines:
        line = raw_line if raw_line else ' '
        if y < 50:
            doc.showPage()
            doc.setFont(resolve_pdf_font(), 10)
            y = height - 40
        doc.drawString(40, y, line[:150])
        y -= 16

    doc.save()
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=filename, mimetype='application/pdf')


def get_or_create_csrf_token() -> str:
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token


@app.before_request
def verify_csrf() -> Response | None:
    if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        return None
    if request.endpoint == 'static':
        return None

    expected = session.get('_csrf_token')
    provided = request.form.get('_csrf_token') or request.headers.get('X-CSRF-Token')
    if not expected or not provided or not secrets.compare_digest(expected, provided):
        flash(CSRF_EXPIRED_MESSAGE, 'error')
        if request.endpoint == 'login':
            return redirect(url_for('login'))
        return redirect(url_for('dashboard'))

    return None


@app.before_request
def enforce_auth_and_permissions() -> Response | None:
    endpoint = request.endpoint or ''
    if not endpoint or endpoint in PUBLIC_ENDPOINTS:
        return None

    user = get_current_user()
    if user is None:
        if request.method == 'GET':
            queue_post_login_endpoint(endpoint)
        else:
            session.pop(POST_LOGIN_SESSION_KEY, None)
        return redirect(url_for('login'))

    if endpoint in ADMIN_ENDPOINTS and not has_permission(user['role'], 'admin'):
        flash('Acesso restrito a administradores.', 'error')
        return redirect(url_for('dashboard'))

    if request.method in WRITE_METHODS and endpoint not in WRITE_EXEMPT_ENDPOINTS and not has_permission(user['role'], 'write'):
        flash('Seu perfil possui permissão apenas de leitura.', 'error')
        return redirect(url_for('dashboard'))

    return None


@app.after_request
def set_security_headers(response: Response) -> Response:
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Permitted-Cross-Domain-Policies'] = 'none'
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
    response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data: blob:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'"
    )
    if request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response


@app.context_processor
def inject_globals() -> dict[str, Any]:
    user = get_current_user()
    return {
        'SERVICE_TYPES': SERVICE_TYPES,
        'CHANNELS': CHANNELS,
        'TRANSACTION_STATUS': TRANSACTION_STATUS,
        'EXPENSE_CATEGORIES': EXPENSE_CATEGORIES,
        'ANNEX_OPTIONS': ANNEX_OPTIONS,
        'VALID_ROLES': VALID_ROLES,
        'now_year': datetime.now().year,
        'csrf_token': get_or_create_csrf_token,
        'current_endpoint': request.endpoint or '',
        'current_user': user,
        'can_write': can_write_data(),
        'is_admin': has_permission(user['role'], 'admin') if user else False,
        'asset_url': asset_url,
    }


@app.route('/login', methods=['GET', 'POST'])
def login() -> str:
    if get_current_user() is not None:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = normalize_username(request.form.get('username', ''))
        password = request.form.get('password', '')
        user = get_user_by_username(username)

        if user is None or not check_password_hash(user['password_hash'], password):
            flash('Credenciais inválidas.', 'error')
            return redirect(url_for('login'))

        sign_in_user(user)
        flash('Sessão iniciada com sucesso.', 'success')
        if user['must_change_password']:
            flash('Seu usuário utiliza senha provisória. Altere-a na área de usuários.', 'error')
        return redirect(consume_post_login_target())

    return render_template('login.html')


@app.route('/logout', methods=['POST'])
def logout() -> Response:
    sign_out_user()
    flash('Sessão encerrada.', 'success')
    return redirect(url_for('login'))


@app.route('/users', methods=['GET', 'POST'])
@admin_required
def users() -> str:
    if request.method == 'POST':
        username = normalize_username(request.form.get('username', ''))
        role = (request.form.get('role', 'viewer') or 'viewer').strip().lower()
        password = request.form.get('password', '')

        if not username or len(username) < 3:
            flash('Informe um usuário com ao menos 3 caracteres.', 'error')
            return redirect(url_for('users'))
        if role not in VALID_ROLES:
            flash('Perfil inválido.', 'error')
            return redirect(url_for('users'))
        if len(password) < 8:
            flash('Senha deve ter no mínimo 8 caracteres.', 'error')
            return redirect(url_for('users'))
        if get_user_by_username(username) is not None:
            flash('Usuário já existe.', 'error')
            return redirect(url_for('users'))

        execute(
            '''INSERT INTO users (username, password_hash, role, must_change_password, created_at)
               VALUES (?, ?, ?, 1, ?)''',
            (username, generate_password_hash(password), role, datetime.now().isoformat(timespec='seconds')),
        )
        flash('Usuário criado com sucesso.', 'success')
        return redirect(url_for('users'))

    all_users = fetch_all('SELECT id, username, role, must_change_password, created_at, last_login_at FROM users ORDER BY id ASC')
    total_users = len(all_users)
    users_view: list[dict[str, Any]] = []
    for row in all_users:
        row_data = dict(row)
        row_data['is_protected'] = is_protected_system_user(row)
        row_data['can_delete'] = (not row_data['is_protected']) and total_users > 1
        users_view.append(row_data)
    return render_template('users.html', users=users_view, total_users=total_users)


@app.route('/users/<int:user_id>/username', methods=['POST'])
@admin_required
def update_user_username(user_id: int) -> Response:
    user = get_user_by_id(user_id)
    if user is None:
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('users'))

    username = normalize_username(request.form.get('username', ''))
    if not username or len(username) < 3:
        flash('Informe um usuário com ao menos 3 caracteres.', 'error')
        return redirect(url_for('users'))

    existing = get_user_by_username(username)
    if existing is not None and int(existing['id']) != int(user_id):
        flash('Usuário já existe.', 'error')
        return redirect(url_for('users'))

    execute('UPDATE users SET username = ? WHERE id = ?', (username, user_id))
    flash('Usuário atualizado com sucesso.', 'success')
    return redirect(url_for('users'))


@app.route('/users/<int:user_id>/role', methods=['POST'])
@admin_required
def update_user_role(user_id: int) -> Response:
    user = get_user_by_id(user_id)
    if user is None:
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('users'))

    role = (request.form.get('role', user['role']) or user['role']).strip().lower()
    if role not in VALID_ROLES:
        flash('Perfil inválido.', 'error')
        return redirect(url_for('users'))

    current = get_current_user()
    if current and int(current['id']) == int(user_id) and role != 'admin':
        flash('Você não pode remover seu próprio perfil administrador.', 'error')
        return redirect(url_for('users'))

    execute('UPDATE users SET role = ? WHERE id = ?', (role, user_id))
    flash('Perfil atualizado com sucesso.', 'success')
    return redirect(url_for('users'))


@app.route('/users/<int:user_id>/password', methods=['POST'])
@admin_required
def reset_user_password(user_id: int) -> Response:
    user = get_user_by_id(user_id)
    if user is None:
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('users'))

    password = request.form.get('password', '')
    if len(password) < 8:
        flash('Senha deve ter no mínimo 8 caracteres.', 'error')
        return redirect(url_for('users'))

    execute(
        'UPDATE users SET password_hash = ?, must_change_password = 1 WHERE id = ?',
        (generate_password_hash(password), user_id),
    )
    flash('Senha redefinida com sucesso.', 'success')
    return redirect(url_for('users'))


@app.route('/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id: int) -> Response:
    user = get_user_by_id(user_id)
    if user is None:
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('users'))

    if is_protected_system_user(user):
        flash('O usuário padrão do sistema é protegido e não pode ser excluído.', 'error')
        return redirect(url_for('users'))

    if count_users() <= 1:
        flash('Não é permitido excluir o último usuário do sistema.', 'error')
        return redirect(url_for('users'))

    execute('DELETE FROM users WHERE id = ?', (user_id,))
    flash('Usuário excluído com sucesso.', 'success')
    return redirect(url_for('users'))


@app.route('/')
def dashboard() -> str:
    transactions = get_transactions_filtered(limit=12)
    totals = summarize_transactions_sql()
    company = get_company_settings()

    current_month = datetime.now().strftime('%Y-%m')
    month_data = build_monthly_report_data(current_month)

    client_total = fetch_one('SELECT COUNT(*) AS total FROM clients')['total']
    service_total = fetch_one('SELECT COUNT(*) AS total FROM services')['total']
    expense_total_count = fetch_one('SELECT COUNT(*) AS total FROM expenses')['total']

    return render_template(
        'dashboard.html',
        transactions=transactions,
        totals=totals,
        month_data=month_data,
        company=company,
        client_total=client_total,
        service_total=service_total,
        expense_total_count=expense_total_count,
    )


@app.route('/about')
def about() -> str:
    authors = [
        {
            **author,
            'initials': ''.join(part[0] for part in author['name'].split()[:2]).upper() or 'IF',
        }
        for author in AUTHORS
    ]
    return render_template('about.html', authors=authors)


@app.route('/company', methods=['GET', 'POST'])
def company_settings() -> str:
    settings = get_company_settings()

    if request.method == 'POST':
        company_name = request.form.get('company_name', '').strip() or settings['company_name']
        legal_name = request.form.get('legal_name', '').strip()
        tax_regime = request.form.get('tax_regime', 'Simples Nacional').strip() or 'Simples Nacional'
        employees_count = request.form.get('employees_count', type=int)
        payroll_monthly = request.form.get('payroll_monthly', type=float)
        prolabore_monthly = request.form.get('prolabore_monthly', type=float)
        notes = request.form.get('notes', '').strip()

        employees_count = max(employees_count or 0, 0)
        payroll_monthly = max(payroll_monthly or 0.0, 0.0)
        prolabore_monthly = max(prolabore_monthly or 0.0, 0.0)

        execute(
            '''UPDATE company_settings
               SET company_name = ?, legal_name = ?, tax_regime = ?, employees_count = ?,
                   payroll_monthly = ?, prolabore_monthly = ?, notes = ?, updated_at = ?
               WHERE id = 1''',
            (
                company_name,
                legal_name,
                tax_regime,
                employees_count,
                payroll_monthly,
                prolabore_monthly,
                notes,
                datetime.now().isoformat(timespec='seconds'),
            ),
        )
        flash('Configurações da empresa atualizadas com sucesso.', 'success')
        return redirect(url_for('company_settings'))

    return render_template('company.html', company=settings)


@app.route('/clients', methods=['GET', 'POST'])
def clients() -> str:
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        person_type = request.form.get('person_type', 'PF').strip().upper()
        notes = request.form.get('notes', '').strip()

        if not name:
            flash('Informe o nome do cliente.', 'error')
            return redirect(url_for('clients'))

        if person_type not in {'PF', 'PJ'}:
            person_type = 'PF'

        execute(
            'INSERT INTO clients (name, person_type, notes, created_at) VALUES (?, ?, ?, ?)',
            (name, person_type, notes, datetime.now().isoformat(timespec='seconds')),
        )
        flash('Cliente cadastrado com sucesso.', 'success')
        return redirect(url_for('clients'))

    search_query = parse_search_term(request.args.get('q', ''))
    page = parse_page_or_default(request.args.get('page', '1'))
    where_clauses: list[str] = []
    params: list[Any] = []

    if search_query:
        like_term = f'%{search_query.lower()}%'
        where_clauses.append("(LOWER(name) LIKE ? OR LOWER(COALESCE(notes, '')) LIKE ?)")
        params.extend((like_term, like_term))

    where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ''
    total_row = fetch_one(f'SELECT COUNT(*) AS total FROM clients{where_sql}', tuple(params))
    total_items = int(total_row['total'] or 0) if total_row is not None else 0
    pagination = build_pagination(total_items, page, CLIENTS_PER_PAGE)

    page_params = [*params, int(pagination['per_page']), int(pagination['offset'])]
    rows = fetch_all(
        f'SELECT * FROM clients{where_sql} ORDER BY id DESC LIMIT ? OFFSET ?',
        tuple(page_params),
    )
    return render_template('clients.html', clients=rows, search_query=search_query, pagination=pagination)


@app.route('/clients/<int:client_id>/edit', methods=['GET', 'POST'])
def edit_client(client_id: int) -> str:
    row = fetch_one('SELECT * FROM clients WHERE id = ?', (client_id,))
    if row is None:
        flash('Cliente não encontrado.', 'error')
        return redirect(url_for('clients'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        person_type = request.form.get('person_type', 'PF').strip().upper()
        notes = request.form.get('notes', '').strip()

        if not name:
            flash('Informe o nome do cliente.', 'error')
            return redirect(url_for('edit_client', client_id=client_id))

        if person_type not in {'PF', 'PJ'}:
            person_type = row['person_type']

        execute(
            'UPDATE clients SET name = ?, person_type = ?, notes = ? WHERE id = ?',
            (name, person_type, notes, client_id),
        )
        flash('Cliente atualizado com sucesso.', 'success')
        return redirect(url_for('clients'))

    return render_template('client_edit.html', client=row)


@app.route('/clients/<int:client_id>/delete', methods=['POST'])
def delete_client(client_id: int):
    linked = fetch_one('SELECT COUNT(*) AS total FROM transactions WHERE client_id = ?', (client_id,))
    if linked and linked['total'] > 0:
        flash('Não foi possível excluir: existem entradas vinculadas a este cliente.', 'error')
        return redirect(url_for('clients'))

    execute('DELETE FROM clients WHERE id = ?', (client_id,))
    flash('Cliente excluído com sucesso.', 'success')
    return redirect(url_for('clients'))


@app.route('/services', methods=['GET', 'POST'])
def services() -> str:
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        service_type = request.form.get('service_type', 'operacional').strip()
        tax_rate = normalize_percent_input(request.form.get('tax_rate', '0'))
        cnae = request.form.get('cnae', '').strip()
        cnae_description = request.form.get('cnae_description', '').strip()
        annex = parse_annex(request.form.get('annex', 'III_V'), 'III_V')
        factor_r_applicable = 1 if to_bool(request.form.get('factor_r_applicable')) else 0
        description_template = request.form.get('description_template', '').strip()

        if not name:
            flash('Informe o nome do serviço.', 'error')
            return redirect(url_for('services'))

        if service_type not in SERVICE_TYPES:
            service_type = 'personalizado'

        execute(
            '''INSERT INTO services (
                   name, service_type, tax_rate, cnae, cnae_description, annex, factor_r_applicable,
                   description_template, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                name,
                service_type,
                tax_rate,
                cnae,
                cnae_description,
                annex,
                factor_r_applicable,
                description_template,
                datetime.now().isoformat(timespec='seconds'),
            ),
        )
        flash('Serviço cadastrado com sucesso.', 'success')
        return redirect(url_for('services'))

    search_query = parse_search_term(request.args.get('q', ''))
    page = parse_page_or_default(request.args.get('page', '1'))
    where_clauses: list[str] = []
    params: list[Any] = []

    if search_query:
        like_term = f'%{search_query.lower()}%'
        where_clauses.append(
            "("
            "LOWER(name) LIKE ? OR "
            "LOWER(COALESCE(cnae, '')) LIKE ? OR "
            "LOWER(COALESCE(cnae_description, '')) LIKE ?"
            ")"
        )
        params.extend((like_term, like_term, like_term))

    where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ''
    total_row = fetch_one(f'SELECT COUNT(*) AS total FROM services{where_sql}', tuple(params))
    total_items = int(total_row['total'] or 0) if total_row is not None else 0
    pagination = build_pagination(total_items, page, SERVICES_PER_PAGE)

    page_params = [*params, int(pagination['per_page']), int(pagination['offset'])]
    rows = fetch_all(
        f'SELECT * FROM services{where_sql} ORDER BY id DESC LIMIT ? OFFSET ?',
        tuple(page_params),
    )
    return render_template('services.html', services=rows, search_query=search_query, pagination=pagination)


@app.route('/services/<int:service_id>/edit', methods=['GET', 'POST'])
def edit_service(service_id: int) -> str:
    row = fetch_one('SELECT * FROM services WHERE id = ?', (service_id,))
    if row is None:
        flash('Serviço não encontrado.', 'error')
        return redirect(url_for('services'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        service_type = request.form.get('service_type', row['service_type']).strip()
        tax_rate = normalize_percent_input(request.form.get('tax_rate', str(row['tax_rate'])))
        cnae = request.form.get('cnae', '').strip()
        cnae_description = request.form.get('cnae_description', '').strip()
        annex = parse_annex(request.form.get('annex', row['annex'] if row['annex'] else 'III_V'), row['annex'] if row['annex'] else 'III_V')
        factor_r_applicable = 1 if to_bool(request.form.get('factor_r_applicable')) else 0
        description_template = request.form.get('description_template', '').strip()

        if not name:
            flash('Informe o nome do serviço.', 'error')
            return redirect(url_for('edit_service', service_id=service_id))

        if service_type not in SERVICE_TYPES:
            service_type = row['service_type']

        execute(
            '''UPDATE services
               SET name = ?, service_type = ?, tax_rate = ?, cnae = ?, cnae_description = ?,
                   annex = ?, factor_r_applicable = ?, description_template = ?
               WHERE id = ?''',
            (
                name,
                service_type,
                tax_rate,
                cnae,
                cnae_description,
                annex,
                factor_r_applicable,
                description_template,
                service_id,
            ),
        )
        flash('Serviço atualizado com sucesso.', 'success')
        return redirect(url_for('services'))

    return render_template('service_edit.html', service=row)


@app.route('/services/<int:service_id>/delete', methods=['POST'])
def delete_service(service_id: int):
    linked = fetch_one('SELECT COUNT(*) AS total FROM transactions WHERE service_id = ?', (service_id,))
    if linked and linked['total'] > 0:
        flash('Não foi possível excluir: existem entradas vinculadas a este serviço.', 'error')
        return redirect(url_for('services'))

    execute('DELETE FROM services WHERE id = ?', (service_id,))
    flash('Serviço excluído com sucesso.', 'success')
    return redirect(url_for('services'))

@app.route('/transactions', methods=['GET', 'POST'])
def transactions() -> str:
    if request.method == 'POST':
        client_id = request.form.get('client_id', type=int)
        service_id = request.form.get('service_id', type=int)
        amount = request.form.get('amount', type=float)
        channel = request.form.get('channel', 'PJ').strip().upper()
        invoice_issued = 1 if request.form.get('invoice_issued') == 'on' else 0
        invoice_number = request.form.get('invoice_number', '').strip()
        invoice_description = request.form.get('invoice_description', '').strip()
        expected_pf_tax = request.form.get('expected_pf_tax', type=float) or 0.0
        date_received = parse_date_or_default(request.form.get('date_received', ''))
        status = request.form.get('status', 'recebido').strip()
        notes = request.form.get('notes', '').strip()

        if not client_id or not service_id or amount is None:
            flash('Preencha cliente, serviço e valor.', 'error')
            return redirect(url_for('transactions'))

        if amount <= 0:
            flash('Informe um valor maior que zero.', 'error')
            return redirect(url_for('transactions'))

        if channel not in CHANNELS:
            channel = 'PJ'

        if status not in TRANSACTION_STATUS:
            status = 'recebido'

        expected_pf_tax = max(expected_pf_tax, 0.0)

        execute(
            '''INSERT INTO transactions (
                   client_id, service_id, amount, channel, invoice_issued, invoice_number,
                   invoice_description, expected_pf_tax, date_received, status, notes, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                client_id,
                service_id,
                amount,
                channel,
                invoice_issued,
                invoice_number,
                invoice_description,
                expected_pf_tax,
                date_received,
                status,
                notes,
                datetime.now().isoformat(timespec='seconds'),
            ),
        )
        flash('Entrada cadastrada com sucesso.', 'success')
        return redirect(url_for('transactions'))

    client_rows = fetch_all('SELECT * FROM clients ORDER BY name ASC')
    service_rows = fetch_all('SELECT * FROM services ORDER BY name ASC')
    selected_month = parse_month_or_none(request.args.get('month', ''))
    search_query = parse_search_term(request.args.get('q', ''))
    page = parse_page_or_default(request.args.get('page', '1'))
    total_items = count_transactions_filtered(selected_month, search_query or None)
    pagination = build_pagination(total_items, page, TRANSACTIONS_PER_PAGE)
    rendered = get_transactions_filtered(
        selected_month,
        limit=int(pagination['per_page']),
        offset=int(pagination['offset']),
        search=search_query or None,
    )

    return render_template(
        'transactions.html',
        clients=client_rows,
        services=service_rows,
        transactions=rendered,
        selected_month=selected_month or '',
        search_query=search_query,
        pagination=pagination,
    )


@app.route('/transactions/<int:transaction_id>/edit', methods=['GET', 'POST'])
def edit_transaction(transaction_id: int) -> str:
    row = fetch_one('SELECT * FROM transactions WHERE id = ?', (transaction_id,))
    if row is None:
        flash('Entrada não encontrada.', 'error')
        return redirect(url_for('transactions'))

    if request.method == 'POST':
        client_id = request.form.get('client_id', type=int)
        service_id = request.form.get('service_id', type=int)
        amount = request.form.get('amount', type=float)
        channel = request.form.get('channel', row['channel']).strip().upper()
        invoice_issued = 1 if request.form.get('invoice_issued') == 'on' else 0
        invoice_number = request.form.get('invoice_number', '').strip()
        invoice_description = request.form.get('invoice_description', '').strip()
        expected_pf_tax = request.form.get('expected_pf_tax', type=float) or 0.0
        date_received = parse_date_or_default(request.form.get('date_received', ''), row['date_received'])
        status = request.form.get('status', row['status']).strip()
        notes = request.form.get('notes', '').strip()

        if not client_id or not service_id or amount is None or amount <= 0:
            flash('Preencha cliente, serviço e valor válido.', 'error')
            return redirect(url_for('edit_transaction', transaction_id=transaction_id))

        if channel not in CHANNELS:
            channel = row['channel']

        if status not in TRANSACTION_STATUS:
            status = row['status']

        expected_pf_tax = max(expected_pf_tax, 0.0)

        execute(
            '''UPDATE transactions
               SET client_id = ?, service_id = ?, amount = ?, channel = ?, invoice_issued = ?,
                   invoice_number = ?, invoice_description = ?, expected_pf_tax = ?, date_received = ?,
                   status = ?, notes = ?
               WHERE id = ?''',
            (
                client_id,
                service_id,
                amount,
                channel,
                invoice_issued,
                invoice_number,
                invoice_description,
                expected_pf_tax,
                date_received,
                status,
                notes,
                transaction_id,
            ),
        )
        flash('Entrada atualizada com sucesso.', 'success')
        return redirect(url_for('transactions'))

    client_rows = fetch_all('SELECT * FROM clients ORDER BY name ASC')
    service_rows = fetch_all('SELECT * FROM services ORDER BY name ASC')
    return render_template('transaction_edit.html', transaction=row, clients=client_rows, services=service_rows)


@app.route('/transactions/<int:transaction_id>/delete', methods=['POST'])
def delete_transaction(transaction_id: int):
    execute('DELETE FROM transactions WHERE id = ?', (transaction_id,))
    flash('Entrada excluída com sucesso.', 'success')
    return redirect(url_for('transactions'))


@app.route('/expenses', methods=['GET', 'POST'])
def expenses() -> str:
    if request.method == 'POST':
        description = request.form.get('description', '').strip()
        category = request.form.get('category', 'outros').strip()
        amount = request.form.get('amount', type=float)
        date_incurred = parse_date_or_default(request.form.get('date_incurred', ''))
        is_fixed = 1 if request.form.get('is_fixed') == 'on' else 0
        notes = request.form.get('notes', '').strip()

        if not description or amount is None or amount <= 0:
            flash('Preencha descrição e valor válido para a despesa.', 'error')
            return redirect(url_for('expenses'))

        if category not in EXPENSE_CATEGORIES:
            category = 'outros'

        execute(
            '''INSERT INTO expenses (description, category, amount, date_incurred, is_fixed, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (description, category, amount, date_incurred, is_fixed, notes, datetime.now().isoformat(timespec='seconds')),
        )
        flash('Despesa cadastrada com sucesso.', 'success')
        return redirect(url_for('expenses'))

    selected_month = parse_month_or_none(request.args.get('month', ''))
    search_query = parse_search_term(request.args.get('q', ''))
    page = parse_page_or_default(request.args.get('page', '1'))
    total_items = count_expenses_filtered(selected_month, search_query or None)
    pagination = build_pagination(total_items, page, EXPENSES_PER_PAGE)
    rows = get_expenses_filtered(
        selected_month,
        limit=int(pagination['per_page']),
        offset=int(pagination['offset']),
        search=search_query or None,
    )
    total = summarize_expenses_total(selected_month, search_query or None)
    return render_template(
        'expenses.html',
        expenses=rows,
        expense_total=total,
        selected_month=selected_month or '',
        search_query=search_query,
        pagination=pagination,
    )


@app.route('/expenses/<int:expense_id>/edit', methods=['GET', 'POST'])
def edit_expense(expense_id: int) -> str:
    row = fetch_one('SELECT * FROM expenses WHERE id = ?', (expense_id,))
    if row is None:
        flash('Despesa não encontrada.', 'error')
        return redirect(url_for('expenses'))

    if request.method == 'POST':
        description = request.form.get('description', '').strip()
        category = request.form.get('category', row['category']).strip()
        amount = request.form.get('amount', type=float)
        date_incurred = parse_date_or_default(request.form.get('date_incurred', ''), row['date_incurred'])
        is_fixed = 1 if request.form.get('is_fixed') == 'on' else 0
        notes = request.form.get('notes', '').strip()

        if not description or amount is None or amount <= 0:
            flash('Preencha descrição e valor válido para a despesa.', 'error')
            return redirect(url_for('edit_expense', expense_id=expense_id))

        if category not in EXPENSE_CATEGORIES:
            category = row['category']

        execute(
            '''UPDATE expenses
               SET description = ?, category = ?, amount = ?, date_incurred = ?, is_fixed = ?, notes = ?
               WHERE id = ?''',
            (description, category, amount, date_incurred, is_fixed, notes, expense_id),
        )
        flash('Despesa atualizada com sucesso.', 'success')
        return redirect(url_for('expenses'))

    return render_template('expense_edit.html', expense=row)


@app.route('/expenses/<int:expense_id>/delete', methods=['POST'])
def delete_expense(expense_id: int):
    execute('DELETE FROM expenses WHERE id = ?', (expense_id,))
    flash('Despesa excluída com sucesso.', 'success')
    return redirect(url_for('expenses'))


@app.route('/simulator', methods=['GET', 'POST'])
def simulator() -> str:
    service_rows = fetch_all('SELECT * FROM services ORDER BY name ASC')
    result = None
    selected_service = None
    form_data = {
        'service_id': '',
        'amount': '',
        'channel': 'PJ',
        'invoice_issued': False,
        'expected_pf_tax': '0',
    }

    if request.method == 'POST':
        if not service_rows:
            flash('Cadastre ao menos um serviço antes de usar o simulador.', 'error')
            return redirect(url_for('services'))

        service_id_raw = (request.form.get('service_id') or '').strip()
        amount_raw = (request.form.get('amount') or '').strip().replace(',', '.')
        expected_pf_tax_raw = (request.form.get('expected_pf_tax') or '').strip().replace(',', '.')
        amount = safe_float(amount_raw, 0.0) or 0.0
        service_id = request.form.get('service_id', type=int)
        channel = request.form.get('channel', 'PJ').strip().upper()
        invoice_issued = request.form.get('invoice_issued') == 'on'
        expected_pf_tax = safe_float(expected_pf_tax_raw, 0.0) or 0.0

        if channel not in CHANNELS:
            channel = 'PJ'

        form_data = {
            'service_id': service_id_raw,
            'amount': amount_raw,
            'channel': channel,
            'invoice_issued': invoice_issued,
            'expected_pf_tax': expected_pf_tax_raw or '0',
        }

        selected_service = fetch_one('SELECT * FROM services WHERE id = ?', (service_id,))
        if selected_service:
            result = calculate_transaction(amount, channel, invoice_issued, selected_service['tax_rate'], expected_pf_tax)
            result['service_name'] = selected_service['name']
            result['service_rate_percent'] = round(selected_service['tax_rate'] * 100, 2)
            result['cnae'] = selected_service['cnae']
            result['annex'] = selected_service['annex'] or 'III'

    return render_template(
        'simulator.html',
        services=service_rows,
        result=result,
        selected_service=selected_service,
        form_data=form_data,
    )


@app.route('/das', methods=['GET', 'POST'])
def das_advanced() -> str:
    company = get_company_settings()
    payroll_default_12m = (float(company['payroll_monthly']) + float(company['prolabore_monthly'])) * 12
    result = None
    input_data = {
        'monthly_revenue': 0.0,
        'rbt12': 0.0,
        'payroll_12m': payroll_default_12m,
        'annex_mode': 'III_V',
        'forced_annex': '',
    }

    if request.method == 'POST':
        input_data = {
            'monthly_revenue': request.form.get('monthly_revenue', type=float) or 0.0,
            'rbt12': request.form.get('rbt12', type=float) or 0.0,
            'payroll_12m': request.form.get('payroll_12m', type=float) or payroll_default_12m,
            'annex_mode': parse_annex(request.form.get('annex_mode', 'III_V'), 'III_V'),
            'forced_annex': request.form.get('forced_annex', '').strip().upper(),
        }

        forced_annex = input_data['forced_annex'] if input_data['forced_annex'] in DAS_BRACKETS else None
        result = calculate_das_advanced(
            monthly_revenue=input_data['monthly_revenue'],
            rbt12=input_data['rbt12'],
            payroll_12m=input_data['payroll_12m'],
            annex_mode=input_data['annex_mode'],
            forced_annex=forced_annex,
        )

    return render_template('das.html', result=result, input_data=input_data, company=company)


@app.route('/reports/monthly')
def monthly_report() -> str:
    month = parse_month_or_default(request.args.get('month', ''))
    data = build_monthly_report_data(month)
    data['company'] = get_company_settings()
    return render_template('monthly_report.html', **data)


@app.route('/favicon.ico')
def favicon_legacy():
    return app.send_static_file('infinance-icon.svg')

@app.route('/export/transactions.csv')
def export_transactions_csv():
    month = parse_month_or_none(request.args.get('month', ''))
    transactions = get_transactions_filtered(month)
    rows: list[list[Any]] = [[
        'ID',
        'Data',
        'Cliente',
        'Serviço',
        'Canal',
        'Status',
        'Bruto',
        'Imposto',
        'Líquido',
        'Nota Emitida',
        'Número Nota',
    ]]
    for item in transactions:
        rows.append([
            item['id'],
            item['date_received'],
            item['client_name'],
            item['service_name'],
            item['channel'],
            item['status'],
            item['calc']['gross'],
            item['calc']['total_tax'],
            item['calc']['net'],
            'Sim' if item['invoice_issued'] else 'Não',
            item['invoice_number'] or '',
        ])

    suffix = f'-{month}' if month else ''
    return csv_response(f'infinance-entradas{suffix}.csv', rows)


@app.route('/export/transactions.xlsx')
def export_transactions_xlsx():
    month = parse_month_or_none(request.args.get('month', ''))
    transactions = get_transactions_filtered(month)
    rows: list[list[Any]] = [[
        'ID',
        'Data',
        'Cliente',
        'Serviço',
        'Canal',
        'Status',
        'Bruto',
        'Imposto',
        'Líquido',
        'Nota Emitida',
        'Número Nota',
    ]]
    for item in transactions:
        rows.append([
            item['id'],
            item['date_received'],
            item['client_name'],
            item['service_name'],
            item['channel'],
            item['status'],
            item['calc']['gross'],
            item['calc']['total_tax'],
            item['calc']['net'],
            'Sim' if item['invoice_issued'] else 'Não',
            item['invoice_number'] or '',
        ])

    suffix = f'-{month}' if month else ''
    response = xlsx_response(f'infinance-entradas{suffix}.xlsx', [('Entradas', rows)])
    return response or redirect(url_for('transactions', month=month) if month else url_for('transactions'))


@app.route('/export/expenses.csv')
def export_expenses_csv():
    month = parse_month_or_none(request.args.get('month', ''))
    expenses_rows = get_expenses_filtered(month)
    rows: list[list[Any]] = [[
        'ID',
        'Data',
        'Descrição',
        'Categoria',
        'Valor',
        'Fixa',
        'Observações',
    ]]
    for expense in expenses_rows:
        rows.append([
            expense['id'],
            expense['date_incurred'],
            expense['description'],
            EXPENSE_CATEGORIES.get(expense['category'], expense['category']),
            expense['amount'],
            'Sim' if expense['is_fixed'] else 'Não',
            expense['notes'] or '',
        ])

    suffix = f'-{month}' if month else ''
    return csv_response(f'infinance-despesas{suffix}.csv', rows)


@app.route('/export/expenses.xlsx')
def export_expenses_xlsx():
    month = parse_month_or_none(request.args.get('month', ''))
    expenses_rows = get_expenses_filtered(month)
    rows: list[list[Any]] = [[
        'ID',
        'Data',
        'Descrição',
        'Categoria',
        'Valor',
        'Fixa',
        'Observações',
    ]]
    for expense in expenses_rows:
        rows.append([
            expense['id'],
            expense['date_incurred'],
            expense['description'],
            EXPENSE_CATEGORIES.get(expense['category'], expense['category']),
            expense['amount'],
            'Sim' if expense['is_fixed'] else 'Não',
            expense['notes'] or '',
        ])

    suffix = f'-{month}' if month else ''
    response = xlsx_response(f'infinance-despesas{suffix}.xlsx', [('Despesas', rows)])
    return response or redirect(url_for('expenses', month=month) if month else url_for('expenses'))


@app.route('/export/monthly.csv')
def export_monthly_csv():
    month = parse_month_or_default(request.args.get('month', ''))
    data = build_monthly_report_data(month)

    rows: list[list[Any]] = [
        ['Resumo Mensal', month],
        ['Receita Bruta', data['income_totals']['gross_total']],
        ['Impostos Estimados', data['income_totals']['total_tax_total']],
        ['Receita Líquida', data['income_totals']['net_total']],
        ['Despesas', data['expense_total']],
        ['Resultado Operacional', data['profit_after_expenses']],
        [],
        ['Entradas'],
        ['Data', 'Cliente', 'Serviço', 'Canal', 'Bruto', 'Imposto', 'Líquido'],
    ]

    for item in data['transactions']:
        rows.append([
            item['date_received'],
            item['client_name'],
            item['service_name'],
            item['channel'],
            item['calc']['gross'],
            item['calc']['total_tax'],
            item['calc']['net'],
        ])

    rows.append([])
    rows.append(['Despesas'])
    rows.append(['Data', 'Descrição', 'Categoria', 'Valor'])

    for expense in data['expenses']:
        rows.append([
            expense['date_incurred'],
            expense['description'],
            EXPENSE_CATEGORIES.get(expense['category'], expense['category']),
            expense['amount'],
        ])

    return csv_response(f'infinance-relatorio-{month}.csv', rows)


@app.route('/export/monthly.xlsx')
def export_monthly_xlsx():
    month = parse_month_or_default(request.args.get('month', ''))
    data = build_monthly_report_data(month)

    summary_rows = [
        ['Indicador', 'Valor'],
        ['Mês', month],
        ['Receita Bruta', data['income_totals']['gross_total']],
        ['Impostos Estimados', data['income_totals']['total_tax_total']],
        ['Receita Líquida', data['income_totals']['net_total']],
        ['Despesas', data['expense_total']],
        ['Resultado Operacional', data['profit_after_expenses']],
    ]

    income_rows = [['Data', 'Cliente', 'Serviço', 'Canal', 'Bruto', 'Imposto', 'Líquido']]
    for item in data['transactions']:
        income_rows.append([
            item['date_received'],
            item['client_name'],
            item['service_name'],
            item['channel'],
            item['calc']['gross'],
            item['calc']['total_tax'],
            item['calc']['net'],
        ])

    expense_rows = [['Data', 'Descrição', 'Categoria', 'Valor']]
    for expense in data['expenses']:
        expense_rows.append([
            expense['date_incurred'],
            expense['description'],
            EXPENSE_CATEGORIES.get(expense['category'], expense['category']),
            expense['amount'],
        ])

    response = xlsx_response(
        f'infinance-relatorio-{month}.xlsx',
        [
            ('Resumo', summary_rows),
            ('Entradas', income_rows),
            ('Despesas', expense_rows),
        ],
    )
    return response or redirect(url_for('monthly_report', month=month))


def transactions_text_lines(month: str | None = None) -> list[str]:
    transactions = get_transactions_filtered(month)
    lines = [
        'INFINANCE - RELATÓRIO DE ENTRADAS',
        f'Gerado em: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        f'Período: {month if month else "Todos"}',
        f'Total de registros: {len(transactions)}',
        '',
    ]
    for item in transactions:
        lines.append(
            f'[{item["id"]}] {item["date_received"]} | {item["client_name"]} | {item["service_name"]} | '
            f'Canal: {item["channel"]} | Bruto: {format_brl_plain(item["calc"]["gross"])} | '
            f'Imposto: {format_brl_plain(item["calc"]["total_tax"])} | Líquido: {format_brl_plain(item["calc"]["net"])}'
        )
    if not transactions:
        lines.append('Sem entradas para exportar.')
    return lines


def expenses_text_lines(month: str | None = None) -> list[str]:
    expenses_rows = get_expenses_filtered(month)
    lines = [
        'INFINANCE - RELATÓRIO DE DESPESAS',
        f'Gerado em: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        f'Período: {month if month else "Todos"}',
        f'Total de registros: {len(expenses_rows)}',
        '',
    ]
    for item in expenses_rows:
        lines.append(
            f'[{item["id"]}] {item["date_incurred"]} | {item["description"]} | '
            f'Categoria: {EXPENSE_CATEGORIES.get(item["category"], item["category"])} | '
            f'Valor: {format_brl_plain(item["amount"])} | Fixa: {"Sim" if item["is_fixed"] else "Não"}'
        )
    if not expenses_rows:
        lines.append('Sem despesas para exportar.')
    return lines


def monthly_text_lines(month: str, report_data: dict[str, Any], company: sqlite3.Row) -> list[str]:
    lines = [
        'INFINANCE - RELATÓRIO MENSAL INTELIGENTE',
        f'Mês de referência: {month}',
        f'Empresa: {company["company_name"]}',
        f'Funcionários: {company["employees_count"]}',
        '',
        f'Receita bruta: {format_brl_plain(report_data["income_totals"]["gross_total"])}',
        f'Impostos estimados: {format_brl_plain(report_data["income_totals"]["total_tax_total"])}',
        f'Receita líquida: {format_brl_plain(report_data["income_totals"]["net_total"])}',
        f'Despesas: {format_brl_plain(report_data["expense_total"])}',
        f'Resultado operacional: {format_brl_plain(report_data["profit_after_expenses"])}',
        '',
        'INSIGHTS AUTOMÁTICOS:',
    ]
    for insight in report_data.get('insights', []):
        lines.append(f'- {insight}')

    lines.extend(['', 'ENTRADAS DO PERÍODO:'])
    if report_data['transactions']:
        for item in report_data['transactions']:
            lines.append(
                f'{item["date_received"]} | {item["client_name"]} | {item["service_name"]} | '
                f'Líquido: {format_brl_plain(item["calc"]["net"])}'
            )
    else:
        lines.append('Sem entradas no período.')

    lines.extend(['', 'DESPESAS DO PERÍODO:'])
    if report_data['expenses']:
        for item in report_data['expenses']:
            lines.append(
                f'{item["date_incurred"]} | {item["description"]} | '
                f'{EXPENSE_CATEGORIES.get(item["category"], item["category"])} | {format_brl_plain(item["amount"])}'
            )
    else:
        lines.append('Sem despesas no período.')

    return lines


@app.route('/export/transactions.txt')
def export_transactions_txt():
    month = parse_month_or_none(request.args.get('month', ''))
    suffix = f'-{month}' if month else ''
    return txt_response(f'infinance-entradas{suffix}.txt', transactions_text_lines(month))


@app.route('/export/transactions.pdf')
def export_transactions_pdf():
    month = parse_month_or_none(request.args.get('month', ''))
    suffix = f'-{month}' if month else ''
    response = pdf_response(f'infinance-entradas{suffix}.pdf', transactions_text_lines(month))
    return response or redirect(url_for('transactions', month=month) if month else url_for('transactions'))


@app.route('/export/expenses.txt')
def export_expenses_txt():
    month = parse_month_or_none(request.args.get('month', ''))
    suffix = f'-{month}' if month else ''
    return txt_response(f'infinance-despesas{suffix}.txt', expenses_text_lines(month))


@app.route('/export/expenses.pdf')
def export_expenses_pdf():
    month = parse_month_or_none(request.args.get('month', ''))
    suffix = f'-{month}' if month else ''
    response = pdf_response(f'infinance-despesas{suffix}.pdf', expenses_text_lines(month))
    return response or redirect(url_for('expenses', month=month) if month else url_for('expenses'))


@app.route('/export/monthly.txt')
def export_monthly_txt():
    month = parse_month_or_default(request.args.get('month', ''))
    report_data = build_monthly_report_data(month)
    company = get_company_settings()
    lines = monthly_text_lines(month, report_data, company)
    return txt_response(f'infinance-relatorio-{month}.txt', lines)


@app.route('/export/monthly.pdf')
def export_monthly_pdf():
    month = parse_month_or_default(request.args.get('month', ''))
    report_data = build_monthly_report_data(month)
    company = get_company_settings()
    lines = monthly_text_lines(month, report_data, company)
    response = pdf_response(f'infinance-relatorio-{month}.pdf', lines)
    return response or redirect(url_for('monthly_report', month=month))


@app.template_filter('currency')
def currency(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    formatted = f'{number:,.2f}'
    return 'R$ ' + formatted.replace(',', 'X').replace('.', ',').replace('X', '.')


@app.template_filter('percent')
def percent(value: Any) -> str:
    try:
        number = float(value) * 100
    except (TypeError, ValueError):
        number = 0.0
    return f'{number:.2f}%'.replace('.', ',')


def bootstrap_database() -> None:
    if _BOOTSTRAP_ONCE.is_set():
        return

    with _BOOTSTRAP_LOCK:
        if _BOOTSTRAP_ONCE.is_set():
            return
        with app.app_context():
            init_db()
            seed_data()
        _BOOTSTRAP_ONCE.set()


bootstrap_database()


def is_loopback_host(host: str) -> bool:
    clean_host = (host or '').strip().lower()
    return clean_host in {'127.0.0.1', 'localhost', '::1'}


def supports_ansi() -> bool:
    disabled = (os.getenv('NO_COLOR') or '').strip()
    if disabled:
        return False
    explicit_disable = (os.getenv('INFINANCE_NO_ANSI') or '').strip().lower()
    if explicit_disable in {'1', 'true', 'yes', 'on'}:
        return False
    term = (os.getenv('TERM') or '').strip().lower()
    if term == 'dumb':
        return False
    return bool(getattr(sys.stdout, 'isatty', lambda: False)())


def resolve_banner_style() -> str:
    requested = (os.getenv('INFINANCE_BANNER_STYLE') or 'neon').strip().lower()
    if requested in {'neon', 'metal'}:
        return requested
    return 'neon'


def print_startup_banner(host: str, port: int, mode_label: str, style: str = 'neon') -> None:
    title_lines = [
        '██╗███╗   ██╗███████╗██╗███╗   ██╗ █████╗ ███╗   ██╗ ██████╗███████╗',
        '██║████╗  ██║██╔════╝██║████╗  ██║██╔══██╗████╗  ██║██╔════╝██╔════╝',
        '██║██╔██╗ ██║█████╗  ██║██╔██╗ ██║███████║██╔██╗ ██║██║     █████╗  ',
        '██║██║╚██╗██║██╔══╝  ██║██║╚██╗██║██╔══██║██║╚██╗██║██║     ██╔══╝  ',
        '██║██║ ╚████║██║     ██║██║ ╚████║██║  ██║██║ ╚████║╚██████╗███████╗',
        '╚═╝╚═╝  ╚═══╝╚═╝     ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝╚══════╝',
    ]
    style_name = style if style in {'neon', 'metal'} else 'neon'
    subtitle = (
        'Sistema Financeiro e Fiscal // Pixel Neon'
        if style_name == 'neon'
        else 'Sistema Financeiro e Fiscal // Retro Metal'
    )
    style_badge = f'Estilo: {style_name.upper()}'
    launch_url = f'http://{host}:{port}/'
    info_left = f'Modo: {mode_label}'
    info_right = f'URL: {launch_url}'
    width = max(
        len(max(title_lines, key=len)),
        len(subtitle) + 2,
        len(style_badge) + 2,
        len(info_left) + len(info_right) + 5,
    )
    width = max(width, 78)

    ansi = supports_ansi()
    c_reset = '\033[0m' if ansi else ''
    if style_name == 'metal':
        c_border = '\033[37m' if ansi else ''
        c_title = '\033[97m' if ansi else ''
        c_sub = '\033[37m' if ansi else ''
        c_meta = '\033[90m' if ansi else ''
        c_shadow = '\033[90m' if ansi else ''
        shadow_char = '▓'
    else:
        # Neon theme: white solid text with green contour/shadow.
        c_border = '\033[92m' if ansi else ''
        c_title = '\033[97m' if ansi else ''
        c_sub = '\033[92m' if ansi else ''
        c_meta = '\033[90m' if ansi else ''
        c_shadow = '\033[32m' if ansi else ''
        shadow_char = '░'

    def pad(text: str) -> str:
        return text + (' ' * (width - len(text)))

    print()
    print(f"{c_border}╔{'═' * (width + 2)}╗{c_reset}")
    for line in title_lines:
        print(f"{c_border}║{c_reset} {c_title}{pad(line)}{c_reset} {c_border}║{c_shadow}{shadow_char}{c_reset}")
    print(f"{c_border}║{c_reset} {c_sub}{pad(subtitle)}{c_reset} {c_border}║{c_shadow}{shadow_char}{c_reset}")
    print(f"{c_border}║{c_reset} {c_sub}{pad(style_badge)}{c_reset} {c_border}║{c_shadow}{shadow_char}{c_reset}")
    print(f"{c_border}║{c_reset} {c_meta}{pad(f'{info_left}   {info_right}')}{c_reset} {c_border}║{c_shadow}{shadow_char}{c_reset}")
    print(f"{c_border}╚{'═' * (width + 2)}╝{c_shadow}{shadow_char}{c_reset}")
    print(f"{c_shadow} {shadow_char * (width + 4)}{c_reset}")
    print()


if __name__ == '__main__':
    host = os.getenv('INFINANCE_HOST', '127.0.0.1')
    allow_remote_raw = os.getenv('INFINANCE_ALLOW_REMOTE', '0').strip().lower()
    allow_remote = allow_remote_raw in {'1', 'true', 'yes', 'on'}
    if not allow_remote and not is_loopback_host(host):
        print('[WARN] INFINANCE_HOST externo bloqueado por seguranca. Usando 127.0.0.1.')
        print('[WARN] Defina INFINANCE_ALLOW_REMOTE=1 para liberar acesso remoto conscientemente.')
        host = '127.0.0.1'

    debug_raw = os.getenv('INFINANCE_DEBUG', '0').strip().lower()
    debug_requested = debug_raw in {'1', 'true', 'yes', 'on'}
    if debug_requested:
        print('[WARN] INFINANCE_DEBUG solicitado, mas o modo debug foi desabilitado por seguranca.')

    try:
        port = int(os.getenv('INFINANCE_PORT', os.getenv('PORT', '5000')))
    except ValueError:
        port = 5000

    try:
        waitress_threads = int((os.getenv('INFINANCE_WAITRESS_THREADS') or '8').strip())
    except ValueError:
        waitress_threads = 8
    waitress_threads = max(waitress_threads, 4)
    mode_label = 'PRODUÇÃO (Waitress)' if waitress_serve is not None else 'DESENVOLVIMENTO (Flask)'
    print_startup_banner(host, port, mode_label, resolve_banner_style())

    if waitress_serve is not None:
        # Reduz ruído no terminal (ex.: "Task queue depth is 1") sem afetar logs de erro.
        logging.getLogger('waitress.queue').setLevel(logging.ERROR)
        print(f'[INFO] Starting INFinance in PRODUCTION mode on port {port}...')
        waitress_serve(app, host=host, port=port, threads=waitress_threads)
    else:
        print('[WARN] Waitress não encontrada. Usando servidor de desenvolvimento do Flask.')
        app.run(host=host, port=port, debug=False)


