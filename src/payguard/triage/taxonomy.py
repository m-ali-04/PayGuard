"""The triage vocabulary: routing categories, urgency levels and review flags.

DEFINITIONS is the single source of the wording: the labelling guide is generated from it and the
LLM prompt uses it, so human labels and model output are judged against the same definitions.
"""
from enum import StrEnum


class Category(StrEnum):
    FRAUD_SCAMS = "fraud_scams"
    CREDIT_REPORTING = "credit_reporting"
    DEBT_COLLECTION = "debt_collection"
    BANKING_PAYMENTS = "banking_payments"
    CREDIT_CARDS = "credit_cards"
    LENDING = "lending"
    OTHER = "other"


class Urgency(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Flag(StrEnum):
    FRAUD_ALLEGATION = "fraud_allegation"
    LEGAL_THREAT = "legal_threat"
    VULNERABLE_CUSTOMER = "vulnerable_customer"
    SAFETY_RISK = "safety_risk"
    DISCRIMINATION = "discrimination"


CATEGORY_RULES = (
    "Route by where the complaint should be handled, judged from the text. Apply in order: "
    "fraud or unauthorised activity goes to fraud_scams whatever the product; otherwise wrong or "
    "improper credit-report information goes to credit_reporting whatever the company; otherwise "
    "route by product. Use other only when the text is unclear, spans several areas equally, or fits none."
)

URGENCY_RULES = (
    "Urgency follows the harm described: what kind it is and whether it is ongoing, imminent or past. "
    "Time cues in the text (\"the sale is next week\", \"frozen for three weeks\") can raise urgency. "
    "Missing or redacted time (XXXX, XX/XX/XXXX) never lowers it."
)

DEFINITIONS: dict[StrEnum, str] = {
    Category.FRAUD_SCAMS: "Scams, unauthorised transactions, identity theft, account takeover or accounts "
                          "opened in the consumer's name, on any product.",
    Category.CREDIT_REPORTING: "Wrong or improper information on a credit report, or disputes and investigations "
                               "about it, from any company.",
    Category.DEBT_COLLECTION: "How a debt is being collected: validation, debts not owed, collection letters, "
                              "calls, threats or false statements by a collector.",
    Category.BANKING_PAYMENTS: "Checking and savings accounts, account fees, opening or closing accounts, money "
                               "transfers, mobile wallets and prepaid cards.",
    Category.CREDIT_CARDS: "Credit card billing, purchase disputes, interest and fees, card features, getting "
                           "or closing a card.",
    Category.LENDING: "Mortgages, vehicle, student, payday and personal loans: applying, servicing, payment "
                      "trouble, repossession, foreclosure, payoff.",
    Category.OTHER: "Unclear, spanning several areas equally, or outside every other category.",
    Urgency.HIGH: "Harm happening now or imminent: money being lost to fraud, no access to funds, a scheduled "
                  "foreclosure, repossession or eviction, legal action against the consumer with a deadline, "
                  "or any safety risk.",
    Urgency.MEDIUM: "Real financial harm that is not imminent: wrong fees or charges, a wrong credit report "
                    "affecting applications, ongoing collection attempts.",
    Urgency.LOW: "Service or information problems, delays, poor communication, or harm already resolved.",
    Flag.FRAUD_ALLEGATION: "The consumer says money or identity was taken through deception or without consent "
                           "(scam, unauthorised transaction, identity theft, account takeover). A dispute about "
                           "a debt's amount or calling a fee a ripoff is not fraud.",
    Flag.LEGAL_THREAT: "The consumer threatens or describes legal action or representation: suing, an attorney, "
                       "small claims, a lawsuit. Citing a law (\"under the FDCPA\") is not a legal threat.",
    Flag.VULNERABLE_CUSTOMER: "The text describes circumstances that make the consumer especially exposed to "
                              "harm: older age, disability, serious illness, bereavement or severe financial "
                              "hardship.",
    Flag.SAFETY_RISK: "Risk to someone's physical safety or wellbeing: self-harm or suicide, threats of violence, "
                      "domestic or financial abuse by a partner or family member. A rude or persistent collector "
                      "is not a safety risk.",
    Flag.DISCRIMINATION: "The consumer alleges unfair treatment because of a protected characteristic: race, "
                         "colour, religion, national origin, sex, age, disability, marital status or receiving "
                         "public assistance. Calling something discrimination without one is not enough.",
}

# Weak reference label from CFPB's own fields, in the same rule order as CATEGORY_RULES. CFPB's
# product follows the company more than the text, so this checks broad agreement only.
FRAUD_ISSUES = {"Fraud or scam", "Unauthorized transactions or other transaction problem"}
CREDIT_REPORT_ISSUES = {"Incorrect information on your report", "Improper use of your report"}
PRODUCT_CATEGORY = {
    "Credit reporting or other personal consumer reports": Category.CREDIT_REPORTING,
    "Credit reporting, credit repair services, or other personal consumer reports": Category.CREDIT_REPORTING,
    "Debt collection": Category.DEBT_COLLECTION,
    "Checking or savings account": Category.BANKING_PAYMENTS,
    "Money transfer, virtual currency, or money service": Category.BANKING_PAYMENTS,
    "Prepaid card": Category.BANKING_PAYMENTS,
    "Credit card": Category.CREDIT_CARDS,
    "Mortgage": Category.LENDING,
    "Vehicle loan or lease": Category.LENDING,
    "Student loan": Category.LENDING,
    "Payday loan, title loan, personal loan, or advance loan": Category.LENDING,
    "Debt or credit management": Category.OTHER,
}


def reference_category(product: str, issue: str) -> Category:
    if issue in FRAUD_ISSUES:
        return Category.FRAUD_SCAMS
    if issue in CREDIT_REPORT_ISSUES:
        return Category.CREDIT_REPORTING
    return PRODUCT_CATEGORY.get(product, Category.OTHER)
