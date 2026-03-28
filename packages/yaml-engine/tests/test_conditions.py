"""Parametrized tests for built-in condition operators."""

import re

import pytest

from yaml_engine.conditions import evaluate_condition


# --- eq ---

@pytest.mark.parametrize("value, param, expected", [
    ("Klar", "klar", True),
    ("KLAR", "Klar", True),
    ("Nu", "Klar", False),
    (None, "Klar", False),
    (42, 42, True),
    (42, 43, False),
])
def test_eq(value, param, expected):
    assert evaluate_condition("eq", value, param) == expected


# --- neq ---

@pytest.mark.parametrize("value, param, expected", [
    ("Klar", "klar", False),
    ("Nu", "Klar", True),
    (None, "Klar", True),
])
def test_neq(value, param, expected):
    assert evaluate_condition("neq", value, param) == expected


# --- contains ---

@pytest.mark.parametrize("value, param, expected", [
    ("WALMART COMPRA", "walmart", True),
    ("walmart compra", "WALMART", True),
    ("OXXO GAS", "oxxo", True),
    ("STARBUCKS", "walmart", False),
    (None, "walmart", False),
])
def test_contains(value, param, expected):
    assert evaluate_condition("contains", value, param) == expected


# --- in / in_set ---

@pytest.mark.parametrize("op", ["in", "in_set"])
@pytest.mark.parametrize("value, param, expected", [
    ("charge", frozenset({"charge", "withdrawal", "fee"}), True),
    ("payment", frozenset({"charge", "withdrawal", "fee"}), False),
    (None, frozenset({"charge"}), False),
    ("CHARGE", frozenset({"charge"}), True),
])
def test_in(op, value, param, expected):
    assert evaluate_condition(op, value, param) == expected


# --- all_present ---

@pytest.mark.parametrize("value, param, expected", [
    ("Cuenta Priority BANAMEX", ["CUENTA PRIORITY"], True),
    ("Cuenta Priority", ["CUENTA PRIORITY", "BANAMEX"], False),
    ("CUENTA NU:", ["CUENTA NU:"], True),
    (None, ["CUENTA NU:"], False),
])
def test_all_present(value, param, expected):
    assert evaluate_condition("all_present", value, param) == expected


# --- has_fragment ---

@pytest.mark.parametrize("value, param, expected", [
    ("RICARDO OCAMPO VEGA", ["RICARDO", "JOSE"], True),
    ("JOSE GARCIA", ["RICARDO", "OCAMPO"], False),
    ("ocampo garcia", ["OCAMPO"], True),
    (None, ["RICARDO"], False),
])
def test_has_fragment(value, param, expected):
    assert evaluate_condition("has_fragment", value, param) == expected


# --- matches ---

@pytest.mark.parametrize("value, param, expected", [
    ("SPEI TRANSFERENCIA", re.compile(r"SPEI.*", re.IGNORECASE), True),
    ("PAGO NORMAL", re.compile(r"SPEI.*", re.IGNORECASE), False),
    ("REST AURANTE", re.compile(r"REST\s", re.IGNORECASE), True),
    ("RESTAURANTE", re.compile(r"REST\s", re.IGNORECASE), False),
    (None, re.compile(r"SPEI"), False),
])
def test_matches(value, param, expected):
    assert evaluate_condition("matches", value, param) == expected


# --- gt / lt ---

@pytest.mark.parametrize("value, param, expected", [
    (100.0, 0, True),
    (-50.0, 0, False),
    (0.0, 0, False),
    (None, 0, False),
])
def test_gt(value, param, expected):
    assert evaluate_condition("gt", value, param) == expected


@pytest.mark.parametrize("value, param, expected", [
    (-50.0, 0, True),
    (100.0, 0, False),
    (0.0, 0, False),
    (None, 0, False),
])
def test_lt(value, param, expected):
    assert evaluate_condition("lt", value, param) == expected


# --- is_null / not_null ---

@pytest.mark.parametrize("value, expected", [
    (None, True),
    ("something", False),
    (0, False),
    ("", False),
])
def test_is_null(value, expected):
    assert evaluate_condition("is_null", value, None) == expected


@pytest.mark.parametrize("value, expected", [
    (None, False),
    ("something", True),
    (0, True),
])
def test_not_null(value, expected):
    assert evaluate_condition("not_null", value, None) == expected


# --- is_truthy ---

@pytest.mark.parametrize("value, expected", [
    (True, True),
    (1, True),
    ("yes", True),
    (False, False),
    (0, False),
    (None, False),
    ("", False),
])
def test_is_truthy(value, expected):
    assert evaluate_condition("is_truthy", value, None) == expected


# --- unknown operator ---

def test_unknown_operator_raises():
    with pytest.raises(ValueError, match="Unknown condition operator"):
        evaluate_condition("nonexistent_op", "value", None)
