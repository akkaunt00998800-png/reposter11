from __future__ import annotations


class EsimCliError(RuntimeError):
    """Base error for user-facing failures."""


class NotFoundError(EsimCliError):
    """Resource not found."""


class InvalidStateError(EsimCliError):
    """Invalid application state."""


class ActivationCodeError(EsimCliError):
    """Activation code is invalid or already used (one-time use violation)."""

