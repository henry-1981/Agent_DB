"""Tests for traceability context helper."""

from context import get_parent, get_children, get_siblings, get_context


def test_get_parent_returns_parent():
    parent = get_parent("kmdia-fc-art7-p1-item1")
    assert parent == "kmdia-fc-art7-p1-main"


def test_get_children_returns_list():
    children = get_children("kmdia-fc-art7-p1-main")
    assert isinstance(children, list)
    assert len(children) == 6
    assert "kmdia-fc-art7-p1-item1" in children


def test_get_siblings_excludes_self():
    siblings = get_siblings("kmdia-fc-art7-p1-item1")
    assert "kmdia-fc-art7-p1-item1" not in siblings
    assert len(siblings) == 5  # 6 total children - 1 self


def test_get_context_includes_hierarchy_type():
    ctx = get_context("kmdia-fc-art7-p1-item1")
    assert "hierarchy_type" in ctx
    # Existing traceability files have no hierarchy_type, so it should be None
    assert ctx["hierarchy_type"] is None
