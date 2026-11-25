import pandas as pd
import pytest

from get_complaints import DEST
from payguard.triage.taxonomy import (DEFINITIONS, PRODUCT_CATEGORY, Category, Flag, Urgency,
                                      reference_category)


@pytest.mark.parametrize("product, issue, expected", [
    ("Credit card", "Fraud or scam", Category.FRAUD_SCAMS),  # fraud wins over product
    ("Mortgage", "Incorrect information on your report", Category.CREDIT_REPORTING),  # report content next
    ("Credit card", "Fees or interest", Category.CREDIT_CARDS),
    ("A product CFPB adds later", "Anything", Category.OTHER),
])
def test_reference_category_follows_rule_order(product, issue, expected):
    assert reference_category(product, issue) == expected


def test_every_slice_product_is_mapped_on_purpose():
    products = set(pd.read_csv(DEST, dtype=str)["Product"])
    assert products <= PRODUCT_CATEGORY.keys()


def test_every_term_has_a_definition():
    assert set(DEFINITIONS) == {*Category, *Urgency, *Flag}
