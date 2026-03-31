import unittest
from datetime import datetime

from app import app, bootstrap_database, execute, fetch_one, get_user_by_username, month_to_date_range
from werkzeug.security import generate_password_hash


class RoutesSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True)
        bootstrap_database()
        with app.app_context():
            admin = get_user_by_username('admin')
            if admin is None:
                raise RuntimeError('Usuário admin não foi criado no bootstrap.')
            cls.admin_id = int(admin['id'])
            cls.admin_username = admin['username']
            cls.admin_role = admin['role']
            cls.operator_id, cls.operator_username, cls.operator_role = cls.ensure_user('operator_test', 'operator')
            cls.viewer_id, cls.viewer_username, cls.viewer_role = cls.ensure_user('viewer_test', 'viewer')

    @classmethod
    def ensure_user(cls, username: str, role: str):
        existing = get_user_by_username(username)
        if existing is None:
            execute(
                '''INSERT INTO users (username, password_hash, role, must_change_password, created_at)
                   VALUES (?, ?, ?, 0, ?)''',
                (
                    username,
                    generate_password_hash('Test@1234'),
                    role,
                    datetime.now().isoformat(timespec='seconds'),
                ),
            )
            existing = get_user_by_username(username)
        else:
            execute('UPDATE users SET role = ?, must_change_password = 0 WHERE id = ?', (role, int(existing['id'])))
            existing = get_user_by_username(username)
        return int(existing['id']), existing['username'], existing['role']

    def setUp(self):
        self.client = app.test_client()
        self.login_as_admin()

    def login_as_admin(self):
        self.login_with_identity(self.admin_id, self.admin_username, self.admin_role)

    def login_with_identity(self, user_id: int, username: str, role: str):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username
            sess['role'] = role
            sess['_csrf_token'] = 'test-csrf-token'

    def assert_route_ok(self, path: str):
        response = self.client.get(path)
        try:
            self.assertEqual(response.status_code, 200, msg=f"Falha em {path}: {response.status_code}")
        finally:
            response.close()

    def assert_download_ok(self, path: str, expected_mimetype: str, expected_filename: str):
        response = self.client.get(path)
        try:
            self.assertEqual(response.status_code, 200, msg=f"Download falhou em {path}: {response.status_code}")
            self.assertEqual(response.mimetype, expected_mimetype)
            disposition = response.headers.get('Content-Disposition', '')
            self.assertIn('attachment', disposition)
            self.assertIn(expected_filename, disposition)
        finally:
            response.close()

    def test_main_routes(self):
        for path in (
            '/',
            '/about',
            '/company',
            '/clients',
            '/services',
            '/transactions',
            '/expenses',
            '/simulator',
            '/das',
            '/reports/monthly',
            '/users',
        ):
            with self.subTest(path=path):
                self.assert_route_ok(path)

    def test_favicon_route(self):
        response = self.client.get('/favicon.ico')
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'image/svg+xml')
        finally:
            response.close()

    def test_security_headers(self):
        response = self.client.get('/')
        try:
            self.assertEqual(response.headers.get('X-Content-Type-Options'), 'nosniff')
            self.assertEqual(response.headers.get('X-Frame-Options'), 'DENY')
            csp = response.headers.get('Content-Security-Policy', '')
            self.assertIn("default-src 'self'", csp)
            self.assertIn("object-src 'none'", csp)
            self.assertNotIn("'unsafe-inline'", csp)
            self.assertNotIn('unsafe-eval', csp)
        finally:
            response.close()

    def test_month_range_helper(self):
        self.assertEqual(month_to_date_range('2026-03'), ('2026-03-01', '2026-04-01'))
        self.assertIsNone(month_to_date_range('2026-13'))

    def test_requires_authentication(self):
        client = app.test_client()
        response = client.get('/company', follow_redirects=False)
        try:
            self.assertEqual(response.status_code, 302)
            self.assertIn('/login', response.headers.get('Location', ''))
        finally:
            response.close()

    def test_filters_and_pagination_routes(self):
        for path in (
            '/clients?q=exemplo&page=1',
            '/services?q=web&page=1',
            '/transactions?month=2026-03&q=cliente&page=1',
            '/expenses?month=2026-03&q=hospedagem&page=1',
        ):
            with self.subTest(path=path):
                self.assert_route_ok(path)

    def test_about_avatar_fallback_markup(self):
        response = self.client.get('/about')
        try:
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertIn('data-author-avatar-image', html)
            self.assertIn('data-author-avatar-fallback', html)
            self.assertNotIn('onerror=', html)
            self.assertIn('IN', html)
            self.assertIn('AB', html)
        finally:
            response.close()

    def test_viewer_cannot_write_data(self):
        self.login_with_identity(self.viewer_id, self.viewer_username, self.viewer_role)
        blocked_name = f'Cliente Bloqueado {datetime.now().strftime("%Y%m%d%H%M%S")}'
        response = self.client.post(
            '/clients',
            data={
                '_csrf_token': 'test-csrf-token',
                'name': blocked_name,
                'person_type': 'PF',
            },
            follow_redirects=False,
        )
        try:
            self.assertEqual(response.status_code, 302)
            self.assertIn('/', response.headers.get('Location', ''))
            with app.app_context():
                found = fetch_one('SELECT id FROM clients WHERE name = ?', (blocked_name,))
                self.assertIsNone(found)
        finally:
            response.close()

    def test_operator_cannot_access_admin_routes(self):
        self.login_with_identity(self.operator_id, self.operator_username, self.operator_role)
        response = self.client.get('/users', follow_redirects=False)
        try:
            self.assertEqual(response.status_code, 302)
            self.assertIn('/', response.headers.get('Location', ''))
        finally:
            response.close()

    def test_admin_crud_client_flow(self):
        self.login_as_admin()
        client_name = f'Cliente QA {datetime.now().strftime("%Y%m%d%H%M%S")}'
        create_response = self.client.post(
            '/clients',
            data={
                '_csrf_token': 'test-csrf-token',
                'name': client_name,
                'person_type': 'PJ',
                'notes': 'Criado por teste automatizado',
            },
            follow_redirects=False,
        )
        try:
            self.assertEqual(create_response.status_code, 302)
            self.assertIn('/clients', create_response.headers.get('Location', ''))
        finally:
            create_response.close()

        with app.app_context():
            created = fetch_one('SELECT id FROM clients WHERE name = ?', (client_name,))
            self.assertIsNotNone(created)
            client_id = int(created['id'])

        delete_response = self.client.post(
            f'/clients/{client_id}/delete',
            data={'_csrf_token': 'test-csrf-token'},
            follow_redirects=False,
        )
        try:
            self.assertEqual(delete_response.status_code, 302)
            self.assertIn('/clients', delete_response.headers.get('Location', ''))
        finally:
            delete_response.close()

        with app.app_context():
            removed = fetch_one('SELECT id FROM clients WHERE id = ?', (client_id,))
            self.assertIsNone(removed)

    def test_admin_can_rename_and_delete_non_default_user(self):
        suffix = datetime.now().strftime("%Y%m%d%H%M%S")
        original_username = f'renomear_{suffix}'
        renamed_username = f'editado_{suffix}'

        with app.app_context():
            execute(
                '''INSERT INTO users (username, password_hash, role, must_change_password, created_at)
                   VALUES (?, ?, ?, 0, ?)''',
                (
                    original_username,
                    generate_password_hash('Renomear@123'),
                    'viewer',
                    datetime.now().isoformat(timespec='seconds'),
                ),
            )
            created = get_user_by_username(original_username)
            self.assertIsNotNone(created)
            user_id = int(created['id'])

        rename_response = self.client.post(
            f'/users/{user_id}/username',
            data={
                '_csrf_token': 'test-csrf-token',
                'username': renamed_username,
            },
            follow_redirects=False,
        )
        try:
            self.assertEqual(rename_response.status_code, 302)
            self.assertIn('/users', rename_response.headers.get('Location', ''))
        finally:
            rename_response.close()

        with app.app_context():
            self.assertIsNone(get_user_by_username(original_username))
            renamed = get_user_by_username(renamed_username)
            self.assertIsNotNone(renamed)
            self.assertEqual(int(renamed['id']), user_id)

        delete_response = self.client.post(
            f'/users/{user_id}/delete',
            data={'_csrf_token': 'test-csrf-token'},
            follow_redirects=False,
        )
        try:
            self.assertEqual(delete_response.status_code, 302)
            self.assertIn('/users', delete_response.headers.get('Location', ''))
        finally:
            delete_response.close()

        with app.app_context():
            self.assertIsNone(fetch_one('SELECT id FROM users WHERE id = ?', (user_id,)))

    def test_admin_cannot_delete_default_system_user(self):
        response = self.client.post(
            f'/users/{self.admin_id}/delete',
            data={'_csrf_token': 'test-csrf-token'},
            follow_redirects=False,
        )
        try:
            self.assertEqual(response.status_code, 302)
            self.assertIn('/users', response.headers.get('Location', ''))
        finally:
            response.close()

        with app.app_context():
            admin_row = fetch_one('SELECT id FROM users WHERE id = ?', (self.admin_id,))
            self.assertIsNotNone(admin_row)

    def test_export_endpoints(self):
        self.assert_download_ok(
            '/export/transactions.csv?month=2026-03',
            'text/csv',
            'infinance-entradas-2026-03.csv',
        )
        self.assert_download_ok(
            '/export/transactions.pdf?month=2026-03',
            'application/pdf',
            'infinance-entradas-2026-03.pdf',
        )
        self.assert_download_ok(
            '/export/expenses.txt?month=2026-03',
            'text/plain',
            'infinance-despesas-2026-03.txt',
        )
        self.assert_download_ok(
            '/export/expenses.xlsx?month=2026-03',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'infinance-despesas-2026-03.xlsx',
        )
        self.assert_download_ok(
            '/export/monthly.xlsx?month=2026-03',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'infinance-relatorio-2026-03.xlsx',
        )
        self.assert_download_ok(
            '/export/monthly.pdf?month=2026-03',
            'application/pdf',
            'infinance-relatorio-2026-03.pdf',
        )

    def test_admin_service_and_transaction_crud_flow(self):
        suffix = datetime.now().strftime("%Y%m%d%H%M%S")
        client_name = f'Cliente Fluxo {suffix}'
        service_name = f'Serviço Fluxo {suffix}'

        create_client = self.client.post(
            '/clients',
            data={
                '_csrf_token': 'test-csrf-token',
                'name': client_name,
                'person_type': 'PJ',
                'notes': 'Cliente para fluxo de transações',
            },
            follow_redirects=False,
        )
        try:
            self.assertEqual(create_client.status_code, 302)
            self.assertIn('/clients', create_client.headers.get('Location', ''))
        finally:
            create_client.close()

        create_service = self.client.post(
            '/services',
            data={
                '_csrf_token': 'test-csrf-token',
                'name': service_name,
                'service_type': 'operacional',
                'tax_rate': '6',
                'cnae': '6201-5/01',
                'cnae_description': 'Desenvolvimento de software',
                'annex': 'III',
                'factor_r_applicable': 'on',
                'description_template': 'Serviço criado em teste',
            },
            follow_redirects=False,
        )
        try:
            self.assertEqual(create_service.status_code, 302)
            self.assertIn('/services', create_service.headers.get('Location', ''))
        finally:
            create_service.close()

        with app.app_context():
            client_row = fetch_one('SELECT id FROM clients WHERE name = ?', (client_name,))
            service_row = fetch_one('SELECT id FROM services WHERE name = ?', (service_name,))
            self.assertIsNotNone(client_row)
            self.assertIsNotNone(service_row)
            client_id = int(client_row['id'])
            service_id = int(service_row['id'])

        create_transaction = self.client.post(
            '/transactions',
            data={
                '_csrf_token': 'test-csrf-token',
                'client_id': str(client_id),
                'service_id': str(service_id),
                'amount': '1500',
                'channel': 'PJ',
                'invoice_issued': 'on',
                'invoice_number': f'NF-{suffix}',
                'invoice_description': 'Cobrança do período',
                'expected_pf_tax': '0',
                'date_received': '2026-03-10',
                'status': 'recebido',
                'notes': 'Entrada criada no fluxo de teste',
            },
            follow_redirects=False,
        )
        try:
            self.assertEqual(create_transaction.status_code, 302)
            self.assertIn('/transactions', create_transaction.headers.get('Location', ''))
        finally:
            create_transaction.close()

        with app.app_context():
            transaction_row = fetch_one(
                'SELECT id FROM transactions WHERE invoice_number = ?',
                (f'NF-{suffix}',),
            )
            self.assertIsNotNone(transaction_row)
            transaction_id = int(transaction_row['id'])

        blocked_service_delete = self.client.post(
            f'/services/{service_id}/delete',
            data={'_csrf_token': 'test-csrf-token'},
            follow_redirects=False,
        )
        try:
            self.assertEqual(blocked_service_delete.status_code, 302)
            self.assertIn('/services', blocked_service_delete.headers.get('Location', ''))
        finally:
            blocked_service_delete.close()

        with app.app_context():
            still_exists = fetch_one('SELECT id FROM services WHERE id = ?', (service_id,))
            self.assertIsNotNone(still_exists)

        edit_transaction = self.client.post(
            f'/transactions/{transaction_id}/edit',
            data={
                '_csrf_token': 'test-csrf-token',
                'client_id': str(client_id),
                'service_id': str(service_id),
                'amount': '2000',
                'channel': 'PF',
                'invoice_number': f'NF-{suffix}-EDIT',
                'invoice_description': 'Cobrança revisada',
                'expected_pf_tax': '125',
                'date_received': '2026-03-12',
                'status': 'parcial',
                'notes': 'Entrada editada no fluxo de teste',
            },
            follow_redirects=False,
        )
        try:
            self.assertEqual(edit_transaction.status_code, 302)
            self.assertIn('/transactions', edit_transaction.headers.get('Location', ''))
        finally:
            edit_transaction.close()

        with app.app_context():
            updated = fetch_one(
                'SELECT amount, channel, expected_pf_tax, status, invoice_number FROM transactions WHERE id = ?',
                (transaction_id,),
            )
            self.assertIsNotNone(updated)
            self.assertEqual(float(updated['amount']), 2000.0)
            self.assertEqual(updated['channel'], 'PF')
            self.assertEqual(float(updated['expected_pf_tax']), 125.0)
            self.assertEqual(updated['status'], 'parcial')
            self.assertEqual(updated['invoice_number'], f'NF-{suffix}-EDIT')

        delete_transaction = self.client.post(
            f'/transactions/{transaction_id}/delete',
            data={'_csrf_token': 'test-csrf-token'},
            follow_redirects=False,
        )
        try:
            self.assertEqual(delete_transaction.status_code, 302)
            self.assertIn('/transactions', delete_transaction.headers.get('Location', ''))
        finally:
            delete_transaction.close()

        delete_service = self.client.post(
            f'/services/{service_id}/delete',
            data={'_csrf_token': 'test-csrf-token'},
            follow_redirects=False,
        )
        try:
            self.assertEqual(delete_service.status_code, 302)
            self.assertIn('/services', delete_service.headers.get('Location', ''))
        finally:
            delete_service.close()

        delete_client = self.client.post(
            f'/clients/{client_id}/delete',
            data={'_csrf_token': 'test-csrf-token'},
            follow_redirects=False,
        )
        try:
            self.assertEqual(delete_client.status_code, 302)
            self.assertIn('/clients', delete_client.headers.get('Location', ''))
        finally:
            delete_client.close()

        with app.app_context():
            self.assertIsNone(fetch_one('SELECT id FROM transactions WHERE id = ?', (transaction_id,)))
            self.assertIsNone(fetch_one('SELECT id FROM services WHERE id = ?', (service_id,)))
            self.assertIsNone(fetch_one('SELECT id FROM clients WHERE id = ?', (client_id,)))


if __name__ == '__main__':
    unittest.main()
