import unittest
import contextlib
import hashlib
import os
import re
import secrets
import sys
import uuid
from typing import Any
from math import isfinite, isinf, isnan
from datetime import datetime, timezone

from app import (
    CSRF_EXPIRED_MESSAGE as APP_CSRF_EXPIRED_MESSAGE,
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
    CSRF_EXPIRED_MESSAGE = APP_CSRF_EXPIRED_MESSAGE.casefold()
    MONTH_FORMAT = '%Y-%m'
    USER_INSERT_SQL = (
        'INSERT INTO users (username, password_hash, role, must_change_password, created_at) '
        'VALUES (?, ?, ?, 0, ?)'
    )
    USER_UPDATE_SQL = 'UPDATE users SET password_hash = ?, role = ?, must_change_password = 0 WHERE id = ?'
    CLIENT_INSERT_SQL = 'INSERT INTO clients (name, person_type, notes, created_at) VALUES (?, ?, ?, ?)'
    SERVICE_INSERT_SQL = (
        'INSERT INTO services ('
        'name, service_type, tax_rate, cnae, cnae_description, annex, '
        'factor_r_applicable, description_template, created_at'
        ') VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'
    )
    TRANSACTION_INSERT_SQL = (
        'INSERT INTO transactions ('
        'client_id, service_id, amount, channel, invoice_issued, invoice_number, '
        'invoice_description, expected_pf_tax, date_received, status, notes, created_at'
        ') VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
    )
    EXPENSE_INSERT_SQL = (
        'INSERT INTO expenses ('
        'description, category, amount, date_incurred, is_fixed, notes, created_at'
        ') VALUES (?, ?, ?, ?, ?, ?, ?)'
    )
    # This is a focused subset of the successful DAS payload fields that must
    # not appear when `forced_annex` is invalid (error short-circuit path).
    CALCULATION_RESULT_KEYS = (
        'annex',
        'nominal_rate',
        'effective_rate',
        'estimated_das',
        'factor_r',
    )
    INVALID_FORCED_ANNEX_ERROR_MESSAGE = 'Anexo forçado inválido. Use I, II, III, IV ou V.'
    NUMERIC_COMPARISON_PRECISION = 6
    # Relative tolerance used for boundary comparisons near `sys.float_info.max`.
    # 1e-12 is strict enough to catch regressions while tolerating tiny FP noise.
    FLOAT_MAX_RELATIVE_TOLERANCE = 1e-12
    EXCLUDED_COMPARISON_KEYS = {'error', 'annex', 'uses_factor_r'}
    TRANSACTION_RESULT_KEYS = ('gross', 'invoice_tax', 'pf_tax', 'total_tax', 'net', 'effective_rate')
    VALID_FORCED_ANNEX_VALUES = ('I', 'II', 'III', 'IV', 'V')
    INVALID_FORCED_ANNEX_VALUES = (
        'INVALID',
        'VI',
        # 'III_V' is valid for annex_mode, but forced_annex accepts only a single annex (I-V).
        'III_V',
        '',
        ' ',
        '\n',
        '\t',
        '  ',
        ' None ',
        'X' * 1000,
        '@#$%',
        'ÁÉÍÓÚ',
        123,
        0.0,
        'i',
        'ii',
        'iii',
        'iv',
        'v',
        object(),
    )
    # This keeps the test_build_monthly_report_data_includes_insights margin assertion
    # consistent without coupling to every textual detail.
    # NOTE: [.,] intentionally accepts both comma and period as decimal separators
    # to tolerate locale-dependent formatting in test output.
    MARGIN_INSIGHT_PREFIX_PATTERN = r'Margem operacional estimada:'
    MARGIN_INSIGHT_CONTEXT_PATTERN = r'sobre a receita bruta do período'
    MARGIN_INSIGHT_PATTERN = (
        rf'^{MARGIN_INSIGHT_PREFIX_PATTERN}\s*-?\d+(?:[.,]\d+)?%\s+{MARGIN_INSIGHT_CONTEXT_PATTERN}\.$'
    )
    PERCENTAGE_VALUE_PATTERN = r'-?\d+(?:[.,]\d+)?%'

    @classmethod
    def _resolve_test_password(cls, env_var_name: str, identity: str) -> str:
        """
        Resolve a stable test password.

        Priority:
        1) explicit environment variable value;
        2) deterministic value derived from the app secret key and identity.

        This keeps test credentials repeatable across runs (including with
        persistent databases) without hardcoding reusable plain-text passwords.
        """
        explicit = (os.getenv(env_var_name) or '').strip()
        if explicit:
            return explicit

        seed = str(app.config.get('SECRET_KEY', 'infinance-test-fallback-secret'))
        digest = hashlib.sha256(f'{seed}:{identity}'.encode('utf-8')).hexdigest()
        return f'TestAuth!{digest[:24]}'

    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True)
        bootstrap_database()
        cls.username = 'qa_auth_user'
        cls.password = cls._resolve_test_password('INFINANCE_TEST_USER_PASSWORD', cls.username)
        cls.admin_username = 'qa_auth_admin'
        cls.admin_password = cls._resolve_test_password('INFINANCE_TEST_ADMIN_PASSWORD', cls.admin_username)
        with app.app_context():
            existing = get_user_by_username(cls.username)
            if existing is None:
                execute(
                    cls.USER_INSERT_SQL,
                    (
                        cls.username,
                        generate_password_hash(cls.password),
                        'viewer',
                        datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    ),
                )
            else:
                execute(
                    cls.USER_UPDATE_SQL,
                    (generate_password_hash(cls.password), 'viewer', int(existing['id'])),
                )
            refreshed = get_user_by_username(cls.username)
            cls.user_id = int(refreshed['id'])

            admin_existing = get_user_by_username(cls.admin_username)
            if admin_existing is None:
                execute(
                    cls.USER_INSERT_SQL,
                    (
                        cls.admin_username,
                        generate_password_hash(cls.admin_password),
                        'admin',
                        datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    ),
                )
            else:
                execute(
                    cls.USER_UPDATE_SQL,
                    (generate_password_hash(cls.admin_password), 'admin', int(admin_existing['id'])),
                )

    def setUp(self):
        self.client = app.test_client()

    @contextlib.contextmanager
    def savepoint(self, db, name: str, rollback_on_success: bool = False):
        """
        Create a database savepoint and guarantee cleanup.

        The context ROLLBACKs when:
        1) an exception is raised inside the block, or
        2) `rollback_on_success` is True.

        The `finally` block always executes `RELEASE SAVEPOINT`.
        When rollback is needed, `ROLLBACK TO SAVEPOINT` runs before
        `RELEASE SAVEPOINT`.
        """
        safe_name = self._validate_savepoint_name(name)
        db.execute(self._build_savepoint_sql('SAVEPOINT', safe_name))
        should_rollback = rollback_on_success
        try:
            yield
        except Exception:
            should_rollback = True
            raise
        finally:
            if should_rollback:
                db.execute(self._build_savepoint_sql('ROLLBACK TO SAVEPOINT', safe_name))
            db.execute(self._build_savepoint_sql('RELEASE SAVEPOINT', safe_name))

    @staticmethod
    def _validate_savepoint_name(name: str) -> str:
        if not isinstance(name, str) or not name:
            raise ValueError('Savepoint name must be a non-empty string.')
        if re.fullmatch(r'[A-Za-z0-9_]+', name) is None:
            raise ValueError('Invalid savepoint name; only letters, digits, and underscores are allowed.')
        return name

    @staticmethod
    def _build_savepoint_sql(operation: str, name: str) -> str:
        """
        Build savepoint SQL from controlled inputs.

        Safety note: SQLite does not parameterize identifiers such as
        savepoint names. This helper remains safe because:
        - `operation` is restricted to an explicit allowlist;
        - `name` is validated by `_validate_savepoint_name` to only allow
          `[A-Za-z0-9_]+`.
        This method defensively validates `name` itself before interpolation.
        """
        allowed_operations = (
            'SAVEPOINT',
            'ROLLBACK TO SAVEPOINT',
            'RELEASE SAVEPOINT',
        )
        if operation not in allowed_operations:
            raise ValueError('Unsupported savepoint operation.')
        safe_name = AuthAndCalculationsTest._validate_savepoint_name(name)
        return f'{operation} {safe_name}'

    def _assert_results_equal(
        self,
        baseline_result: dict,
        compared_result: dict,
        compared_name: str,
        excluded_keys: set[str] | None = None,
    ) -> None:
        """
        Compare two result dictionaries used in DAS assertions.

        Keys listed in `excluded_keys` are ignored. For the remaining keys:
        - numeric values are compared with `assertAlmostEqual(...)` using
          `NUMERIC_COMPARISON_PRECISION`
        - non-numeric values are compared by type and exact equality.
        """
        ignored = excluded_keys if excluded_keys is not None else self.EXCLUDED_COMPARISON_KEYS
        for key, baseline_value in baseline_result.items():
            if key in ignored:
                continue
            self.assertIn(key, compared_result, msg=f"Missing key '{key}' in {compared_name}")
            compared_value = compared_result[key]
            if isinstance(baseline_value, (int, float)):
                self.assertIsInstance(
                    compared_value,
                    (int, float),
                    msg=f"Value for key '{key}' in {compared_name} is not numeric as expected",
                )
                self.assertAlmostEqual(
                    compared_value,
                    baseline_value,
                    places=self.NUMERIC_COMPARISON_PRECISION,
                )
            else:
                self.assertIsInstance(compared_value, type(baseline_value))
                self.assertEqual(
                    compared_value,
                    baseline_value,
                    msg=f"Value for key '{key}' in {compared_name} does not match baseline value",
                )

    def set_csrf_token(self, csrf_token: str | None = None) -> str:
        """
        Persist a CSRF token in the test client session.

        :param csrf_token: Optional token value to store in ``sess['_csrf_token']``.
            When omitted, a secure random token is generated for the test.
        :return: The same token value, to support concise test setup.
        """
        effective_token = csrf_token or secrets.token_urlsafe(32)
        with self.client.session_transaction() as sess:
            sess['_csrf_token'] = effective_token
        return effective_token

    def login_with_credentials(self, csrf_token: str, username: str, password: str, next_value: str | None = None):
        """
        Submit login credentials with a CSRF token.

        :param csrf_token: Token expected by the CSRF middleware.
        :param username: Username to authenticate.
        :param password: Plain-text password for the user.
        :param next_value: Optional post-login redirect target used by redirect tests.
        :return: Flask test client response for POST /login without following redirects.
        """
        payload = {
            '_csrf_token': csrf_token,
            'username': username,
            'password': password,
        }
        if next_value is not None:
            payload['next'] = next_value
        return self.client.post('/login', data=payload, follow_redirects=False)

    def login_with_valid_credentials(self, csrf_token: str):
        return self.login_with_credentials(csrf_token, self.username, self.password)

    def _assert_transaction_values_valid(
        self,
        result_dict: dict,
        require_finite_values: bool = False,
        context: str | None = None,
    ) -> None:
        """
        Internal helper for this test class.

        Validate transaction result values against NaN/finite invariants.

        :param result_dict: Output dictionary from `calculate_transaction`.
        :param require_finite_values: When True, each numeric value must be finite.
        :param context: Optional label prefixed to assertion messages to make
            failures easier to diagnose for each scenario.
        """
        msg_prefix = f'{context}: ' if context else ''
        for key in self.TRANSACTION_RESULT_KEYS:
            self.assertIn(key, result_dict, msg=f"{msg_prefix}missing key '{key}'")
            value = result_dict[key]
            self.assertFalse(isnan(value), msg=f'{msg_prefix}{key} should not be NaN')
            if require_finite_values:
                self.assertTrue(isfinite(value), msg=f'{msg_prefix}{key} should remain finite')

    def _count_clients_by_name(self, db, name: str) -> int:
        """
        Internal helper for this test class.

        Count client rows by exact name.

        :param db: Active SQLite connection used by tests.
        :param name: Client name to match in ``clients.name``.
        :return: Number of matching rows.
        """
        return int(db.execute('SELECT COUNT(*) FROM clients WHERE name = ?', (name,)).fetchone()[0])

    def _create_test_transaction_with_expense(
        self,
        db,
        month: str,
        now_iso: str,
        *,
        amount: float = 1000.0,
        expense_amount: float = 400.0,
    ) -> dict[str, Any]:
        """
        Internal helper to insert deterministic monthly-report fixture data.

        It creates one client, one service, one transaction and one expense
        for the provided month, then returns inserted identifiers/values.
        """
        client_cursor = db.execute(
            self.CLIENT_INSERT_SQL,
            ('Cliente Insights Janeiro', 'PJ', 'Cliente de teste para insights', now_iso),
        )
        service_cursor = db.execute(
            self.SERVICE_INSERT_SQL,
            (
                'Serviço Insights Janeiro',
                'operacional',
                0.10,
                '6319-4/00',
                'Serviço de teste para geração de insights',
                'III',
                1,
                'Template teste insights',
                now_iso,
            ),
        )
        client_id = int(client_cursor.lastrowid)
        service_id = int(service_cursor.lastrowid)

        db.execute(
            self.TRANSACTION_INSERT_SQL,
            (
                client_id,
                service_id,
                amount,
                'PJ',
                1,
                f'NF-INSIGHTS-{month}',
                'Transação de teste para insights',
                0.0,
                f'{month}-15',
                'recebido',
                'Teste determinístico',
                now_iso,
            ),
        )

        db.execute(
            self.EXPENSE_INSERT_SQL,
            (
                'Despesa de teste para insights',
                'marketing',
                expense_amount,
                f'{month}-20',
                0,
                'Teste determinístico',
                now_iso,
            ),
        )

        return {
            'client_id': client_id,
            'service_id': service_id,
            'amount': amount,
            'expense_amount': expense_amount,
        }

    def test_set_csrf_sets_session_token(self):
        csrf_token = secrets.token_urlsafe(24)
        returned = self.set_csrf_token(csrf_token)
        self.assertEqual(returned, csrf_token)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('_csrf_token'), csrf_token)

    def test_login_with_valid_credentials_helper(self):
        csrf_token = self.set_csrf_token()
        response = self.login_with_valid_credentials(csrf_token)
        self.assertEqual(response.status_code, 302)
        location = response.headers.get('Location', '')
        self.assertTrue(location.endswith('/') or location.endswith('/dashboard'))

    def test_login_success(self):
        csrf_token = self.set_csrf_token()
        login_response = self.login_with_valid_credentials(csrf_token)
        self.assertEqual(login_response.status_code, 302)
        location = login_response.headers.get('Location', '')
        self.assertTrue(location.endswith('/') or location.endswith('/dashboard'))

        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('user_id'), self.user_id)
            self.assertEqual(sess.get('username'), self.username)
            self.assertEqual(sess.get('role'), 'viewer')

    def test_login_admin_role(self):
        csrf_token = self.set_csrf_token()
        login_response = self.login_with_credentials(csrf_token, self.admin_username, self.admin_password)
        self.assertEqual(login_response.status_code, 302)
        location = login_response.headers.get('Location', '')
        self.assertTrue(location.endswith('/') or location.endswith('/dashboard'))

        with self.client.session_transaction() as sess:
            self.assertIsNotNone(sess.get('user_id'))
            self.assertEqual(sess.get('username'), self.admin_username)
            self.assertEqual(sess.get('role'), 'admin')

    def test_logout_flow(self):
        csrf_token = self.set_csrf_token()
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
        csrf_token = self.set_csrf_token()
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
        csrf_token = self.set_csrf_token()
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
        csrf_token = self.set_csrf_token()
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
        csrf_token = self.set_csrf_token()
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
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        response_text = response.data.decode('utf-8').casefold()
        self.assertIn(self.CSRF_EXPIRED_MESSAGE, response_text)

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

    def test_calculate_transaction_pj_with_invoice_ignores_expected_pf_tax(self):
        with_pf_tax_input = calculate_transaction(1000.0, 'PJ', True, 0.06, 999.0)
        without_pf_tax_input = calculate_transaction(1000.0, 'PJ', True, 0.06, 0.0)

        self.assertEqual(with_pf_tax_input['pf_tax'], 0.0)
        self.assertEqual(with_pf_tax_input['invoice_tax'], with_pf_tax_input['total_tax'])
        self.assertEqual(with_pf_tax_input, without_pf_tax_input)

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
        expected_invoice_tax = gross * invoice_rate
        # In this test scenario (PJ with invoice), PF tax is expected to be zero.
        expected_pf_tax = 0.0
        expected_total_tax = expected_invoice_tax + expected_pf_tax
        expected_net = gross - expected_total_tax
        expected_effective_rate = (expected_total_tax / gross) * 100

        self.assertEqual(result['gross'], gross)
        # `calculate_transaction` rounds monetary/tax values to cents.
        # `places=2` aligns assertions with this production behavior.
        self.assertAlmostEqual(result['invoice_tax'], expected_invoice_tax, places=2)
        self.assertAlmostEqual(result['pf_tax'], expected_pf_tax, places=2)
        self.assertAlmostEqual(result['total_tax'], expected_total_tax, places=2)
        self.assertAlmostEqual(result['net'], expected_net, places=2)
        self.assertAlmostEqual(result['effective_rate'], expected_effective_rate, places=2)

    def test_calculate_transaction_near_float_limits(self):
        near_float_max = sys.float_info.max / 10.0
        result = calculate_transaction(near_float_max, 'PJ', True, 0.5, 0.0)
        self.assertTrue(isfinite(result['gross']))
        self.assertTrue(isfinite(result['invoice_tax']))
        self.assertTrue(isfinite(result['total_tax']))
        self.assertTrue(isfinite(result['net']))
        self.assertTrue(isfinite(result['effective_rate']))
        self.assertGreater(result['gross'], 0.0)
        self.assertGreater(result['invoice_tax'], 0.0)
        self.assertEqual(result['total_tax'], result['invoice_tax'])
        self.assertGreaterEqual(result['effective_rate'], 0.0)
        self.assertLessEqual(result['effective_rate'], 100.0)

    def test_calculate_transaction_at_float_max_with_100_percent_rate(self):
        # Boundary case (not overflow): gross is float max and rate is exactly 1.0.
        # Expected behavior is deterministic because gross * 1.0 == gross in IEEE-754,
        # so all returned values should remain finite and consistent.
        result = calculate_transaction(sys.float_info.max, 'PJ', True, 1.0, 0.0)
        self._assert_transaction_values_valid(result, require_finite_values=True, context='float max boundary')
        tolerance = sys.float_info.max * self.FLOAT_MAX_RELATIVE_TOLERANCE
        self.assertAlmostEqual(result['gross'], sys.float_info.max, delta=tolerance)
        self.assertAlmostEqual(result['invoice_tax'], sys.float_info.max, delta=tolerance)
        self.assertEqual(result['pf_tax'], 0.0)
        self.assertAlmostEqual(result['total_tax'], sys.float_info.max, delta=tolerance)
        self.assertEqual(result['net'], 0.0)
        self.assertEqual(result['effective_rate'], 100.0)

    def test_calculate_transaction_overflow_multiplication(self):
        # Overflow-prone multiplication (gross * rate > float max).
        # Expected handling strategy:
        # - NaN must never be returned;
        # - +inf is acceptable for overflowed tax/rate fields;
        # - relational invariants (e.g., total_tax matches invoice_tax for PJ with invoice)
        #   must still hold.
        overflowing_gross = sys.float_info.max * 0.75
        overflow_result = calculate_transaction(overflowing_gross, 'PJ', True, 1.5, 0.0)
        self._assert_transaction_values_valid(overflow_result, context='overflow-prone multiplication')
        self.assertEqual(overflow_result['gross'], overflowing_gross)
        # For PJ with invoice, PF tax should remain zero and total tax should
        # match the invoice tax component.
        self.assertEqual(overflow_result['pf_tax'], 0.0)
        self.assertEqual(overflow_result['total_tax'], overflow_result['invoice_tax'])
        # Overflow strategy consistency:
        # - taxes remain non-negative and may become +inf;
        # - net stays <= gross (can become -inf when tax overflows);
        # - effective_rate remains non-negative (finite or +inf).
        self.assertTrue(isinf(overflow_result['invoice_tax']) or overflow_result['invoice_tax'] >= 0.0)
        self.assertTrue(isinf(overflow_result['total_tax']) or overflow_result['total_tax'] >= 0.0)
        self.assertLessEqual(overflow_result['net'], overflow_result['gross'])
        self.assertTrue(isinf(overflow_result['effective_rate']) or overflow_result['effective_rate'] >= 0.0)

    def test_calculate_transaction_at_float_max_boundary_realistic_rate(self):
        gross = sys.float_info.max
        invoice_rate = 0.2
        result = calculate_transaction(gross, 'PJ', True, invoice_rate, 0.0)

        self._assert_transaction_values_valid(
            result,
            require_finite_values=True,
            context='float max boundary (realistic rate)',
        )

        self.assertGreater(result['gross'], 0.0)
        self.assertGreater(result['invoice_tax'], 0.0)
        self.assertEqual(result['pf_tax'], 0.0)
        self.assertGreaterEqual(result['total_tax'], result['invoice_tax'])
        self.assertLessEqual(result['net'], result['gross'])
        self.assertGreaterEqual(result['effective_rate'], 0.0)
        self.assertLessEqual(result['effective_rate'], 100.0)

    def test_calculate_transaction_positive_gross_negative_tax_rate(self):
        result = calculate_transaction(1000.0, 'PJ', True, -0.1, 0.0)
        self.assertEqual(result['gross'], 1000.0)
        self.assertEqual(result['invoice_tax'], 0.0)
        self.assertEqual(result['pf_tax'], 0.0)
        self.assertEqual(result['total_tax'], 0.0)
        self.assertEqual(result['net'], 1000.0)
        self.assertEqual(result['effective_rate'], 0.0)

    def test_calculate_transaction_positive_gross_negative_fixed_tax(self):
        result = calculate_transaction(1000.0, 'PF', False, 0.15, -30.0)
        self.assertEqual(result['gross'], 1000.0)
        self.assertEqual(result['invoice_tax'], 0.0)
        self.assertEqual(result['pf_tax'], 0.0)
        self.assertEqual(result['total_tax'], 0.0)
        self.assertEqual(result['net'], 1000.0)
        self.assertEqual(result['effective_rate'], 0.0)

    def test_calculate_das_advanced_zero_revenue(self):
        result = calculate_das_advanced(5000.0, 0.0, 1000.0, 'III_V')
        error = result.get('error')
        self.assertIsNotNone(error)
        self.assertEqual(
            error,
            'Informe uma receita bruta acumulada dos últimos 12 meses (RBT12) maior que zero.',
        )

    def test_calculate_das_advanced_negative_revenue(self):
        result = calculate_das_advanced(5000.0, -1.0, 1000.0, 'III_V')
        error = result.get('error')
        self.assertIsNotNone(error)
        self.assertEqual(
            error,
            'Informe uma receita bruta acumulada dos últimos 12 meses (RBT12) maior que zero.',
        )

    def test_calculate_das_advanced_over_limit(self):
        result = calculate_das_advanced(5000.0, 4_900_000.0, 100_000.0, 'III_V')
        error = result.get('error')
        self.assertIsNotNone(error)
        self.assertEqual(
            error,
            'RBT12 acima de R$ 4.800.000,00. O cálculo simplificado aqui não cobre esse regime.',
        )

    def test_calculate_das_advanced_high_factor(self):
        high_payroll_factor_result = calculate_das_advanced(10_000.0, 200_000.0, 60_000.0, 'III_V')
        self.assertIsNone(high_payroll_factor_result.get('error'))
        self.assertEqual(high_payroll_factor_result['annex'], 'III')
        self.assertTrue(high_payroll_factor_result['uses_factor_r'])

    def test_calculate_das_advanced_low_factor(self):
        low_payroll_factor_result = calculate_das_advanced(10_000.0, 200_000.0, 20_000.0, 'III_V')
        self.assertIsNone(low_payroll_factor_result.get('error'))
        self.assertEqual(low_payroll_factor_result['annex'], 'V')
        self.assertTrue(low_payroll_factor_result['uses_factor_r'])

    def test_calculate_das_advanced_forced_annex(self):
        baseline_annex_ii_result = calculate_das_advanced(10_000.0, 200_000.0, 20_000.0, 'II')
        self.assertIsNone(baseline_annex_ii_result.get('error'))
        self.assertEqual(baseline_annex_ii_result['annex'], 'II')

        forced_annex_result = calculate_das_advanced(10_000.0, 200_000.0, 20_000.0, 'III_V', forced_annex='II')
        self.assertIsNone(forced_annex_result.get('error'))
        self.assertEqual(forced_annex_result['annex'], 'II')
        self.assertFalse(forced_annex_result['uses_factor_r'])
        self._assert_results_equal(
            baseline_annex_ii_result,
            forced_annex_result,
            'forced_annex_result',
            excluded_keys=self.EXCLUDED_COMPARISON_KEYS | {'annex_mode'},
        )

    def test_calculate_das_advanced_forced_same_annex_as_natural(self):
        natural_result = calculate_das_advanced(10_000.0, 200_000.0, 20_000.0, 'III_V')
        self.assertIsNone(natural_result.get('error'))
        self.assertEqual(natural_result['annex'], 'V')

        forced_same_annex_result = calculate_das_advanced(
            10_000.0,
            200_000.0,
            20_000.0,
            'III_V',
            forced_annex='V',
        )
        self.assertIsNone(forced_same_annex_result.get('error'))
        self.assertEqual(forced_same_annex_result['annex'], 'V')
        self._assert_results_equal(
            natural_result,
            forced_same_annex_result,
            'forced_same_annex_result',
        )

    def test_calculate_das_advanced_forced_annex_other_valid_options(self):
        natural_result = calculate_das_advanced(10_000.0, 200_000.0, 20_000.0, 'III_V')
        self.assertIsNone(natural_result.get('error'))
        self.assertEqual(natural_result['annex'], 'V')

        for forced_annex in ('I', 'III', 'IV'):
            with self.subTest(forced_annex=forced_annex):
                result = calculate_das_advanced(10_000.0, 200_000.0, 20_000.0, 'III_V', forced_annex=forced_annex)
                self.assertIsNone(result.get('error'))
                self.assertEqual(result.get('annex'), forced_annex)
                self.assertNotEqual(result.get('annex'), natural_result.get('annex'))
                self.assertIn('effective_rate', result)
                self.assertIn('estimated_das', result)

    def test_calculate_das_advanced_invalid_forced_annex(self):
        for forced_annex in self.INVALID_FORCED_ANNEX_VALUES:
            with self.subTest(forced_annex=forced_annex):
                result = calculate_das_advanced(10_000.0, 200_000.0, 20_000.0, 'III_V', forced_annex=forced_annex)
                self.assertIsNotNone(result.get('error'))
                self.assertEqual(result.get('error'), self.INVALID_FORCED_ANNEX_ERROR_MESSAGE)
                # Invalid forced annex must short-circuit and avoid calculation payload fields.
                for key in self.CALCULATION_RESULT_KEYS:
                    self.assertNotIn(key, result)

    def test_calculate_das_advanced_none_forced_annex_is_allowed(self):
        result = calculate_das_advanced(10_000.0, 200_000.0, 20_000.0, 'III_V', forced_annex=None)
        self.assertIsNone(result.get('error'))

    def test_calculate_das_advanced_invalid_forced_annex_does_not_corrupt_valid_flow(self):
        monthly_revenue = 12_345.67
        rbt12 = 300_000.0
        payroll_12m = 90_000.0
        annex_mode = 'III_V'

        baseline_valid_result = calculate_das_advanced(
            monthly_revenue,
            rbt12,
            payroll_12m,
            annex_mode,
            forced_annex=None,
        )
        self.assertIsNone(baseline_valid_result.get('error'))
        self.assertIn('estimated_das', baseline_valid_result)
        self.assertIn('effective_rate', baseline_valid_result)

        invalid_result = calculate_das_advanced(
            monthly_revenue,
            rbt12,
            payroll_12m,
            annex_mode,
            forced_annex='INVALID',
        )
        self.assertEqual(invalid_result.get('error'), self.INVALID_FORCED_ANNEX_ERROR_MESSAGE)
        for key in self.CALCULATION_RESULT_KEYS:
            self.assertNotIn(key, invalid_result)

        rerun_valid_result = calculate_das_advanced(
            monthly_revenue,
            rbt12,
            payroll_12m,
            annex_mode,
            forced_annex=None,
        )
        self.assertIsNone(rerun_valid_result.get('error'))
        self._assert_results_equal(
            baseline_valid_result,
            rerun_valid_result,
            'rerun_valid_result',
        )
        self.assertEqual(rerun_valid_result.get('error'), baseline_valid_result.get('error'))
        self.assertEqual(rerun_valid_result.get('annex'), baseline_valid_result.get('annex'))
        self.assertEqual(rerun_valid_result.get('uses_factor_r'), baseline_valid_result.get('uses_factor_r'))

    def test_calculate_das_advanced_accepts_all_valid_forced_annex_values(self):
        for forced_annex in self.VALID_FORCED_ANNEX_VALUES:
            with self.subTest(forced_annex=forced_annex):
                result = calculate_das_advanced(10_000.0, 200_000.0, 20_000.0, 'III_V', forced_annex=forced_annex)
                self.assertIsNone(result.get('error'))
                self.assertEqual(result.get('annex'), forced_annex)
                self.assertIn('effective_rate', result)
                self.assertIn('estimated_das', result)

    def test_build_monthly_report_data_includes_insights(self):
        with app.app_context():
            db = get_db()
            with self.savepoint(db, 'monthly_insights_test', rollback_on_success=True):
                now_dt = datetime.now(timezone.utc)
                month = now_dt.strftime(self.MONTH_FORMAT)
                now = now_dt.isoformat(timespec='seconds')
                self._create_test_transaction_with_expense(db, month, now)

                data = build_monthly_report_data(month)
        self.assertEqual(data.get('month'), month)
        self.assertIn('insights', data)
        self.assertIsInstance(data['insights'], list)
        insights = data['insights']

        for insight in insights:
            self.assertIsInstance(insight, str)
            self.assertNotEqual(insight.strip(), '')

        gross = data['income_totals']['gross_total']
        expense_total = data['expense_total']
        net = data['income_totals']['net_total']
        self.assertIsInstance(gross, (int, float))
        self.assertIsInstance(expense_total, (int, float))
        self.assertIsInstance(net, (int, float))
        self.assertGreater(gross, 0.0)
        self.assertGreater(expense_total, 0.0)
        self.assertGreater(net, 0.0)
        self.assertGreaterEqual(len(insights), 3)

        first_insight = insights[0]
        self.assertRegex(first_insight, self.MARGIN_INSIGHT_PATTERN)
        margin_match = re.search(r'(-?\d+(?:[.,]\d+)?)%', first_insight)
        self.assertIsNotNone(margin_match)
        reported_margin = float(margin_match.group(1).replace(',', '.'))
        expected_margin = ((net - expense_total) / gross) * 100 if gross > 0 else 0.0
        self.assertAlmostEqual(reported_margin, expected_margin, places=2)

        second_insight = insights[1]
        self.assertTrue(second_insight.startswith('Maior categoria de despesas: '))
        self.assertIn(' em R$ ', second_insight)

        third_insight = insights[2]
        self.assertTrue(third_insight.startswith('Pressão tributária estimada: '))
        self.assertRegex(third_insight, self.PERCENTAGE_VALUE_PATTERN)
        self.assertIn('receita bruta', third_insight)

    def test_savepoint_context_manager_rollback(self):
        with app.app_context():
            db = get_db()
            test_client_identifier = f'Cliente_Savepoint_Rollback_{uuid.uuid4()}'
            pre_existing = self._count_clients_by_name(db, test_client_identifier)
            self.assertEqual(pre_existing, 0)

            did_raise = False
            try:
                with self.savepoint(db, 'monthly_insights_rollback_test'):
                    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
                    db.execute(
                        self.CLIENT_INSERT_SQL,
                        (test_client_identifier, 'PJ', 'Cliente temporário para testar rollback de savepoint', now),
                    )
                    in_savepoint_count = self._count_clients_by_name(db, test_client_identifier)
                    self.assertEqual(in_savepoint_count, 1)
                    raise RuntimeError('force rollback scenario')
            except RuntimeError:
                did_raise = True

            self.assertTrue(did_raise)

            post_rollback_count = self._count_clients_by_name(db, test_client_identifier)
            self.assertEqual(post_rollback_count, 0)

    def test_savepoint_context_manager_commit(self):
        with app.app_context():
            db = get_db()
            test_client_identifier = f'Cliente_Savepoint_Commit_{uuid.uuid4()}'
            with self.savepoint(db, 'savepoint_commit_cleanup', rollback_on_success=True):
                pre_existing = self._count_clients_by_name(db, test_client_identifier)
                self.assertEqual(pre_existing, 0)

                with self.savepoint(db, 'monthly_insights_commit_test'):
                    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
                    db.execute(
                        self.CLIENT_INSERT_SQL,
                        (test_client_identifier, 'PJ', 'Cliente temporário para testar commit de savepoint', now),
                    )
                    in_savepoint_count = self._count_clients_by_name(db, test_client_identifier)
                    self.assertEqual(in_savepoint_count, 1)

                post_commit_count = self._count_clients_by_name(db, test_client_identifier)
                self.assertEqual(post_commit_count, 1)


if __name__ == '__main__':
    unittest.main()
