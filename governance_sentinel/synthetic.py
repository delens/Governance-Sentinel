"""Seeded synthetic risk transactions with documented data-quality defects.

The default run builds 4,000 rows, inside the 1,000 to 10,000 band used for a
full audit. Smaller frames are supported so the committed sample and the unit
tests stay light. Every defect count is ``round(rate * n)`` under the given
seed, so a rerun writes the same file.

The protected attribute ``age_category`` is a demo label for the fairness
audit. 1 means the unprivileged group ("40_and_over") and 2 means the
privileged group ("under_40"). Those labels are not a legal age classification.

Target approval rates, applied before the few null labels:

- privileged (2): 0.78
- unprivileged (1): 0.54

The expected disparate-impact ratio is about 0.54 / 0.78 = 0.69, below the
US EEOC four-fifths figure of 0.80. That figure is a heuristic in this
project. It is not a threshold in the EU AI Act.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_SEED = 239
DEFAULT_ROWS = 4_000
SAMPLE_ROWS = 150
REPORTING_DATE = "2026-09-30"
MIN_ROWS = 30
MAX_ROWS = 20_000

# Target share of rows. Counts are round(rate * n), so they are exact when
# rate * n is an integer (the default 4,000-row run).
DEFECT_RATES: dict[str, float] = {
    "missing_transaction_id": 0.010,
    "duplicate_transaction_id": 0.004,
    "null_exposure": 0.015,
    "negative_exposure": 0.010,
    "outlier_exposure": 0.008,
    "invalid_currency": 0.012,
    "null_currency": 0.004,
    "orphan_counterparty": 0.020,
    "null_counterparty": 0.005,
    "late_availability": 0.030,
    "unparseable_availability": 0.003,
    "invalid_rating": 0.010,
    "null_rating": 0.008,
    "null_age_category": 0.004,
    "null_loan_approved": 0.002,
}

PRIVILEGED_APPROVAL_RATE = 0.78
UNPRIVILEGED_APPROVAL_RATE = 0.54
UNKNOWN_GROUP_APPROVAL_RATE = 0.65

EXPOSURE_LOG_MEAN = 11.0
EXPOSURE_LOG_SIGMA = 0.40
# Clip inside the theoretical 1.5-IQR fence on the original scale. The fence of a
# lognormal sits near exp(mu + 0.67*sigma) plus 1.5 times that IQR, which is
# below exp(mu + 2*sigma). One sigma keeps every body point inside the fence
# while leaving the quartiles (0.67 sigma) untouched.
EXPOSURE_CLIP_SIGMA = 1.0
# Above the interquartile fence (about 1.3e5 for this distribution) and small
# enough that one spike does not hide a 250,000 reconciliation break inside
# a 0.1 percent tolerance on the entity total.
OUTLIER_EXPOSURE = 500_000.0
NEGATIVE_EXPOSURE = -1_500.0
LATE_BUSINESS_DAYS = 4

CURRENCIES: tuple[str, ...] = ("EUR", "USD", "GBP", "CHF", "JPY")
INVALID_CURRENCY = "XYZ"
RATINGS: tuple[str, ...] = ("AAA", "AA", "A", "BBB", "BB", "B", "CCC", "D", "NR")
INVALID_RATING = "BAD"
PRODUCTS: tuple[str, ...] = ("LOAN", "DERIVATIVE", "SECURITY", "GUARANTEE")

# Fictional legal entities. source_system is the booking application that feeds
# the landed transaction file. It is technical lineage, not a second dataset.
LEGAL_ENTITIES: tuple[tuple[str, str, str], ...] = (
    ("LE-FR", "Lumiere Banque SA", "CBS_FR"),
    ("LE-DE", "Nordhafen Bank AG", "CBS_DE"),
    ("LE-UK", "Thames Retail plc", "CBS_UK"),
    ("LE-US", "Harbor National NA", "CBS_US"),
    ("LE-SG", "Straits Markets Pte Ltd", "MUREX_SG"),
    ("LE-CH", "Alpine Custody AG", "CBS_CH"),
)

# Fictional counterparties. The reference file is this list. Orphan ids are
# minted at generation time and are not added here.
_COUNTERPARTY_ROWS: tuple[tuple[str, str, str, str], ...] = (
    ("Northwind Metals", "SA", "FR", "Manufacturing"),
    ("Helvetia Grain", "AG", "CH", "Agriculture"),
    ("Blueharbor Shipping", "Ltd", "UK", "Transport"),
    ("Cinder Rail", "NV", "NL", "Transport"),
    ("Lumen Grid", "GmbH", "DE", "Utilities"),
    ("Sable Chemicals", "SA", "FR", "Manufacturing"),
    ("Redkite Aviation", "Ltd", "UK", "Transport"),
    ("Marrow Steel", "AG", "CH", "Manufacturing"),
    ("Pebble Telecom", "Pte Ltd", "SG", "Telecom"),
    ("Orchard Foods", "SA", "FR", "Consumer"),
    ("Quartz Mining", "Ltd", "UK", "Mining"),
    ("Fjord Timber", "AS", "NO", "Manufacturing"),
    ("Cedar Housing", "AG", "DE", "Real estate"),
    ("Ivy Payments", "Ltd", "UK", "Financial"),
    ("Maple Health", "Inc", "US", "Healthcare"),
    ("Juniper Energy", "Inc", "US", "Energy"),
    ("Coral Ports", "SA", "ES", "Transport"),
    ("Brass Instruments", "GmbH", "DE", "Manufacturing"),
    ("Silverline Retail", "plc", "UK", "Consumer"),
    ("Harbor Mills", "Inc", "US", "Manufacturing"),
    ("Dune Solar", "SA", "ES", "Energy"),
    ("Aster Insurance", "AG", "CH", "Financial"),
    ("Kite Logistics", "BV", "NL", "Transport"),
    ("Nimbus Software", "Pte Ltd", "SG", "Technology"),
    ("Copperline Cable", "SA", "FR", "Telecom"),
    ("Willow Paper", "AB", "SE", "Manufacturing"),
    ("Granite Works", "Ltd", "UK", "Construction"),
    ("Poppy Pharma", "AG", "CH", "Healthcare"),
    ("Elm Water", "GmbH", "DE", "Utilities"),
    ("Sparrow Airlines", "Ltd", "IE", "Transport"),
    ("Boreal Fish", "AS", "NO", "Agriculture"),
    ("Topaz Hotels", "SA", "FR", "Consumer"),
    ("Rivet Auto", "AG", "DE", "Manufacturing"),
    ("Lantern Media", "Ltd", "UK", "Consumer"),
    ("Moss Cement", "SpA", "IT", "Construction"),
    ("Peak Alloys", "Inc", "US", "Manufacturing"),
    ("Yarrow Textiles", "SA", "PT", "Manufacturing"),
    ("Flint Glass", "GmbH", "DE", "Manufacturing"),
    ("Oakland Stores", "Inc", "US", "Consumer"),
    ("Vesper Leasing", "Ltd", "UK", "Financial"),
)

TRANSACTION_COLUMNS: tuple[str, ...] = (
    "record_id",
    "transaction_id",
    "legal_entity_id",
    "legal_entity_name",
    "source_system",
    "counterparty_id",
    "product_type",
    "currency",
    "exposure_amount",
    "internal_rating",
    "reporting_date",
    "availability_date",
    "age_category",
    "age_band",
    "loan_approved",
)

AGE_BAND = {1: "40_and_over", 2: "under_40"}


@dataclass(frozen=True)
class DefectManifest:
    """Which rows carry each injected defect.

    ``record_ids`` lists the rows that were edited. For duplicates, the list is
    the rows whose identifier was overwritten. The donor rows are in
    ``duplicate_donors``: a uniqueness check fails both sides.
    """

    seed: int
    row_count: int
    rates: dict[str, float]
    counts: dict[str, int]
    record_ids: dict[str, tuple[str, ...]]
    duplicate_donors: tuple[str, ...]

    @property
    def duplicate_failing_ids(self) -> tuple[str, ...]:
        """Rows that share a transaction id after the duplicate injection."""
        overwritten = set(self.record_ids["duplicate_transaction_id"])
        return tuple(sorted(overwritten | set(self.duplicate_donors)))


def defect_count(row_count: int, rate: float) -> int:
    """Return the integer count injected for ``rate`` on a frame of this size."""
    return int(round(rate * row_count))


def counterparty_reference() -> pd.DataFrame:
    """Return the counterparty master the referential check joins to."""
    rows = [
        {
            "counterparty_id": f"CP-{index:03d}",
            "counterparty_name": f"{stem} {suffix}",
            "country": country,
            "sector": sector,
        }
        for index, (stem, suffix, country, sector) in enumerate(_COUNTERPARTY_ROWS, start=1)
    ]
    return pd.DataFrame(rows)


def generate_risk_dataset(
    n: int = DEFAULT_ROWS,
    seed: int = DEFAULT_SEED,
    defect_rates: Mapping[str, float] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, DefectManifest]:
    """Build transactions, the counterparty master, and the defect manifest.

    ``defect_rates`` replaces individual entries of ``DEFECT_RATES``. Omitted
    names keep the documented rate. The default audit does not pass this
    argument.

    Raises:
        ValueError: ``n`` is outside the supported range, or a rate name is unknown.
    """
    if n < MIN_ROWS or n > MAX_ROWS:
        raise ValueError(f"n must be between {MIN_ROWS} and {MAX_ROWS}. Got {n}.")

    rates = _resolve_rates(defect_rates)
    rng = np.random.default_rng(seed)
    reference = counterparty_reference()
    counts = {name: defect_count(n, rate) for name, rate in rates.items()}

    pairs = [(entity[0], currency) for entity in LEGAL_ENTITIES for currency in CURRENCIES]
    pair_slots = np.arange(n) % len(pairs)
    pair_slots = pair_slots[rng.permutation(n)]

    entity_ids = np.empty(n, dtype=object)
    entity_names = np.empty(n, dtype=object)
    source_systems = np.empty(n, dtype=object)
    currencies = np.empty(n, dtype=object)
    entity_by_id = {item[0]: item for item in LEGAL_ENTITIES}
    for index, slot in enumerate(pair_slots):
        entity_id, currency = pairs[int(slot)]
        _entity_id, entity_name, source_system = entity_by_id[entity_id]
        entity_ids[index] = entity_id
        entity_names[index] = entity_name
        source_systems[index] = source_system
        currencies[index] = currency

    products = rng.choice(list(PRODUCTS), size=n)
    ratings = rng.choice(list(RATINGS), size=n)
    counterparty_ids = rng.choice(reference["counterparty_id"].to_numpy(), size=n)

    low = math.exp(EXPOSURE_LOG_MEAN - EXPOSURE_CLIP_SIGMA * EXPOSURE_LOG_SIGMA)
    high = math.exp(EXPOSURE_LOG_MEAN + EXPOSURE_CLIP_SIGMA * EXPOSURE_LOG_SIGMA)
    exposures = np.clip(rng.lognormal(EXPOSURE_LOG_MEAN, EXPOSURE_LOG_SIGMA, size=n), low, high)
    exposures = np.round(exposures, 2)

    reporting = np.full(n, np.datetime64(REPORTING_DATE))
    availability = np.busday_offset(reporting, rng.integers(0, 2, size=n))

    age = rng.integers(1, 3, size=n)
    approval_probability = np.where(
        age == 2,
        PRIVILEGED_APPROVAL_RATE,
        UNPRIVILEGED_APPROVAL_RATE,
    )
    loan = (rng.random(n) < approval_probability).astype(int)

    blocked: set[int] = set()
    chosen: dict[str, np.ndarray] = {}

    def take(name: str, group_blocked: set[int]) -> np.ndarray:
        picked = _choose(rng, n, counts[name], group_blocked)
        group_blocked.update(int(item) for item in picked)
        chosen[name] = picked
        return picked

    transaction_block: set[int] = set()
    missing_txn = take("missing_transaction_id", transaction_block)
    duplicate_rows = take("duplicate_transaction_id", transaction_block)
    duplicate_donors = _choose(rng, n, counts["duplicate_transaction_id"], transaction_block)
    transaction_block.update(int(item) for item in duplicate_donors)

    exposure_block: set[int] = set()
    null_exposure = take("null_exposure", exposure_block)
    negative_exposure = take("negative_exposure", exposure_block)
    outlier_exposure = take("outlier_exposure", exposure_block)

    currency_block: set[int] = set()
    invalid_currency = take("invalid_currency", currency_block)
    null_currency = take("null_currency", currency_block)

    counterparty_block: set[int] = set()
    orphan_counterparty = take("orphan_counterparty", counterparty_block)
    null_counterparty = take("null_counterparty", counterparty_block)

    availability_block: set[int] = set()
    late_availability = take("late_availability", availability_block)
    unparseable_availability = take("unparseable_availability", availability_block)

    rating_block: set[int] = set()
    invalid_rating = take("invalid_rating", rating_block)
    null_rating = take("null_rating", rating_block)

    null_age = take("null_age_category", blocked)
    null_loan = take("null_loan_approved", blocked)

    record_ids = np.array([f"R{index + 1:06d}" for index in range(n)], dtype=object)
    transaction_ids = np.array([f"TX-{index + 1:06d}" for index in range(n)], dtype=object)
    transaction_ids[missing_txn] = None
    for row, donor in zip(duplicate_rows, duplicate_donors, strict=True):
        transaction_ids[int(row)] = transaction_ids[int(donor)]

    exposure_values = exposures.astype(object)
    exposure_values[null_exposure] = None
    exposure_values[negative_exposure] = NEGATIVE_EXPOSURE
    exposure_values[outlier_exposure] = OUTLIER_EXPOSURE

    currencies[invalid_currency] = INVALID_CURRENCY
    currencies[null_currency] = None

    counterparty_ids = counterparty_ids.astype(object)
    for ordinal, row in enumerate(orphan_counterparty, start=1):
        counterparty_ids[int(row)] = f"CP-ORPHAN-{ordinal:04d}"
    counterparty_ids[null_counterparty] = None

    availability_text = np.array(
        [pd.Timestamp(value).strftime("%Y-%m-%d") for value in availability],
        dtype=object,
    )
    late_dates = np.busday_offset(reporting[late_availability], LATE_BUSINESS_DAYS)
    for row, late in zip(late_availability, late_dates, strict=True):
        availability_text[int(row)] = pd.Timestamp(late).strftime("%Y-%m-%d")
    availability_text[unparseable_availability] = "not-a-date"

    ratings = ratings.astype(object)
    ratings[invalid_rating] = INVALID_RATING
    ratings[null_rating] = None

    age_values = age.astype(object)
    age_values[null_age] = None
    age_band = np.array(
        [None if value is None else AGE_BAND[int(value)] for value in age_values],
        dtype=object,
    )
    loan_values = loan.astype(object)
    loan_values[null_loan] = None

    frame = pd.DataFrame(
        {
            "record_id": record_ids,
            "transaction_id": transaction_ids,
            "legal_entity_id": entity_ids,
            "legal_entity_name": entity_names,
            "source_system": source_systems,
            "counterparty_id": counterparty_ids,
            "product_type": products,
            "currency": currencies,
            "exposure_amount": exposure_values,
            "internal_rating": ratings,
            "reporting_date": REPORTING_DATE,
            "availability_date": availability_text,
            "age_category": age_values,
            "age_band": age_band,
            "loan_approved": loan_values,
        }
    )
    frame = frame.loc[:, list(TRANSACTION_COLUMNS)]

    def ids_for(indexes: np.ndarray) -> tuple[str, ...]:
        return tuple(str(record_ids[int(item)]) for item in indexes)

    manifest = DefectManifest(
        seed=seed,
        row_count=n,
        rates=rates,
        counts=counts,
        record_ids={name: ids_for(indexes) for name, indexes in chosen.items()},
        duplicate_donors=ids_for(duplicate_donors),
    )
    return frame, reference, manifest


def write_risk_dataset(
    transactions_path: str | Path,
    counterparties_path: str | Path,
    n: int = DEFAULT_ROWS,
    seed: int = DEFAULT_SEED,
    defect_rates: Mapping[str, float] | None = None,
) -> DefectManifest:
    """Generate the dataset and write both CSV files. Returns the manifest."""
    frame, reference, manifest = generate_risk_dataset(
        n=n,
        seed=seed,
        defect_rates=defect_rates,
    )
    transactions = Path(transactions_path)
    counterparties = Path(counterparties_path)
    transactions.parent.mkdir(parents=True, exist_ok=True)
    counterparties.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(transactions, index=False)
    reference.to_csv(counterparties, index=False)
    return manifest


def _resolve_rates(override: Mapping[str, float] | None) -> dict[str, float]:
    """Return the defect rates for one extract. Unknown names are rejected."""
    if override is None:
        return dict(DEFECT_RATES)
    unknown = sorted(set(override) - set(DEFECT_RATES))
    if unknown:
        raise ValueError(f"Unknown defect rates: {unknown}.")
    rates = dict(DEFECT_RATES)
    for name, rate in override.items():
        if rate < 0:
            raise ValueError(f"Defect rate {name} must be zero or positive. Got {rate}.")
        rates[name] = float(rate)
    return rates


def _choose(rng: np.random.Generator, n: int, count: int, blocked: set[int]) -> np.ndarray:
    if count == 0:
        return np.array([], dtype=int)
    pool = np.array([index for index in range(n) if index not in blocked], dtype=int)
    if count > pool.size:
        raise ValueError(f"Cannot place {count} defects into {pool.size} remaining rows.")
    return np.sort(rng.choice(pool, size=count, replace=False))
