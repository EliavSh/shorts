__version__ = "0.1.0"

# Use the OS native trust store so HTTPS works behind corporate TLS-inspecting
# proxies (where system root CAs are trusted but Python's bundled certifi isn't).
# Safe no-op on machines without such a proxy.
try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass
