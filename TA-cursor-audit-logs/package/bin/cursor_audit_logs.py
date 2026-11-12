"""Modular input entry point: Cursor audit logs (sourcetype cursor:audit)."""

import import_declare_test  # noqa: F401  (UCC-generated: puts ../lib on sys.path)

from cursor_audit.modinput import run

if __name__ == "__main__":
    run()
