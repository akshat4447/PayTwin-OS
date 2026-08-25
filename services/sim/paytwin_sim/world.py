"""Merchant world configuration — mirrors the prototype's Nova Commerce org."""
from __future__ import annotations

METHODS = {
    "upi_intent": {"w": 0.34, "sr": 0.955},
    "upi_collect": {"w": 0.16, "sr": 0.935},
    "card": {"w": 0.28, "sr": 0.965},
    "netbanking": {"w": 0.12, "sr": 0.945},
    "mandate": {"w": 0.10, "sr": 0.925},
}

ISSUERS = {
    "HDFC": {"w": 0.26, "sr": 0.985},
    "ICICI": {"w": 0.22, "sr": 0.98},
    "SBI": {"w": 0.20, "sr": 0.97},
    "AXIS": {"w": 0.17, "sr": 0.975},
    "KOTAK": {"w": 0.15, "sr": 0.97},
}

PSPS = {
    "cashfree": {"w": 0.30, "sr": 0.98},
    "razorpay": {"w": 0.40, "sr": 0.985},
    "payu": {"w": 0.30, "sr": 0.975},
}

GATEWAYS = ["gw1", "gw2"]

# hour-of-day traffic profile (IST-ish double-peak)
HOD = [0.25, 0.18, 0.12, 0.10, 0.10, 0.14, 0.26, 0.45, 0.70, 0.90, 1.05, 1.15,
       1.20, 1.10, 1.05, 1.10, 1.20, 1.35, 1.50, 1.55, 1.40, 1.05, 0.70, 0.42]

MERCHANTS = {
    "mgro": {"name": "Nova Grocery", "short": "NG", "color": "#2fd48e", "industry": "grocery",
             "tpm": 26.0, "aov_paise": 84_000, "sr_base": 0.956, "autonomy": 3, "stage": 5},
    "mfash": {"name": "Nova Fashion", "short": "NF", "color": "#9a6bff", "industry": "fashion",
              "tpm": 17.0, "aov_paise": 199_000, "sr_base": 0.968, "autonomy": 2, "stage": 4},
    "mtrav": {"name": "Nova Travel", "short": "NT", "color": "#3ec6d0", "industry": "travel",
              "tpm": 36.0, "aov_paise": 415_000, "sr_base": 0.974, "autonomy": 3, "stage": 5},
    "msubs": {"name": "Nova Subscriptions", "short": "NS", "color": "#ffb454", "industry": "subscriptions",
              "tpm": 8.0, "aov_paise": 39_900, "sr_base": 0.939, "autonomy": 1, "stage": 3},
}

FAILURE_CLASSES = ["issuer_decline", "timeout", "auth", "insufficient_funds", "psp_error"]


def pick(rng, table):
    """Weighted pick from {'w': ...} tables using a numpy Generator."""
    keys = list(table)
    weights = [table[k]["w"] for k in keys]
    return keys[int(rng.choice(len(keys), p=normalize(weights)))]


def normalize(ws):
    s = sum(ws)
    return [w / s for w in ws]
