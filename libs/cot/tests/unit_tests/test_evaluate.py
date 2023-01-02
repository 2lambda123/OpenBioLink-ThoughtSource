from typing import Iterator

import datasets
import pytest
from cot import Collection

# import os
# from pathlib import Path
from cot.generate import Correct_output

from cot.evaluate import clean, is_correct

from .utils import chdir, get_test_collection, simple_config


def test_clean():
    type_ = "multiplechoice"
    number_of_choices = 7

    assert clean(type_, "E", number_of_choices) == "E"
    assert clean(type_, "E.", number_of_choices) == "E"
    assert clean(type_, "E ", number_of_choices) == "E"
    assert clean(type_, "(E)", number_of_choices) == "E"
    assert clean(type_, "[E]", number_of_choices) == "E"

    assert clean(type_, "So the answer is B", number_of_choices) == "B"
    assert clean(type_, "So the answer is B.", number_of_choices) == "B"
    assert clean(type_, "So the answer isB", number_of_choices) == "B"
    assert clean(type_, "Therefore, the answer is B", number_of_choices) == "B"
    assert clean(type_, "The answer is B", number_of_choices) == "B"
    assert clean(type_, "Answer is B", number_of_choices) == "B"
    assert clean(type_, "Answer B", number_of_choices) == "B"
    assert clean(type_, "The correct answer is B", number_of_choices) == "B"
    assert clean(type_, "The correct answer B", number_of_choices) == "B"
    assert clean(type_, "Correct answer is B", number_of_choices) == "B"
    assert clean(type_, "Correct answer B", number_of_choices) == "B"
    assert clean(type_, "Among A through F, the answer is B", number_of_choices) == "B"
    assert (
        clean(type_, "Among A through F, the correct answer is B", number_of_choices)
        == "B"
    )
    assert (
        clean(type_, "Therefore, among A through F, the answer is B", number_of_choices)
        == "B"
    )

    assert clean(type_, "B is the answer.", number_of_choices) == "B"
    assert clean(type_, "B is the answer", number_of_choices) == "B"
    assert clean(type_, "B is the correct answer", number_of_choices) == "B"
    assert clean(type_, "B is the correct answer.", number_of_choices) == "B"
    assert clean(type_, "B is the right answer", number_of_choices) == "B"
    assert clean(type_, "B is the right answer.", number_of_choices) == "B"

    assert clean(type_, "B is correct", number_of_choices) == "B"
    assert clean(type_, "B is correct.", number_of_choices) == "B"
    assert clean(type_, "B is right", number_of_choices) == "B"
    assert clean(type_, "B is right.", number_of_choices) == "B"


def test_clean_and_is_correct():
    # test upper and lower case

    type_ = "multiplechoice"
    number_of_choices = 7

    pred = clean(type_, r"{e}", number_of_choices)
    assert is_correct(type_, pred, "E")

    pred = clean(type_, "e", number_of_choices)
    assert is_correct(type_, pred, "E")

    pred = clean(type_, "So the answer is (b)", number_of_choices)
    assert is_correct(type_, pred, "B")

    pred = clean(type_, "b is the answer", number_of_choices)
    assert is_correct(type_, pred, "B")

    pred = clean(type_, "(b) is the answer", number_of_choices)
    assert is_correct(type_, pred, "B")

    pred = clean(type_, "So the answer is b", number_of_choices)
    assert is_correct(type_, pred, "B")

    pred = clean(type_, "So the answer isb", number_of_choices)
    assert is_correct(type_, pred, "B")
