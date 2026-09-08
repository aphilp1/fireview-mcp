#!/usr/bin/env python3
"""
Reference table of NWS/NWS-operated radiosonde (weather balloon) launch sites,
for finding the nearest upper-air station to a fire location and fetching its
twice-daily sounding via:

    https://forecast.weather.gov/product.php?site={SITE}&issuedby={SITE}
        &product=MAN&format=TXT&version={N}&glossary=0

`site` in each row below is EXACTLY the 3-letter identifier that goes in that
URL -- not the WMO number, not an ICAO code. TFX (Great Falls, MT) and OTX
(Spokane, WA) are the two stations this project had already validated live
before this table was built; both are reproduced here unchanged (72776 /
47.4614,-111.3847 and 72786 / 47.6806,-117.6266) and match the sourced data
to 4 decimal places.

BUILD DATE / SOURCES (2026-08-09)
----------------------------------
- NCAR/RAP surface+upper-air station list (Arnaud Dumont, last updated
  2022-05-08): https://weather.rap.ucar.edu/surface/stations.txt
  -- primary source for `site` candidates, state, elevation, and most WMO
  numbers. NOTE: this file's 3-letter "site" column is NOT globally unique
  (e.g. "OAX" collides with Oaxaca, Mexico) -- every value pulled from it was
  cross-checked against the ICAO column and country="US" before use.
- NOAA/NCEI IGRA2 station list (2026-08-09 pull):
  https://ncei.noaa.gov/pub/data/igra/igra2-station-list.txt
  -- independent decimal lat/lon + WMO cross-check, matched to RAP rows by
  WMO number embedded in the 11-char IGRA2 station id. This is what produced
  the higher-precision lat/lon on most rows (source "IGRA2+RAP" during the
  build). Also the only source used for Guam and Pago Pago, which aren't in
  the RAP file at all.
- NWS "Upper Air Sounding Data" page: https://www.weather.gov/upperair/sounding
  -- used to derive the set of currently-displayed CONUS/AK/HI station codes
  (rap.ucar.edu image links keyed by ICAO). This is what caught that several
  stations use their co-located WFO's 3-letter id as the working `site`
  value rather than the airport/ICAO-derived one -- e.g. Albany is ALY not
  ALB, Pittsburgh is PBZ not PIT, Nashville is OHX not BNA, Key West is KEY
  not EYW. Two real active stations (Denver/DNR, Chatham MA/CHH) turned up
  in the RAP list but were NOT on this NWS page at the time of this pull.
- LIVE VALIDATION: every `site` value below was actually tried against the
  real forecast.weather.gov MAN-product URL on 2026-08-09 (the exact
  mechanism above, not a proxy). A response containing a
  `class="glossaryProduct"` block with sounding text = confirmed. Rows where
  every code I could source (including the co-located WFO id, where one
  exists) came back HTTP 400 or an empty product are marked
  "UNCONFIRMED LIVE FETCH" in an inline comment, with a NOTE explaining what
  was tried. Do not assume those will work without checking again.

KNOWN GAP -- READ BEFORE RELYING ON THIS FOR ALASKA OR HAWAII FIRES
--------------------------------------------------------------------
This table has 87 of the ~92 stations NWS documents (69 CONUS + 13 AK + 2 HI
+ 3 Pacific/Caribbean territories: Guam, Pago Pago AS, San Juan PR). That is
short of the full network in two ways that matter operationally, not just
as a coverage gap:

1. ALL 13 Alaska site codes and BOTH Hawaii site codes (ADQ, AKN, ANC, ANN,
   BET, BRW, CDB, FAI, MCG, OME, OTZ, SNP, YAK, ITO, LIH) returned HTTP 400
   from forecast.weather.gov during this session -- including their
   co-located WFO ids (AFC, AFG, AJK, HFO), which came back HTTP 200 but
   with no MAN product. That's a different failure mode than "wrong code":
   ADQ/ANC/etc. weren't recognized as valid `site` params at all, whereas a
   genuinely-wrong-but-syntactically-valid code (like BNA or PIT) returns
   200 with an empty product. This suggests Alaska/Hawaii upper-air text
   products may not be distributed through forecast.weather.gov/product.php
   under these identifiers at all, or use a scheme not discovered here.
   TFX/OTX (the two previously-validated stations) are both CONUS -- this
   project has not actually proven the fetch mechanism works outside CONUS.
   AK/HI rows are still included, with real sourced coordinates, because a
   wrong "no data" is worse than no row for a nearest-station search -- but
   treat the fetch step for these as unverified until re-tested.
2. Nine CONUS stations (DRT, GSO, INL, NKX, OAK, UIL, WAL, LWX, TAE) plus
   DNR and CHH also came back HTTP 400 / empty on repeated tries (with
   delays, to rule out rate-limiting) despite being real, sourced, currently
   active stations. NKX (Miramar NAS) and WAL (Wallops Island) are Navy/NASA
   -operated, which may be why. The rest have no obvious explanation found
   this session.
3. The Pacific bucket is short 5 stations (likely Chuuk, Pohnpei, Yap,
   Koror, and Majuro or Kwajalein -- the COFA/Micronesia sites). I could not
   find a sourced `site` code for any of them, and guessed candidates
   (TKK, PNI, YAP, ROR, MAJ, KWA) all returned HTTP 400, so per this
   project's no-fabrication rule they are left out entirely rather than
   guessed. GUM (Guam) and PPG (Pago Pago) DID validate live and are
   included.

Every row's `site` and `lat`/`lon` traces to a real fetched source (see
above); `wmo_id` is left as None only where I could not confirm it (none of
that happened here -- every row has a sourced WMO number). Cross-check
anything flagged UNCONFIRMED before this table gets used for anything live,
especially the Alaska rows given FireView-MCP's wildfire use case.
"""

RADIOSONDE_STATIONS = [
    # --- CONUS (contiguous 48 states) ---
    {"site": "BMX", "wmo_id": "72230", "name": "Birmingham", "state": "AL", "lat": 33.1789, "lon": -86.7822},
    {"site": "LZK", "wmo_id": "72340", "name": "North Little Rock", "state": "AR", "lat": 34.835, "lon": -92.2594},
    {"site": "FGZ", "wmo_id": "72376", "name": "Flagstaff", "state": "AZ", "lat": 35.23, "lon": -111.8216},
    {"site": "TWC", "wmo_id": "72274", "name": "Tucson", "state": "AZ", "lat": 32.2278, "lon": -110.9558},
    {"site": "OAK", "wmo_id": "72493", "name": "Oakland", "state": "CA", "lat": 37.7444, "lon": -122.2236},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned no product / HTTP 400 during 2026-08-09 testing (also tried the co-located WFO id where one exists); code sourced from NCAR/RAP U-flagged station list, verify before relying on it
    {"site": "NKX", "wmo_id": "72293", "name": "San Diego/Miramar NAS", "state": "CA", "lat": 32.8333, "lon": -117.1166},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned no product / HTTP 400 during 2026-08-09 testing (also tried the co-located WFO id where one exists); code sourced from NCAR/RAP U-flagged station list, verify before relying on it
    {"site": "DNR", "wmo_id": "72469", "name": "Denver/Stapleton", "state": "CO", "lat": 39.7675, "lon": -104.8694},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned no product / HTTP 400 during 2026-08-09 testing (also tried the co-located WFO id where one exists); code sourced from NCAR/RAP U-flagged station list, verify before relying on it
    {"site": "GJT", "wmo_id": "72476", "name": "Grand Junction", "state": "CO", "lat": 39.12, "lon": -108.525},
    {"site": "JAX", "wmo_id": "72206", "name": "Jacksonville", "state": "FL", "lat": 30.4839, "lon": -81.7011},
    {"site": "KEY", "wmo_id": "72201", "name": "Key West", "state": "FL", "lat": 24.5531, "lon": -81.7886},
    # NOTE: site=KEY (Key West WFO id) confirmed live; airport ICAO KEYW/EYW is NOT the working param
    {"site": "MFL", "wmo_id": "72202", "name": "Miami", "state": "FL", "lat": 25.75, "lon": -80.3833},
    {"site": "TAE", "wmo_id": "72214", "name": "Tallahassee", "state": "FL", "lat": 30.4461, "lon": -84.2994},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned no product / HTTP 400 during 2026-08-09 testing (also tried the co-located WFO id where one exists); code sourced from NCAR/RAP U-flagged station list, verify before relying on it
    {"site": "TBW", "wmo_id": "72210", "name": "Tampa Bay/Ruskin", "state": "FL", "lat": 27.7053, "lon": -82.4006},
    {"site": "FFC", "wmo_id": "72215", "name": "Peachtree City/Atlanta", "state": "GA", "lat": 33.3558, "lon": -84.5672},
    {"site": "DVN", "wmo_id": "74455", "name": "Davenport", "state": "IA", "lat": 41.6114, "lon": -90.5817},
    {"site": "BOI", "wmo_id": "72681", "name": "Boise", "state": "ID", "lat": 43.5672, "lon": -116.2113},
    {"site": "ILX", "wmo_id": "74560", "name": "Lincoln", "state": "IL", "lat": 40.1517, "lon": -89.3383},
    {"site": "DDC", "wmo_id": "72451", "name": "Dodge City", "state": "KS", "lat": 37.7614, "lon": -99.9686},
    {"site": "TOP", "wmo_id": "72456", "name": "Topeka", "state": "KS", "lat": 39.0722, "lon": -95.6305},
    {"site": "LCH", "wmo_id": "72240", "name": "Lake Charles", "state": "LA", "lat": 30.1253, "lon": -93.2161},
    {"site": "SHV", "wmo_id": "72248", "name": "Shreveport", "state": "LA", "lat": 32.4511, "lon": -93.8414},
    {"site": "LIX", "wmo_id": "72233", "name": "Slidell/New Orleans", "state": "LA", "lat": 30.3369, "lon": -89.825},
    {"site": "CHH", "wmo_id": "74494", "name": "Chatham", "state": "MA", "lat": 41.6569, "lon": -69.9589},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned no product / HTTP 400 during 2026-08-09 testing (also tried the co-located WFO id where one exists); code sourced from NCAR/RAP U-flagged station list, verify before relying on it
    {"site": "CAR", "wmo_id": "72712", "name": "Caribou", "state": "ME", "lat": 46.8683, "lon": -68.0136},
    {"site": "GYX", "wmo_id": "74389", "name": "Gray/Portland", "state": "ME", "lat": 43.8925, "lon": -70.2572},
    {"site": "DTX", "wmo_id": "72632", "name": "Detroit/White Lake", "state": "MI", "lat": 42.6989, "lon": -83.4714},
    {"site": "APX", "wmo_id": "72634", "name": "Gaylord/Alpena", "state": "MI", "lat": 44.9075, "lon": -84.7189},
    {"site": "MPX", "wmo_id": "72649", "name": "Chanhassen/Minneapolis", "state": "MN", "lat": 44.8497, "lon": -93.5647},
    {"site": "INL", "wmo_id": "72747", "name": "International Falls", "state": "MN", "lat": 48.5647, "lon": -93.3975},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned no product / HTTP 400 during 2026-08-09 testing (also tried the co-located WFO id where one exists); code sourced from NCAR/RAP U-flagged station list, verify before relying on it
    {"site": "SGF", "wmo_id": "72440", "name": "Springfield", "state": "MO", "lat": 37.2347, "lon": -93.4014},
    {"site": "JAN", "wmo_id": "72235", "name": "Jackson", "state": "MS", "lat": 32.3189, "lon": -90.08},
    {"site": "GGW", "wmo_id": "72768", "name": "Glasgow", "state": "MT", "lat": 48.2067, "lon": -106.6255},
    {"site": "TFX", "wmo_id": "72776", "name": "Great Falls", "state": "MT", "lat": 47.4614, "lon": -111.3847},
    {"site": "GSO", "wmo_id": "72317", "name": "Greensboro", "state": "NC", "lat": 36.0981, "lon": -79.9428},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned no product / HTTP 400 during 2026-08-09 testing (also tried the co-located WFO id where one exists); code sourced from NCAR/RAP U-flagged station list, verify before relying on it
    {"site": "MHX", "wmo_id": "72305", "name": "Newport/Morehead City", "state": "NC", "lat": 34.7761, "lon": -76.8767},
    {"site": "BIS", "wmo_id": "72764", "name": "Bismarck", "state": "ND", "lat": 46.7717, "lon": -100.7594},
    {"site": "LBF", "wmo_id": "72562", "name": "North Platte", "state": "NE", "lat": 41.1328, "lon": -100.7},
    {"site": "OAX", "wmo_id": "72558", "name": "Omaha/Valley", "state": "NE", "lat": 41.32, "lon": -96.3669},
    # NOTE: RAP's own OAX row is a Mexico/Oaxaca collision (site codes aren't globally unique in that file) -- WMO/lat-lon pulled via ICAO KOAX instead
    {"site": "ABQ", "wmo_id": "72365", "name": "Albuquerque", "state": "NM", "lat": 35.0378, "lon": -106.6219},
    {"site": "EPZ", "wmo_id": "72364", "name": "Santa Teresa/El Paso", "state": "NM", "lat": 31.8728, "lon": -106.698},
    {"site": "LKN", "wmo_id": "72582", "name": "Elko", "state": "NV", "lat": 40.86, "lon": -115.7422},
    {"site": "VEF", "wmo_id": "72388", "name": "Las Vegas", "state": "NV", "lat": 36.0471, "lon": -115.1846},
    {"site": "REV", "wmo_id": "72489", "name": "Reno", "state": "NV", "lat": 39.5681, "lon": -119.7966},
    {"site": "ALY", "wmo_id": "72518", "name": "Albany", "state": "NY", "lat": 42.75, "lon": -73.8},
    {"site": "BUF", "wmo_id": "72528", "name": "Buffalo", "state": "NY", "lat": 42.9411, "lon": -78.7189},
    {"site": "OKX", "wmo_id": "72501", "name": "Upton/Brookhaven", "state": "NY", "lat": 40.865, "lon": -72.8628},
    {"site": "ILN", "wmo_id": "72426", "name": "Wilmington", "state": "OH", "lat": 39.4214, "lon": -83.8217},
    {"site": "OUN", "wmo_id": "72357", "name": "Norman", "state": "OK", "lat": 35.1808, "lon": -97.4378},
    {"site": "MFR", "wmo_id": "72597", "name": "Medford", "state": "OR", "lat": 42.3769, "lon": -122.8822},
    {"site": "SLE", "wmo_id": "72694", "name": "Salem", "state": "OR", "lat": 44.9092, "lon": -123.0083},
    {"site": "PBZ", "wmo_id": "72520", "name": "Pittsburgh/Coraopolis", "state": "PA", "lat": 40.5167, "lon": -80.2167},
    {"site": "CHS", "wmo_id": "72208", "name": "Charleston", "state": "SC", "lat": 32.895, "lon": -80.0275},
    {"site": "ABR", "wmo_id": "72659", "name": "Aberdeen", "state": "SD", "lat": 45.4556, "lon": -98.4133},
    {"site": "UNR", "wmo_id": "72662", "name": "Rapid City", "state": "SD", "lat": 44.0453, "lon": -103.0569},
    {"site": "OHX", "wmo_id": "72327", "name": "Nashville/Old Hickory", "state": "TN", "lat": 36.2333, "lon": -86.55},
    {"site": "AMA", "wmo_id": "72363", "name": "Amarillo", "state": "TX", "lat": 35.2331, "lon": -101.7091},
    {"site": "BRO", "wmo_id": "72250", "name": "Brownsville", "state": "TX", "lat": 25.9167, "lon": -97.4192},
    {"site": "CRP", "wmo_id": "72251", "name": "Corpus Christi", "state": "TX", "lat": 27.7789, "lon": -97.5055},
    {"site": "DRT", "wmo_id": "72261", "name": "Del Rio", "state": "TX", "lat": 29.3744, "lon": -100.9183},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned no product / HTTP 400 during 2026-08-09 testing (also tried the co-located WFO id where one exists); code sourced from NCAR/RAP U-flagged station list, verify before relying on it
    {"site": "FWD", "wmo_id": "72249", "name": "Fort Worth", "state": "TX", "lat": 32.835, "lon": -97.2986},
    {"site": "MAF", "wmo_id": "72265", "name": "Midland", "state": "TX", "lat": 31.9425, "lon": -102.1891},
    {"site": "SLC", "wmo_id": "72572", "name": "Salt Lake City", "state": "UT", "lat": 40.7722, "lon": -111.9552},
    {"site": "RNK", "wmo_id": "72318", "name": "Blacksburg/Roanoke", "state": "VA", "lat": 37.2039, "lon": -80.4142},
    {"site": "LWX", "wmo_id": "72403", "name": "Sterling/Washington-Dulles", "state": "VA", "lat": 38.95, "lon": -77.45},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned no product / HTTP 400 during 2026-08-09 testing (also tried the co-located WFO id where one exists); code sourced from NCAR/RAP U-flagged station list, verify before relying on it
    {"site": "WAL", "wmo_id": "72402", "name": "Wallops Island", "state": "VA", "lat": 37.9333, "lon": -75.4833},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned no product / HTTP 400 during 2026-08-09 testing (also tried the co-located WFO id where one exists); code sourced from NCAR/RAP U-flagged station list, verify before relying on it
    {"site": "UIL", "wmo_id": "72797", "name": "Quillayute", "state": "WA", "lat": 47.9339, "lon": -124.5602},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned no product / HTTP 400 during 2026-08-09 testing (also tried the co-located WFO id where one exists); code sourced from NCAR/RAP U-flagged station list, verify before relying on it
    {"site": "OTX", "wmo_id": "72786", "name": "Spokane", "state": "WA", "lat": 47.6806, "lon": -117.6266},
    {"site": "GRB", "wmo_id": "72645", "name": "Green Bay", "state": "WI", "lat": 44.4986, "lon": -88.1119},
    {"site": "RIW", "wmo_id": "72672", "name": "Riverton", "state": "WY", "lat": 43.0647, "lon": -108.4766},
    # --- ALASKA ---
    {"site": "ANC", "wmo_id": "70273", "name": "Anchorage", "state": "AK", "lat": 61.1567, "lon": -149.9863},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned HTTP 400 during 2026-08-09 testing (all 13 AK candidates rejected outright, incl. WFO ids AFC/AFG/AJK); code sourced from NCAR/RAP U-flagged station list, cross-checked vs IGRA2 name+coords, NOT confirmed against forecast.weather.gov
    {"site": "ANN", "wmo_id": "70398", "name": "Annette Island", "state": "AK", "lat": 55.0389, "lon": -131.5777},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned HTTP 400 during 2026-08-09 testing (all 13 AK candidates rejected outright, incl. WFO ids AFC/AFG/AJK); code sourced from NCAR/RAP U-flagged station list, cross-checked vs IGRA2 name+coords, NOT confirmed against forecast.weather.gov
    {"site": "BRW", "wmo_id": "70026", "name": "Barrow/Utqiagvik", "state": "AK", "lat": 71.2889, "lon": -156.7833},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned HTTP 400 during 2026-08-09 testing (all 13 AK candidates rejected outright, incl. WFO ids AFC/AFG/AJK); code sourced from NCAR/RAP U-flagged station list, cross-checked vs IGRA2 name+coords, NOT confirmed against forecast.weather.gov
    {"site": "BET", "wmo_id": "70219", "name": "Bethel", "state": "AK", "lat": 60.785, "lon": -161.84},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned HTTP 400 during 2026-08-09 testing (all 13 AK candidates rejected outright, incl. WFO ids AFC/AFG/AJK); code sourced from NCAR/RAP U-flagged station list, cross-checked vs IGRA2 name+coords, NOT confirmed against forecast.weather.gov
    {"site": "CDB", "wmo_id": "70316", "name": "Cold Bay", "state": "AK", "lat": 55.2011, "lon": -162.7163},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned HTTP 400 during 2026-08-09 testing (all 13 AK candidates rejected outright, incl. WFO ids AFC/AFG/AJK); code sourced from NCAR/RAP U-flagged station list, cross-checked vs IGRA2 name+coords, NOT confirmed against forecast.weather.gov
    {"site": "FAI", "wmo_id": "70261", "name": "Fairbanks", "state": "AK", "lat": 64.8161, "lon": -147.8766},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned HTTP 400 during 2026-08-09 testing (all 13 AK candidates rejected outright, incl. WFO ids AFC/AFG/AJK); code sourced from NCAR/RAP U-flagged station list, cross-checked vs IGRA2 name+coords, NOT confirmed against forecast.weather.gov
    {"site": "AKN", "wmo_id": "70326", "name": "King Salmon", "state": "AK", "lat": 58.6794, "lon": -156.6683},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned HTTP 400 during 2026-08-09 testing (all 13 AK candidates rejected outright, incl. WFO ids AFC/AFG/AJK); code sourced from NCAR/RAP U-flagged station list, cross-checked vs IGRA2 name+coords, NOT confirmed against forecast.weather.gov
    {"site": "ADQ", "wmo_id": "70350", "name": "Kodiak", "state": "AK", "lat": 57.7431, "lon": -152.4866},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned HTTP 400 during 2026-08-09 testing (all 13 AK candidates rejected outright, incl. WFO ids AFC/AFG/AJK); code sourced from NCAR/RAP U-flagged station list, cross-checked vs IGRA2 name+coords, NOT confirmed against forecast.weather.gov
    {"site": "OTZ", "wmo_id": "70133", "name": "Kotzebue", "state": "AK", "lat": 66.8864, "lon": -162.6133},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned HTTP 400 during 2026-08-09 testing (all 13 AK candidates rejected outright, incl. WFO ids AFC/AFG/AJK); code sourced from NCAR/RAP U-flagged station list, cross-checked vs IGRA2 name+coords, NOT confirmed against forecast.weather.gov
    {"site": "MCG", "wmo_id": "70231", "name": "McGrath", "state": "AK", "lat": 62.9583, "lon": -155.5977},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned HTTP 400 during 2026-08-09 testing (all 13 AK candidates rejected outright, incl. WFO ids AFC/AFG/AJK); code sourced from NCAR/RAP U-flagged station list, cross-checked vs IGRA2 name+coords, NOT confirmed against forecast.weather.gov
    {"site": "OME", "wmo_id": "70200", "name": "Nome", "state": "AK", "lat": 64.5072, "lon": -165.4347},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned HTTP 400 during 2026-08-09 testing (all 13 AK candidates rejected outright, incl. WFO ids AFC/AFG/AJK); code sourced from NCAR/RAP U-flagged station list, cross-checked vs IGRA2 name+coords, NOT confirmed against forecast.weather.gov
    {"site": "SNP", "wmo_id": "70308", "name": "St. Paul Island", "state": "AK", "lat": 57.15, "lon": -170.2166},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned HTTP 400 during 2026-08-09 testing (all 13 AK candidates rejected outright, incl. WFO ids AFC/AFG/AJK); code sourced from NCAR/RAP U-flagged station list, cross-checked vs IGRA2 name+coords, NOT confirmed against forecast.weather.gov
    {"site": "YAK", "wmo_id": "70361", "name": "Yakutat", "state": "AK", "lat": 59.5167, "lon": -139.6666},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned HTTP 400 during 2026-08-09 testing (all 13 AK candidates rejected outright, incl. WFO ids AFC/AFG/AJK); code sourced from NCAR/RAP U-flagged station list, cross-checked vs IGRA2 name+coords, NOT confirmed against forecast.weather.gov
    # --- HAWAII ---
    {"site": "ITO", "wmo_id": "91285", "name": "Hilo", "state": "HI", "lat": 19.7183, "lon": -155.0583},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned HTTP 400 during 2026-08-09 testing; code sourced from NCAR/RAP, NOT confirmed against forecast.weather.gov
    {"site": "LIH", "wmo_id": "91165", "name": "Lihue", "state": "HI", "lat": 21.9933, "lon": -159.3466},  # UNCONFIRMED LIVE FETCH -- see note below
    # NOTE: live fetch returned HTTP 400 during 2026-08-09 testing; code sourced from NCAR/RAP, NOT confirmed against forecast.weather.gov
    # --- PACIFIC / CARIBBEAN TERRITORIES ---
    {"site": "GUM", "wmo_id": "91212", "name": "Guam", "state": "GU", "lat": 13.4767, "lon": 144.7944},
    # NOTE: lat/lon from IGRA2 GQM00091212 (RAP file has no Pacific coverage)
    {"site": "PPG", "wmo_id": "91765", "name": "Pago Pago", "state": "AS", "lat": -14.3383, "lon": -170.7191},
    # NOTE: lat/lon from IGRA2 AQM00091765 (RAP file has no Pacific coverage)
    {"site": "SJU", "wmo_id": "78526", "name": "San Juan", "state": "PR", "lat": 18.4317, "lon": -65.9919},
]
