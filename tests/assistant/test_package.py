from __future__ import annotations


def test_assistant_package_imports():
    import openjarvis.assistant as a

    assert a.__doc__ is not None
