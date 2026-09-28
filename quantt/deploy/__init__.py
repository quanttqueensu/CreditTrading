"""Deployment of the Alpaca runner onto the prod machine (docs/RUNBOOK.md).

Holds the launchd templates and `install_prod`, the installer for the prod clone.
Nothing in this package stores, reads or copies a credential; the installer only
checks that the key file it is told about exists and is private.
"""
