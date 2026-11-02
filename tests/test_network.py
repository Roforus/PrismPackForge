import ssl
import unittest

from packforge.network import https_context


class TlsTests(unittest.TestCase):
    def test_tls_requires_trusted_certificate_and_matching_hostname(self):
        context = https_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
