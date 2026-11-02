"""Verified TLS using the native certificate store plus bundled public roots."""
import ssl

import certifi
import truststore


def https_context():
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=certifi.where())
    return context


def configure_application_tls():
    # Application entry points only, before requests/urllib3 are imported.
    truststore.inject_into_ssl()
