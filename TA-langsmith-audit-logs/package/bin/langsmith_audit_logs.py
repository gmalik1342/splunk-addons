"""Modular input entry point: LangSmith audit logs (sourcetype langsmith:audit)."""

import import_declare_test  # noqa: F401  (UCC-generated: puts ../lib on sys.path)

from langsmith_audit.modinput import run

if __name__ == "__main__":
    run()
