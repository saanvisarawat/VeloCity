"""
Manually-curated snapshot of PUBLIC, city-wide Delhi vehicle-registration
statistics, for display alongside (never mixed into) this platform's own
live ANPR numbers.

This is NOT a live feed and does not call Parivahan/Vahan at request time —
that portal is a session-based JSF application not meant for programmatic
scraping. Instead, this snapshot is taken directly from the Government of
NCT of Delhi's own published "Economic Survey of Delhi 2025-26" (Transport
chapter, Statement 12.11/12.12), the same kind of aggregate report the Vahan
public dashboard itself is built from. No per-vehicle or per-owner data is
involved anywhere — only a handful of city-wide totals.

Source: https://delhiplanning.delhi.gov.in/sites/default/files/2026-03/economic_survey_english_0.pdf
(Planning Department, Govt. of NCT of Delhi — "Economic Survey of Delhi 2025-26")

Update this dict by hand when a newer Economic Survey of Delhi is published
(typically annually, around the Delhi Budget session in March).
"""

DELHI_VEHICLE_REFERENCE_STATS = {
    "total_registered_vehicles": 8_761_919,
    "yoy_increase": 643_625,
    "yoy_growth_pct": 7.93,
    "vehicles_per_1000_population": 522,
    "two_wheelers": 5_927_775,
    "two_wheeler_pct": 68,
    "cars_and_jeeps_pct": 24,
    "cumulative_deregistered_due_to_age_ban": 6_620_160,
    "as_of": "19 March 2026 (FY 2025-26)",
    "source": "Economic Survey of Delhi 2025-26, Planning Department, Govt. of NCT of Delhi",
    "source_url": "https://delhiplanning.delhi.gov.in/sites/default/files/2026-03/economic_survey_english_0.pdf",
}

def get_delhi_vehicle_reference_stats():
    return DELHI_VEHICLE_REFERENCE_STATS

"""
Separate historical dataset — deliberately NOT merged with the snapshot above.

Source: "Delhi Total Number of Vehicles 2015-16 to 2024-25", published via
portal.delhi.gov.in and hosted on OpenCity (Oorvani Foundation):
https://data.opencity.in/dataset/delhi-vehicle-registrations-data

Its FY2024-25 total (84,13,644 "vehicles plying") does NOT match the Economic
Survey's FY2024-25 figure (81,18,294) above — a ~3.5% gap, most likely from
different snapshot dates / "plying" vs "on-road" methodology. Rather than
splice the two into one continuous series (which would imply false precision),
this is kept as its own dataset with its own citation.

The sharp drop between 2020-21 and 2021-22 in this data lines up with the
age-based deregistration drive (diesel >10yr / petrol >15yr) referenced in
the Economic Survey — not a data error.
"""

DELHI_VEHICLE_FLEET_TREND_SOURCE = {
    "name": "Delhi Total Number of Vehicles, 2015-16 to 2024-25 (portal.delhi.gov.in, via OpenCity)",
    "url": "https://data.opencity.in/dataset/delhi-vehicle-registrations-data",
}

DELHI_VEHICLE_FLEET_TREND = [
    {"fiscal_year": "2015-16", "cars_and_jeeps": 2986579, "motorcycles_scooters": 6104070, "auto_rickshaws": 198137, "taxis": 91073, "buses": 34365, "e_rickshaws_other": 6368, "ambulances": 2990, "tractors_goods_others": 281159, "total_vehicles_plying": 9704741},
    {"fiscal_year": "2016-17", "cars_and_jeeps": 3152710, "motorcycles_scooters": 6607879, "auto_rickshaws": 105399, "taxis": 118308, "buses": 35206, "e_rickshaws_other": 59759, "ambulances": 3059, "tractors_goods_others": 300437, "total_vehicles_plying": 10382757},
    {"fiscal_year": "2017-18", "cars_and_jeeps": 3246637, "motorcycles_scooters": 7078428, "auto_rickshaws": 113074, "taxis": 118060, "buses": 35285, "e_rickshaws_other": 76231, "ambulances": 3220, "tractors_goods_others": 315080, "total_vehicles_plying": 10986015},
    {"fiscal_year": "2018-19", "cars_and_jeeps": 3249670, "motorcycles_scooters": 7556002, "auto_rickshaws": 113240, "taxis": 109780, "buses": 32218, "e_rickshaws_other": 81422, "ambulances": 2358, "tractors_goods_others": 246861, "total_vehicles_plying": 11391551},
    {"fiscal_year": "2019-20", "cars_and_jeeps": 3311579, "motorcycles_scooters": 7959753, "auto_rickshaws": 114891, "taxis": 122476, "buses": 33302, "e_rickshaws_other": 85477, "ambulances": 2287, "tractors_goods_others": 263112, "total_vehicles_plying": 11892877},
    {"fiscal_year": "2020-21", "cars_and_jeeps": 3384736, "motorcycles_scooters": 8239550, "auto_rickshaws": 114869, "taxis": 112401, "buses": 33294, "e_rickshaws_other": 91887, "ambulances": 2289, "tractors_goods_others": 274324, "total_vehicles_plying": 12253350},
    {"fiscal_year": "2021-22", "cars_and_jeeps": 2057657, "motorcycles_scooters": 5135821, "auto_rickshaws": 92149, "taxis": 85079, "buses": 17282, "e_rickshaws_other": 104534, "ambulances": 1131, "tractors_goods_others": 245716, "total_vehicles_plying": 7739369},
    {"fiscal_year": "2022-23", "cars_and_jeeps": 2071115, "motorcycles_scooters": 5294900, "auto_rickshaws": 93654, "taxis": 83278, "buses": 17232, "e_rickshaws_other": 118506, "ambulances": 1172, "tractors_goods_others": 265739, "total_vehicles_plying": 7945596},
    {"fiscal_year": "2023-24", "cars_and_jeeps": 2083905, "motorcycles_scooters": 5467895, "auto_rickshaws": 94072, "taxis": 85981, "buses": 17621, "e_rickshaws_other": 137385, "ambulances": 1173, "tractors_goods_others": 282167, "total_vehicles_plying": 8170199},
    {"fiscal_year": "2024-25", "cars_and_jeeps": 2088805, "motorcycles_scooters": 5659930, "auto_rickshaws": 94731, "taxis": 84632, "buses": 17613, "e_rickshaws_other": 173457, "ambulances": 1136, "tractors_goods_others": 293340, "total_vehicles_plying": 8413644},
]




