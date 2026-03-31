import unittest
from datetime import datetime

from app import (
    app,
    bootstrap_database,
    build_monthly_report_data,
    calculate_das_advanced,
    calculate_transaction,
    execute,
    get_user_by_username,
)
from werkzeug.security import generate_password_hash


class AuthAndCalculationsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True)
        bootstrap_database()
        cls.username = 'qa_auth_user'
        cls.password = 'QaAuth@123'
        with app.app_context():
            existing = get_user_by_username(cls.username)
            if existing is None:
                execute(
                    '''INSERT INTO users (username, password_hash, role, must_change_password, created_at)
                       VALUES (?, ?, 'viewer', 0, ?)''',
                    (
                        cls.username,
                        generate_password_hash(cls.password),
                        datetime.now().isoformat(timespec='seconds'),
                    ),
                )
            else:
                execute(
                    'UPDATE users SET password_hash = ?, role = ?, must_change_password = 0 WHERE id = ?',
                    (generate_password_hash(cls.password), 'viewer', int(existing['id'])),
                )
            refreshed = get_user_by_username(cls.username)
            cls.user_id = int(refreshed['id'])

    def setUp(self):
        self.client = app.test_client()

    def set_csrf(self, token: str = 'test-csrf-auth') -> str:
        with self.client.session_transaction() as sess:
            sess['_csrf_token'] = token
        return token

    def test_login_success_and_logout_flow(self):
        csrf_token = self.set_csrf('csrf-auth-ok')
        login_response = self.client.post(
            '/login',
            data={
                '_csrf_token': csrf_token,
                'username': self.username,
                'password': self.password,
                'next': '/dashboard',
            },
            follow_redirects=False,
        )
        try:
            self.assertEqual(login_response.status_code, 302)
            location = login_response.headers.get('Location', '')
            self.assertTrue(location.endswith('/') or location.endswith('/dashboard'))
        finally:
            login_response.close()

        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('user_id'), self.user_id)
            self.assertEqual(sess.get('username'), self.username)
            self.assertEqual(sess.get('role'), 'viewer')

        logout_response = self.client.post(
            '/logout',
            data={'_csrf_token': csrf_token},
            follow_redirects=False,
        )
        try:
            self.assertEqual(logout_response.status_code, 302)
            self.assertIn('/login', logout_response.headers.get('Location', ''))
        finally:
            logout_response.close()

        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('user_id'))
            self.assertIsNone(sess.get('username'))
            self.assertIsNone(sess.get('role'))

    def test_login_invalid_password(self):
        csrf_token = self.set_csrf('csrf-auth-invalid')
        response = self.client.post(
            '/login',
            data={
                '_csrf_token': csrf_token,
                'username': self.username,
                'password': 'SenhaErrada!123',
            },
            follow_redirects=False,
        )
        try:
            self.assertEqual(response.status_code, 302)
            self.assertIn('/login', response.headers.get('Location', ''))
        finally:
            response.close()

        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('user_id'))

    def test_login_rejects_open_redirect(self):
        csrf_token = self.set_csrf('csrf-auth-open-redirect')
        response = self.client.post(
            '/login',
            data={
                '_csrf_token': csrf_token,
                'username': self.username,
                'password': self.password,
                'next': 'https://evil.example/steal',
            },
            follow_redirects=False,
        )
        try:
            self.assertEqual(response.status_code, 302)
            location = response.headers.get('Location', '')
            self.assertNotIn('evil.example', location)
            self.assertTrue(location.endswith('/') or location.endswith('/dashboard'))
        finally:
            response.close()

    def test_calculate_transaction_pj_with_invoice(self):
        result = calculate_transaction(1000.0, 'PJ', True, 0.06, 120.0)
        self.assertEqual(result['gross'], 1000.0)
        self.assertEqual(result['invoice_tax'], 60.0)
        self.assertEqual(result['pf_tax'], 0.0)
        self.assertEqual(result['total_tax'], 60.0)
        self.assertEqual(result['net'], 940.0)
        self.assertEqual(result['effective_rate'], 6.0)

    def test_calculate_transaction_guards_negative_values(self):
        result = calculate_transaction(-50.0, 'PF', False, -0.15, -30.0)
        self.assertEqual(result['gross'], 0.0)
        self.assertEqual(result['invoice_tax'], 0.0)
        self.assertEqual(result['pf_tax'], 0.0)
        self.assertEqual(result['total_tax'], 0.0)
        self.assertEqual(result['net'], 0.0)
        self.assertEqual(result['effective_rate'], 0.0)

    def test_calculate_das_advanced_edge_cases(self):
        error_zero = calculate_das_advanced(5000.0, 0.0, 1000.0, 'III_V')
        self.assertIsNotNone(error_zero.get('error'))

        error_over = calculate_das_advanced(5000.0, 4_900_000.0, 100_000.0, 'III_V')
        self.assertIsNotNone(error_over.get('error'))

        high_factor = calculate_das_advanced(10_000.0, 200_000.0, 60_000.0, 'III_V')
        self.assertIsNone(high_factor.get('error'))
        self.assertEqual(high_factor['annex'], 'III')
        self.assertTrue(high_factor['uses_factor_r'])

        low_factor = calculate_das_advanced(10_000.0, 200_000.0, 20_000.0, 'III_V')
        self.assertIsNone(low_factor.get('error'))
        self.assertEqual(low_factor['annex'], 'V')
        self.assertTrue(low_factor['uses_factor_r'])

        forced = calculate_das_advanced(10_000.0, 200_000.0, 20_000.0, 'III_V', forced_annex='II')
        self.assertIsNone(forced.get('error'))
        self.assertEqual(forced['annex'], 'II')
        self.assertFalse(forced['uses_factor_r'])

    def test_build_monthly_report_data_includes_insights(self):
        month = datetime.now().strftime('%Y-%m')
        with app.app_context():
            data = build_monthly_report_data(month)
        self.assertIn('insights', data)
        self.assertIsInstance(data['insights'], list)


if __name__ == '__main__':
    unittest.main()
