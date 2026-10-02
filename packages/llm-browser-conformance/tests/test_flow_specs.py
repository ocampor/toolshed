"""Fixture flows the suite ships still validate the way the library promises."""

import pytest
from llm_browser.flows import load_flow_text
from pydantic import ValidationError

from llm_browser_conformance.scenario import FLOWS_DIR


def test_an_unknown_extract_key_fails_validation() -> None:
    text = (FLOWS_DIR / "typed-read.yaml").read_text()
    load_flow_text(text)
    stray = text.replace("required: true }", "required: true, colour: red }")

    with pytest.raises(ValidationError, match="colour"):
        load_flow_text(stray)
