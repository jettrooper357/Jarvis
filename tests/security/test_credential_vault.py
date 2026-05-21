"""Unit tests for CredentialVault.

The vault stores raw secrets under opaque tokens scoped to a run_id.
Resolution only succeeds when the caller presents the same run_id;
this prevents a leaked token from one run from dereferencing under
another's scope.
"""

from __future__ import annotations

import pytest

from openjarvis.security.credential_vault import CredentialVault


def test_store_returns_token_that_resolves_back_to_value():
    v = CredentialVault()
    token = v.store("run-1", "sk-secret-12345")
    assert token is not None
    assert token != "sk-secret-12345"
    assert token.startswith("[[credential:")
    assert v.resolve(f"please use {token} now", "run-1") == (
        "please use sk-secret-12345 now"
    )


def test_resolve_rejects_wrong_run_id():
    """A token from one run cannot dereference under another run's scope."""
    v = CredentialVault()
    token = v.store("run-1", "sk-secret-12345")
    out = v.resolve(f"call X with {token}", "run-2")
    # Token is left in place, value never substituted.
    assert "sk-secret-12345" not in out
    assert token in out


def test_purge_removes_value():
    v = CredentialVault()
    token = v.store("run-1", "sk-secret-12345")
    v.purge("run-1")
    out = v.resolve(f"using {token}", "run-1")
    assert "sk-secret-12345" not in out
    assert list(v.active_runs()) == []


def test_store_rejects_empty_value():
    v = CredentialVault()
    assert v.store("run-1", "") is None
    assert v.store("run-1", None) is None
    assert v.store(None, "value") is None
    assert v.store("", "value") is None


def test_resolve_passes_through_text_without_tokens():
    v = CredentialVault()
    v.store("run-1", "anything")
    text = "no tokens here, just normal text"
    assert v.resolve(text, "run-1") == text


def test_multiple_secrets_per_run():
    v = CredentialVault()
    t1 = v.store("run-1", "secret-one-aaaaaa")
    t2 = v.store("run-1", "secret-two-bbbbbb")
    assert t1 != t2
    text = f"{t1} and {t2}"
    assert v.resolve(text, "run-1") == "secret-one-aaaaaa and secret-two-bbbbbb"


def test_purge_one_run_does_not_affect_another():
    v = CredentialVault()
    t1 = v.store("run-1", "value-one")
    t2 = v.store("run-2", "value-two")
    v.purge("run-1")
    assert "value-two" in v.resolve(f"x {t2}", "run-2")
    assert "value-one" not in v.resolve(f"x {t1}", "run-1")
