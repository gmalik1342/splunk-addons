"""Modular input entry point: NetApp Cloud Secure alerts (sourcetype netapp:cloud_secure:alerts)."""

import import_declare_test  # noqa: F401  (UCC-generated: puts ../lib on sys.path)

from cloud_secure.modinput import run

if __name__ == "__main__":
    run()
