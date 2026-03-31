import unittest
from math import isfinite
from datetime import datetime, timezone

from app import (
    app,
    bootstrap_database,
    build_monthly_report_data,
    calculate_das_advanced,
    calculate_transaction,
    execute,
    get_db,
    get_user_by_username,
)
from werkzeug.security import generate_password_hash


class AuthAndCalculationsTest(unittest.TestCase):
    # Keeps the margin insight test consistent without coupling to every textual detail.
    MARGIN_INSIGHT_PATTERN = r'^Margem operacional estimada: -?\d+(?:\.\d+)?% sobre a receita bruta do período\.$'
    PERCENTAGE_VALUE_PATTERN = r'-?\d+(?:\.\d+)?%'

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
                        datetime.now(timezone.utc).isoformat(timespec='seconds'),
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

    def login_with_valid_credentials(self, csrf_token: str):
        return self.client.post(
            '/login',
            data={
                '_csrf_token': csrf_token,
                'username': self.username,
                'password': self.password,
            },
            follow_redirects=False,
        )

    def test_set_csrf_sets_session_token(self):
        token = 'csrf-test-coverage'
        returned = self.set_csrf(token)
        self.assertEqual(returned, token)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('_csrf_token'), token)

    def test_login_with_valid_credentials_helper(self):
        csrf_token = self.set_csrf('csrf-helper-ok')
        response = self.login_with_valid_credentials(csrf_token)
        self.assertEqual(response.status_code, 302)
        location = response.headers.get('Location', '')
        self.assertTrue(location.endswith('/') or location.endswith('/dashboard'))

    def test_login_success(self):
        csrf_token = self.set_csrf('csrf-auth-ok')
        login_response = self.login_with_valid_credentials(csrf_token)
        self.assertEqual(login_response.status_code, 302)
        location = login_response.headers.get('Location', '')
        self.assertTrue(location.endswith('/') or location.endswith('/dashboard'))

        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('user_id'), self.user_id)
            self.assertEqual(sess.get('username'), self.username)
            self.assertEqual(sess.get('role'), 'viewer')

    def test_logout_flow(self):
        csrf_token = self.set_csrf('csrf-auth-logout')
        login_response = self.login_with_valid_credentials(csrf_token)
        self.assertEqual(login_response.status_code, 302)

        logout_response = self.client.post(
            '/logout',
            data={'_csrf_token': csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(logout_response.status_code, 302)
        self.assertIn('/login', logout_response.headers.get('Location', ''))

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
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers.get('Location', ''))

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
        self.assertEqual(response.status_code, 302)
        location = response.headers.get('Location', '')
        self.assertNotIn('evil.example', location)
        self.assertTrue(location.endswith('/') or location.endswith('/dashboard'))

    def test_login_rejects_protocol_relative_open_redirect(self):
        csrf_token = self.set_csrf('csrf-auth-open-redirect-proto-relative')
        response = self.client.post(
            '/login',
            data={
                '_csrf_token': csrf_token,
                'username': self.username,
                'password': self.password,
                'next': '//evil.example/steal',
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        location = response.headers.get('Location', '')
        self.assertNotIn('evil.example', location)
        self.assertTrue(location.endswith('/') or location.endswith('/dashboard'))

    def test_login_rejects_credential_url_open_redirect(self):
        csrf_token = self.set_csrf('csrf-auth-open-redirect-credentials')
        response = self.client.post(
            '/login',
            data={
                '_csrf_token': csrf_token,
                'username': self.username,
                'password': self.password,
                'next': 'http://user:pass@evil.example/steal',
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        location = response.headers.get('Location', '')
        self.assertNotIn('evil.example', location)
        self.assertTrue(location.endswith('/') or location.endswith('/dashboard'))

    def test_login_requires_csrf_token(self):
        response = self.client.post(
            '/login',
            data={
                'username': self.username,
                'password': self.password,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers.get('Location', ''))

        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('user_id'))

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

    def test_calculate_transaction_zero_amount_with_invoice(self):
        result = calculate_transaction(0.0, 'PJ', True, 0.1, 0.0)
        self.assertEqual(result['gross'], 0.0)
        self.assertEqual(result['invoice_tax'], 0.0)
        self.assertEqual(result['pf_tax'], 0.0)
        self.assertEqual(result['total_tax'], 0.0)
        self.assertEqual(result['net'], 0.0)
        self.assertEqual(result['effective_rate'], 0.0)

    def test_calculate_transaction_pf_channel_with_invoice_flag(self):
        result = calculate_transaction(1000.0, 'PF', True, 0.2, 125.5)
        self.assertEqual(result['gross'], 1000.0)
        self.assertEqual(result['invoice_tax'], 0.0)
        self.assertEqual(result['pf_tax'], 125.5)
        self.assertEqual(result['total_tax'], 125.5)
        self.assertEqual(result['net'], 874.5)
        self.assertEqual(result['effective_rate'], 12.55)

    def test_calculate_transaction_very_large_amounts(self):
        gross = 1_000_000_000_000.0
        invoice_rate = 0.05
        result = calculate_transaction(gross, 'PJ', True, invoice_rate, 0.0)
        self.assertTrue(isfinite(result['gross']))
        self.assertTrue(isfinite(result['invoice_tax']))
        self.assertTrue(isfinite(result['total_tax']))
        self.assertTrue(isfinite(result['net']))
        self.assertTrue(isfinite(result['effective_rate']))
        self.assertEqual(result['gross'], gross)
        self.assertAlmostEqual(result['invoice_tax'], gross * invoice_rate, places=2)
        self.assertAlmostEqual(result['total_tax'], result['invoice_tax'] + result['pf_tax'], places=2)
        self.assertAlmostEqual(result['net'], result['gross'] - result['total_tax'], places=2)
        self.assertAlmostEqual(result['effective_rate'], (result['total_tax'] / gross) * 100, places=2)

    def test_calculate_das_advanced_zero_revenue(self):
        zero_revenue_result = calculate_das_advanced(5000.0, 0.0, 1000.0, 'III_V')
        zero_revenue_error = zero_revenue_result.get('error')
        self.assertIsNotNone(zero_revenue_error)
        self.assertEqual(
            zero_revenue_error,
            'Informe uma receita bruta acumulada dos últimos 12 meses (RBT12) maior que zero.',
        )

    def test_calculate_das_advanced_over_limit(self):
        over_limit_result = calculate_das_advanced(5000.0, 4_900_000.0, 100_000.0, 'III_V')
        over_limit_error = over_limit_result.get('error')
        self.assertIsNotNone(over_limit_error)
        self.assertEqual(
            over_limit_error,
            'RBT12 acima de R$ 4.800.000,00. O cálculo simplificado aqui não cobre esse regime.',
        )

    def test_calculate_das_advanced_high_factor(self):
        high_factor_result = calculate_das_advanced(10_000.0, 200_000.0, 60_000.0, 'III_V')
        self.assertIsNone(high_factor_result.get('error'))
        self.assertEqual(high_factor_result['annex'], 'III')
        self.assertTrue(high_factor_result['uses_factor_r'])

    def test_calculate_das_advanced_low_factor(self):
        low_factor_result = calculate_das_advanced(10_000.0, 200_000.0, 20_000.0, 'III_V')
        self.assertIsNone(low_factor_result.get('error'))
        self.assertEqual(low_factor_result['annex'], 'V')
        self.assertTrue(low_factor_result['uses_factor_r'])

    def test_calculate_das_advanced_forced_annex(self):
        baseline_annex_ii_result = calculate_das_advanced(10_000.0, 200_000.0, 20_000.0, 'II')
        self.assertIsNone(baseline_annex_ii_result.get('error'))
        self.assertEqual(baseline_annex_ii_result['annex'], 'II')

        forced_annex_result = calculate_das_advanced(10_000.0, 200_000.0, 20_000.0, 'III_V', forced_annex='II')
        self.assertIsNone(forced_annex_result.get('error'))
        self.assertEqual(forced_annex_result['annex'], 'II')
        self.assertFalse(forced_annex_result['uses_factor_r'])

        for key, baseline_value in baseline_annex_ii_result.items():
            if key in {'error', 'annex', 'uses_factor_r'}:
                continue
            forced_value = forced_annex_result.get(key)
            if isinstance(baseline_value, (int, float)) and isinstance(forced_value, (int, float)):
                self.assertAlmostEqual(forced_value, baseline_value, places=6)

    def test_calculate_das_advanced_invalid_forced_annex(self):
        for forced_annex in ['INVALID', 'VI']:
            with self.subTest(forced_annex=forced_annex):
                result = calculate_das_advanced(10_000.0, 200_000.0, 20_000.0, 'III_V', forced_annex=forced_annex)
                self.assertIsNone(result.get('error'))
                self.assertIn(result['annex'], {'III', 'V'})

    def test_build_monthly_report_data_includes_insights(self):
        month = '2099-01'
        with app.app_context():
            db = get_db()
            db.execute('SAVEPOINT monthly_insights_test')
            try:
                now = datetime.now(timezone.utc).isoformat(timespec='seconds')
                client_cursor = db.execute(
                    'INSERT INTO clients (name, person_type, notes, created_at) VALUES (?, ?, ?, ?)',
                    ('Cliente Insights Janeiro', 'PJ', 'Cliente de teste para insights', now),
                )
                service_cursor = db.execute(
                    '''INSERT INTO services (
                           name, service_type, tax_rate, cnae, cnae_description, annex, factor_r_applicable, description_template, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (
                        'Serviço Insights Janeiro',
                        'operacional',
                        0.10,
                        '6319-4/00',
                        'Serviço de teste para geração de insights',
                        'III',
                        1,
                        'Template teste insights',
                        now,
                    ),
                )
                client_id = int(client_cursor.lastrowid)
                service_id = int(service_cursor.lastrowid)

                db.execute(
                    '''INSERT INTO transactions (
                           client_id, service_id, amount, channel, invoice_issued, invoice_number, invoice_description,
                           expected_pf_tax, date_received, status, notes, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (
                        client_id,
                        service_id,
                        1000.0,
                        'PJ',
                        1,
                        'NF-INSIGHTS-2099-01',
                        'Transação de teste para insights',
                        0.0,
                        '2099-01-15',
                        'recebido',
                        'Teste determinístico',
                        now,
                    ),
                )

                db.execute(
                    '''INSERT INTO expenses (description, category, amount, date_incurred, is_fixed, notes, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (
                        'Despesa de teste para insights',
                        'marketing',
                        400.0,
                        '2099-01-20',
                        0,
                        'Teste determinístico',
                        now,
                    ),
                )

                data = build_monthly_report_data(month)
            finally:
                db.execute('ROLLBACK TO SAVEPOINT monthly_insights_test')
                db.execute('RELEASE SAVEPOINT monthly_insights_test')
        self.assertEqual(data.get('month'), month)
        self.assertIn('insights', data)
        self.assertIsInstance(data['insights'], list)
        insights = data['insights']

        for insight in insights:
            self.assertIsInstance(insight, str)
            self.assertNotEqual(insight.strip(), '')

        gross = float(data['income_totals']['gross_total'])
        expense_total = float(data['expense_total'])
        net = float(data['income_totals']['net_total'])
        self.assertGreater(gross, 0.0)
        self.assertGreater(expense_total, 0.0)
        self.assertGreater(net, 0.0)
        self.assertEqual(len(insights), 3)

        first_insight = insights[0]
        self.assertRegex(first_insight, self.MARGIN_INSIGHT_PATTERN)

        second_insight = insights[1]
        self.assertTrue(second_insight.startswith('Maior categoria de despesas: '))
        self.assertIn(' em R$ ', second_insight)

        third_insight = insights[2]
        self.assertTrue(third_insight.startswith('Pressão tributária estimada: '))
        self.assertRegex(third_insight, self.PERCENTAGE_VALUE_PATTERN)
        self.assertIn('receita bruta', third_insight)

    def test_monthly_insights_savepoint_rollback_behavior(self):
        with app.app_context():
            db = get_db()
            marker = f'Cliente Savepoint Rollback {datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")}'
            pre_existing = db.execute('SELECT COUNT(*) FROM clients WHERE name = ?', (marker,)).fetchone()[0]
            self.assertEqual(pre_existing, 0)

            db.execute('SAVEPOINT monthly_insights_rollback_test')
            try:
                now = datetime.now(timezone.utc).isoformat(timespec='seconds')
                db.execute(
                    'INSERT INTO clients (name, person_type, notes, created_at) VALUES (?, ?, ?, ?)',
                    (marker, 'PJ', 'Cliente temporário para testar rollback de savepoint', now),
                )
                in_savepoint_count = db.execute('SELECT COUNT(*) FROM clients WHERE name = ?', (marker,)).fetchone()[0]
                self.assertEqual(in_savepoint_count, 1)
                raise RuntimeError('force rollback scenario')
            except RuntimeError:
                pass
            finally:
                db.execute('ROLLBACK TO SAVEPOINT monthly_insights_rollback_test')
                db.execute('RELEASE SAVEPOINT monthly_insights_rollback_test')

            post_rollback_count = db.execute('SELECT COUNT(*) FROM clients WHERE name = ?', (marker,)).fetchone()[0]
            self.assertEqual(post_rollback_count, 0)


if __name__ == '__main__':
    unittest.main()
