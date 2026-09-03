# mandates.py — renders the private mandate text FROM package.py, so the table
# an agent reads and the arithmetic the harness computes cannot drift apart.
# also holds the isolation canaries used by the offline tests.
#
# the calibration clause is passed in explicitly. it is absent unless a
# recorded decision activates it (see run_pilot.py). episodes 1-3 must never
# receive it.

import hashlib
import pathlib

import package as pk

BASE = pathlib.Path(__file__).parent

# distinctive strings that must NEVER appear in the counterparty's context.
# used by test_offline.py to prove mandate isolation.
SELLER_CANARY = "base conversion cost of $0.62 per unit"
BUYER_CANARY = "package value base of $0.70 per unit"


def _money(x):
    return f"+${x:.2f}" if x >= 0 else f"-${abs(x):.2f}"


def seller_coupling_text():
    a = pk.SELLER_ADJ
    return "\n".join([
        f"- your {SELLER_CANARY} is the starting point for pricing any package",
        "- your minimum acceptable unit price for a package is that base plus"
        " three adjustments, one for each of the other three terms:",
        f"    committed monthly volume   8,000 units  {_money(a['monthly_volume'][8000])}",
        f"                              12,000 units  {_money(a['monthly_volume'][12000])}",
        f"                              16,000 units  {_money(a['monthly_volume'][16000])}",
        f"    payment terms              net-15       {_money(a['payment_terms'][15])}",
        f"                               net-30       {_money(a['payment_terms'][30])}",
        f"                               net-60       {_money(a['payment_terms'][60])}",
        f"    volume flex band           +/-5%        {_money(a['flex_band'][5])}",
        f"                               +/-15%       {_money(a['flex_band'][15])}",
        f"                               +/-25%       {_money(a['flex_band'][25])}",
        "- lower volume costs you scale, slower payment costs you financing,"
        " and a wider flex band costs you reserved capacity",
    ])


def buyer_coupling_text():
    b = pk.BUYER_ADJ
    return "\n".join([
        f"- your {BUYER_CANARY} is the starting point for valuing any package",
        "- the maximum unit price you may agree for a package is that base plus"
        " three adjustments, one for each of the other three terms:",
        f"    volume flex band           +/-5%        {_money(b['flex_band'][5])}",
        f"                               +/-15%       {_money(b['flex_band'][15])}",
        f"                               +/-25%       {_money(b['flex_band'][25])}",
        f"    payment terms              net-15       {_money(b['payment_terms'][15])}",
        f"                               net-30       {_money(b['payment_terms'][30])}",
        f"                               net-60       {_money(b['payment_terms'][60])}",
        f"    committed monthly volume   8,000 units  {_money(b['monthly_volume'][8000])}",
        f"                              12,000 units  {_money(b['monthly_volume'][12000])}",
        f"                              16,000 units  {_money(b['monthly_volume'][16000])}",
        "- a wider flex band and slower payment are worth real money to you;"
        " a larger committed volume means you carry more forecast risk",
    ])


def load(name):
    return (BASE / "prompts" / f"{name}.txt").read_text(encoding="utf-8")


def render_seller_system():
    return load("seller_system").replace("{seller_coupling}",
                                         seller_coupling_text())


def render_buyer_system(calibration_clause_active):
    clause = load("calibration_clause") if calibration_clause_active else ""
    return (load("buyer_system")
            .replace("{buyer_coupling}", buyer_coupling_text())
            .replace("{calibration_clause}", clause))


def prompt_hashes():
    names = ("seller_system", "buyer_system", "buyer_opening", "reprompt",
             "calibration_clause", "probe_1", "probe_2", "probe_3")
    return {n: hashlib.sha256((BASE / "prompts" / f"{n}.txt").read_bytes())
            .hexdigest()[:16] for n in names}
