"""Detector profiles: every constant MATLAB's converter hard-codes, as one frozen record.

``matlab-2019`` (the default, Q6.10) holds the constants of
``legacy/tdc_autoconverter/lib/dld_read_5channels_reconst_multi_imp.m`` and reproduces its output
byte for byte; ``matlab-2023-lab-edit`` those of the front panel's copy
(``legacy/DLD_front_panel/lib/Core_BEC_Analysis/lib/import_mcp_tdc_data/``). The plate profiles
(``plates-2017``, ``plates-2022``, ``plates-2025``, the last marked uncalibrated) start as copies of
``matlab-2019`` and change only through calibration (stage 3); ``PLATE_SWAPS`` dates them, and
``suggested_plates`` names the one for a day (a suggestion: the default stays ``matlab-2019``).
Each built-in also ships as a JSON file (``builtin_files``, A10.3).

Times and tolerances are in TDC bins (``bin_time`` seconds each) unless named otherwise; dead
times are in seconds, as MATLAB writes them (``0.5e-6/bin_time``). A profile is saved as JSON
(``to_json``, ``from_json``); ``content_hash`` covers the fields that change the output, for
provenance beside the name and version.

**Tags** (Q18.4): HeLab's TXY are named ``d_txy_helab_<tag>_<N>.txt``, so files of two profiles never
share a name and a reader on another computer knows which profile made one from its name alone.
A built-in's tag is fixed in its definition and JSON and frozen once used (``m19v1``; the letter
before the number says ``v`` released, ``a``/``b``/``t`` alpha, beta, testing). Any other profile is
tagged by its content hash (``u`` and ``USER_TAG_DIGITS`` hex digits); ``file_tag`` gives the tag a
profile writes under.

Extending the schema (so existing profiles keep their hash and their files keep loading):

- a new field gets a **neutral default**, the value that behaves as HeLab did before it existed
  (``NEUTRAL``); ``from_dict`` fills a missing field with it, and ``content_hash`` leaves a field
  at its neutral default out. A field with no neutral value is required.
- a change that isn't a new field (a renamed field, a changed meaning) bumps ``SCHEMA`` and adds a
  step to ``_MIGRATIONS`` that rewrites the older dict; unknown fields are always refused.
- a field the output path doesn't read is left out of the hash (``UNUSED_BY_OUTPUT``); it joins
  the hash the moment the output depends on it (``tests/test_convert_profile.py`` perturbs every
  field and fails if one changes the output without changing the hash).

Qt-free; standard library only.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any, Callable, Mapping

SCHEMA = 1
DEFAULT_PROFILE = "matlab-2019"

# How an ambiguous candidate is handled. "matlab": the first candidate in search order is kept
# and the second only ends the search (for x2 this is the ``how_many_x == ~1`` quirk; for y the
# second pair breaks the inner loop). A retry of the other candidate would be a new value here.
CANDIDATE_HANDLING = ("matlab",)
# How X and Y are formed from the corner times. "centred" (2019): the columns hold x1 − tx and
# x2 − tx, so X = ((x1 − tx) − (x2 − tx))·v⊥·bin_time; "raw" (2023 lab edit): the columns hold x1
# and x2, so X = (x1 − x2)·v⊥·bin_time. For integer times below 2^52 (every TDC file) the two are
# the same doubles; they can differ only for times with a fraction, which textscan accepts.
POSITION_FORMULAS = ("centred", "raw")

# Fields that describe the profile rather than change its output; left out of content_hash.
DESCRIPTIVE = ("name", "version", "calibrated", "notes", "tag")
# A built-in's tag (``file_tag``): a lowercase letter, then 1 to 15 lowercase letters or digits; ``u``
# starts only the tags made from a hash.
TAG_PATTERN = re.compile(r"^[a-z][a-z0-9]{1,15}$", re.ASCII)
USER_TAG_PREFIX = "u"
# Hex digits of the content hash in a user profile's tag: 32 bits, so two of a lab's few dozen
# profiles share one with odds of about one in ten million; HeLab's own folders hold the full hash
# in each shot's provenance, so a shared tag there is found stale and converted again.
USER_TAG_DIGITS = 8
# Fields the output path doesn't read yet; left out of content_hash. channel_mcp joins the hash
# once MCP matching is on; channel_trigger once anything in the output path reads it (today only
# stage 4's done-writing check will: t_zero is the first raw row, whatever its channel).
UNUSED_BY_OUTPUT = ("channel_mcp", "channel_trigger")
# Schema n's dict → schema n + 1's, applied in turn by from_dict. None yet.
_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}
# Non-negative thresholds and sums (bins) and dead times (s).
_NON_NEGATIVE = ("search_window", "match_time_sum_x", "match_tolerance_x", "match_time_sum_y", "match_tolerance_y",
                 "xy_sum_tolerance", "time_sum_t_x", "time_sum_t_y",
                 "dead_time_x1", "dead_time_x2", "dead_time_y1", "dead_time_y2")


class ProfileError(ValueError):
    """A profile's values or JSON aren't valid."""


@dataclass(frozen=True, kw_only=True)
class DetectorProfile:
    """The converter's constants. MATLAB's names are in brackets; a default is the field's
    neutral value (see the module's notes on extending the schema)."""

    name: str
    version: int
    calibrated: bool
    notes: str
    # The tag in HeLab's TXY names (``file_tag``): set only on built-ins, "" on every other profile.
    tag: str = ""
    # TDC: seconds per bin [bin_time].
    bin_time: float
    # Channel map: the four delay-line corners (distinct), the MCP and the trigger. MCP and
    # trigger are unused by the 4-corner match (UNUSED_BY_OUTPUT); stage 4's done-writing check
    # reads the trigger channel.
    channel_x1: int
    channel_x2: int
    channel_y1: int
    channel_y2: int
    channel_mcp: int
    channel_trigger: int
    # Time zero: subtract the first raw row's time, whatever its channel [normalise_time_flag,
    # t_zero = dld_output_raw(1,2)], read before sorting.
    subtract_time_zero: bool
    # Skip the first row after sorting by time as "the trigger" [for count = 2:…].
    skip_first_sorted_row: bool
    # Dead time per corner, seconds; 0 is none. A non-zero one keeps the first pulse of each
    # group within it of the group's first pulse and drops the rest before matching (the 2023
    # edit's uniquetol(…, dead_time/bin_time, 'DataScale', 1) cut; only x1's is switched on).
    dead_time_x1: float = 0.0
    dead_time_x2: float = 0.0
    dead_time_y1: float = 0.0
    dead_time_y2: float = 0.0
    # Matching. Rows searched around each x1: −1, +1, −2, +2, … [search_no]; candidates more
    # than search_window from x1 are skipped [T_sum]; an x2 is kept when |x1 − x2| <
    # match_time_sum_x + match_tolerance_x [T_sum_tol_throw], a y pair when |y1 − y2| <
    # match_time_sum_y + match_tolerance_y [T_sum_tol_keep] and |x1 + x2 − y1 − y2| <
    # xy_sum_tolerance [two_tolerance_keep].
    search_depth: int
    search_window: float
    match_time_sum_x: float
    match_tolerance_x: float
    match_time_sum_y: float
    match_tolerance_y: float
    xy_sum_tolerance: float
    x2_handling: str = "matlab"
    y_handling: str = "matlab"
    # Output: T = (tx + ty)/2 with tx = (x1 + x2 − time_sum_t_x)/2 [T_sum, or T_sum_x in 2023];
    # X and Y per position_formula, scaled by v⊥ per axis (m/s) [v_perp_x, v_perp_y].
    time_sum_t_x: float
    time_sum_t_y: float
    v_perp_x: float
    v_perp_y: float
    position_formula: str
    # MATLAB preallocates floor(rows/4) output rows and grows the matrix with zeros past that;
    # an x1 whose x2 matched but whose y didn't, in a grown row, then survives as a hit with
    # T = 0 and Y = 0 (an x1 with no y otherwise leaves a NaN row that is dropped).
    matlab_overflow_row: bool
    # No hits: write an empty TXY (the 2023 dld_raw_to_txy), or none (dld_raw_to_txy_counts).
    write_empty_txy: bool

    def __post_init__(self) -> None:
        for field in dataclasses.fields(self):
            value = getattr(self, field.name)
            if field.type == "float":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ProfileError(f"{field.name} must be a number, not {value!r}")
                # 3200 and 3200.0 are one profile: the JSON and the hash see floats.
                object.__setattr__(self, field.name, float(value))
            elif field.type == "int":
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ProfileError(f"{field.name} must be an integer, not {value!r}")
            elif field.type == "bool":
                if not isinstance(value, bool):
                    raise ProfileError(f"{field.name} must be true or false, not {value!r}")
            elif not isinstance(value, str):
                raise ProfileError(f"{field.name} must be text, not {value!r}")
            if field.type == "float" and not math.isfinite(getattr(self, field.name)):
                raise ProfileError(f"{field.name} must be finite, not {value!r}")
        if not self.name:
            raise ProfileError("A profile needs a name")
        if self.tag and (not TAG_PATTERN.fullmatch(self.tag) or self.tag.startswith(USER_TAG_PREFIX)):
            raise ProfileError(f"tag must be empty, or a lowercase letter (not {USER_TAG_PREFIX!r}) and 1 to 15 "
                               f"lowercase letters or digits, not {self.tag!r}")
        if not self.bin_time > 0:
            raise ProfileError("bin_time must be positive")
        if self.search_depth < 1:
            raise ProfileError("search_depth must be at least 1")
        for name in _NON_NEGATIVE:
            if getattr(self, name) < 0:
                raise ProfileError(f"{name} must be zero or positive")
        corners = (self.channel_x1, self.channel_x2, self.channel_y1, self.channel_y2)
        if len(set(corners)) != len(corners):
            raise ProfileError(f"The four corner channels must differ, not {corners}")
        for name in ("x2_handling", "y_handling"):
            if getattr(self, name) not in CANDIDATE_HANDLING:
                raise ProfileError(f"{name} must be one of {CANDIDATE_HANDLING}")
        if self.position_formula not in POSITION_FORMULAS:
            raise ProfileError(f"position_formula must be one of {POSITION_FORMULAS}")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA, **dataclasses.asdict(self)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DetectorProfile:
        schema = data.get("schema")
        if isinstance(schema, bool) or not isinstance(schema, int) or not 1 <= schema <= SCHEMA:
            raise ProfileError(f"Unknown profile schema {schema!r} (this HeLab reads 1 to {SCHEMA})")
        values = {k: v for k, v in data.items() if k != "schema"}
        for step in range(schema, SCHEMA):
            values = _MIGRATIONS[step](values)
        names = {field.name for field in dataclasses.fields(cls)}
        if set(values) - names:
            raise ProfileError(f"Unknown profile fields: {sorted(set(values) - names)}")
        missing = names - set(values) - set(NEUTRAL)
        if missing:
            raise ProfileError(f"Missing profile fields: {sorted(missing)}")
        return cls(**{name: values[name] for name in names if name in values})

    @classmethod
    def from_json(cls, text: str) -> DetectorProfile:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            raise ProfileError(f"Not JSON: {error}") from error
        if not isinstance(data, dict):
            raise ProfileError("A profile's JSON is an object")
        return cls.from_dict(data)

    def content_hash(self) -> str:
        """SHA-256 of the fields that change the output, as canonical JSON: two profiles with one
        hash convert every file alike. Left out: the descriptive fields (name, version,
        calibrated, notes, tag), those the output doesn't read (UNUSED_BY_OUTPUT) and any at its
        neutral default, so adding a field doesn't change existing profiles' hashes."""
        data = {k: v for k, v in dataclasses.asdict(self).items()
                if k not in DESCRIPTIVE and k not in UNUSED_BY_OUTPUT and not (k in NEUTRAL and v == NEUTRAL[k])}
        text = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def replace(self, **changes: Any) -> DetectorProfile:
        return dataclasses.replace(self, **changes)


# Each field's neutral value: its default. (``tag`` is descriptive: its "" says only "not a built-in".)
NEUTRAL: Mapping[str, Any] = MappingProxyType({
    field.name: field.default for field in dataclasses.fields(DetectorProfile)
    if field.default is not dataclasses.MISSING})

MATLAB_2019 = DetectorProfile(
    name="matlab-2019",
    version=1,
    tag="m19v1",
    calibrated=False,
    notes="MATLAB tdc_autoconverter's dld_read_5channels_reconst_multi_imp (unchanged since 2017), "
          "flags 1,0,1,0: byte-identical to its _txy_forc files, quirks included.",
    bin_time=25e-12,
    channel_x1=0, channel_x2=1, channel_y1=2, channel_y2=3, channel_mcp=4, channel_trigger=5,
    subtract_time_zero=True,
    skip_first_sorted_row=True,
    dead_time_x1=0.0, dead_time_x2=0.0, dead_time_y1=0.0, dead_time_y2=0.0,
    search_depth=36,
    search_window=3200.0,
    match_time_sum_x=3200.0, match_tolerance_x=200.0,
    match_time_sum_y=3200.0, match_tolerance_y=200.0,
    xy_sum_tolerance=400.0,
    x2_handling="matlab", y_handling="matlab",
    time_sum_t_x=3200.0, time_sum_t_y=3200.0,
    v_perp_x=5.2632e5, v_perp_y=5.2632e5,
    position_formula="centred",
    matlab_overflow_row=True,
    write_empty_txy=False,
)

MATLAB_2023_LAB_EDIT = MATLAB_2019.replace(
    name="matlab-2023-lab-edit",
    tag="m23v1",
    notes="The front panel's copy synced from the lab on 2023-08-29: an x1 dead time of 0.5 µs "
          "(uniquetol), time sums 3390/3275 in T only, X/Y from the raw corner times.",
    dead_time_x1=0.5e-6,
    time_sum_t_x=3390.0, time_sum_t_y=3275.0,
    position_formula="raw",
    write_empty_txy=True,
)

# The plate profiles (Q6.11): the 2017, 2022 and 2025 MCP plates. They start as copies of
# ``matlab-2019`` (equal output, so equal content hash) and change only through calibration (stage 3).
_PLATES_NOTES = ("Copy of matlab-2019 until this plate is calibrated (stage 3): same output, so same content "
                 "hash. ")
PLATES_2017 = MATLAB_2019.replace(
    name="plates-2017",
    tag="p17v1",
    notes=_PLATES_NOTES + "The MCP plates fitted on 2017-03-17.")
PLATES_2022 = MATLAB_2019.replace(
    name="plates-2022",
    tag="p22v1",
    notes=_PLATES_NOTES + "The MCP plates fitted in ~2022 (between 2022-08-22 and 2022-11-03; 2022-11-03 for "
                          "now). Measured with MCP pulses in 2022-11: time sums x 3367, y 3294 bins.")
PLATES_2025 = MATLAB_2019.replace(
    name="plates-2025",
    tag="p25t1",
    notes="Uncalibrated: no calibration data for these plates yet (Q6.11). " + _PLATES_NOTES
          + "The MCP plates fitted on 2025-06-18.")
# Marked uncalibrated in the profile manager: a plate with no calibration data at all (Q6.11,
# Tony 2026-10-28: "the 2025 profile is marked uncalibrated").
UNCALIBRATED = frozenset({"plates-2025"})

BUILTIN_PROFILES: Mapping[str, DetectorProfile] = MappingProxyType(
    {profile.name: profile for profile in (MATLAB_2019, MATLAB_2023_LAB_EDIT, PLATES_2017, PLATES_2022, PLATES_2025)})

# When each plate profile's plates went in (local dates, Q6.10): a folder's date can suggest one,
# never apply it (the default stays ``matlab-2019``). The 2022 date is provisional: the first run on
# X named for the new plates (Tony, 2026-10-29).
PLATE_SWAPS: tuple[tuple[str, str], ...] = (
    ("2017-03-17", "plates-2017"),
    ("2022-11-03", "plates-2022"),
    ("2025-06-18", "plates-2025"),
)

# The built-ins as JSON files in the package (A10.3): ``builtin_files`` reads them, and a test
# checks each equals its definition here. (The app uses the definitions, so a build that leaves
# the files out still converts.)
BUILTIN_FOLDER = "builtin_profiles"


def file_tag(profile: DetectorProfile) -> str:
    """The tag ``profile``'s TXY are named with (``d_txy_helab_<tag>_<N>.txt``): a built-in's own while
    the profile is that built-in (its name, tag and content hash), else ``u`` and the first
    ``USER_TAG_DIGITS`` hex digits of its content hash. So an edited copy of a built-in, or a file
    claiming a built-in's tag, never writes under the built-in's name."""
    builtin = BUILTIN_PROFILES.get(profile.name)
    if builtin is not None and profile.tag == builtin.tag and profile.content_hash() == builtin.content_hash():
        return builtin.tag
    return USER_TAG_PREFIX + profile.content_hash()[:USER_TAG_DIGITS]


def builtin_profile(name: str = DEFAULT_PROFILE) -> DetectorProfile:
    try:
        return BUILTIN_PROFILES[name]
    except KeyError:
        raise ProfileError(f"No built-in profile {name!r} (have {sorted(BUILTIN_PROFILES)})") from None


def builtin_files() -> dict[str, DetectorProfile]:
    """The built-in profiles as their packaged JSON files hold them, by name (A10.3)."""
    from importlib import resources
    found: dict[str, DetectorProfile] = {}
    for entry in resources.files(__package__).joinpath(BUILTIN_FOLDER).iterdir():
        if entry.name.endswith(".json"):
            profile = DetectorProfile.from_json(entry.read_text(encoding="utf-8"))
            found[profile.name] = profile
    return found


def suggested_plates(day: str) -> str | None:
    """The plate profile whose plates were in on ``day`` (``YYYY-MM-DD``), or None before the first
    swap listed (or for a malformed date). A suggestion only (Q6.10)."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return None
    chosen = None
    for since, name in PLATE_SWAPS:
        if day >= since:
            chosen = name
    return chosen
