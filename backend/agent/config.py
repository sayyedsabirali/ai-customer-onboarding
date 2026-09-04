"""
Central configuration for document requirements per customer type.
Single source of truth — add a new customer type or document here,
nowhere else in the codebase needs to change.
"""

DOCUMENT_REQUIREMENTS = {
    "individual": ["pan_card", "address_proof"],
    "startup": ["pan_card", "address_proof", "company_registration"],
    "enterprise": ["pan_card", "address_proof", "company_registration", "gst_certificate"],
}

DOCUMENT_DISPLAY_NAMES = {
    "pan_card": "PAN Card",
    "address_proof": "Address Proof",
    "company_registration": "Company Registration Certificate",
    "gst_certificate": "GST Certificate",
    "id_proof": "ID Proof",
}


DOCUMENT_ALIASES = {
    "pan_card": [
        "pan", "pancard", "pan_card", "pan card", "pan-card", "pan doc", "pan document", "pan number",
        "tax_id", "tax id", "tax", "taxid", "tin"
    ],
    "address_proof": [
        "address", "addressproof", "address_proof", "address proof", "address-proof",
        "aadhaar", "aadhar", "aadhaar card", "aadhar card", "passport", "voter id",
        "voter_id", "voter", "driving license", "dl", "utility bill", "electricity bill"
    ],
    "company_registration": [
        "company", "company registration", "company_registration", "company-registration",
        "company registration certificate", "incorporation", "certificate of incorporation",
        "coi", "business registration", "business_reg", "business reg", "company_reg", "cin"
    ],
    "gst_certificate": [
        "gst", "gstin", "gst certificate", "gst_certificate", "gst-certificate",
        "gst doc", "gst document"
    ],
    "id_proof": [
        "id", "id proof", "id_proof", "id-proof", "idproof", "identity proof"
    ]
}


def get_required_documents(customer_type: str) -> list[str]:
    """Returns the ordered list of required document types for a customer type."""
    return DOCUMENT_REQUIREMENTS.get(customer_type, DOCUMENT_REQUIREMENTS["individual"])


def get_display_name(doc_type: str) -> str:
    """Human-readable name for a document type; falls back to the raw key."""
    return DOCUMENT_DISPLAY_NAMES.get(doc_type, doc_type)


def normalize_document_type(doc_type: str):
    """
    Intelligently maps user input variations to standard document_type keys.
    Supports: 'Address Proof', 'address proof', 'aadhaar', 'PAN Card', 'pan', 'gst', etc.
    """
    if not doc_type:
        return None
    cleaned = doc_type.strip().lower()
    clean_snake = cleaned.replace("-", "_").replace(" ", "_")
    if clean_snake in DOCUMENT_DISPLAY_NAMES:
        return clean_snake
    clean_spaces = cleaned.replace("-", " ").replace("_", " ")
    for key, display_name in DOCUMENT_DISPLAY_NAMES.items():
        if clean_spaces == display_name.lower():
            return key
    for key, aliases in DOCUMENT_ALIASES.items():
        if clean_spaces in aliases or clean_snake in aliases:
            return key
    return None


def is_valid_document_type(doc_type: str) -> bool:
    return normalize_document_type(doc_type) is not None


# SLA hours per customer tier
SLA_HOURS_BY_CUSTOMER_TYPE = {
    "individual": 24,
    "startup": 48,
    "enterprise": 72
}


def get_sla_hours(customer_type: str) -> int:
    """Returns SLA in hours based on customer tier; default is 24."""
    if not customer_type:
        return 24
    return SLA_HOURS_BY_CUSTOMER_TYPE.get(customer_type.lower().strip(), 24)