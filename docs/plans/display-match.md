# Plan: match two displays with the iPhone probe

Fork goal: make a secondary display (Innoview, LCD, ~P3) look like a reference display (ASUS
PG32UCDM3, QD-OLED, ~P3+) in white point, tone response and brightness, measured with the iPhone
ambient-light probe. The reference's hardware stays untouched; any correction on it is software
only (ICC profile), and only when the user asks for it.

## Ground rules

- **One owner of the gamma table per display.** A correction lives in exactly one place: an ICC
  profile's `vcgt` (preferred), the d65 menu-bar agent, or BetterDisplay software adjustments.
  Never two at once; they overwrite each other.
- **The ICC profile is the persistent carrier.** macOS loads `vcgt` on login, wake and re-plug with
  no agent running, and BetterDisplay favourite slots can switch profiles.
- **Hardware first on the secondary, software for the rest.** DDC brightness and RGB gain (Innoview
  answers 0x10, 0x16/0x18/0x1A) before any gamma-table change, and every DDC write is verified with
  the sensor (upstream found DDC readback untrustworthy).
- **Matching is relative.** The ALS is uncalibrated, so the target is the reference display's
  measured white, not absolute D65. Both displays are measured in the same session, same room
  light, same probe placement.

## Phase 0 — baseline, no code

1. Build and install the probe (see [runbook](../runbook.md)); confirm `-sensorCheck`.
2. `swift run d65 display list`, then `swift run d65 serve --display-id <id>` (default mode is
   `measureOnly`) on each display. Dark room; ASUS in Racing, 6500K, gamma 2.2, Uniform Brightness
   on so OLED ABL doesn't move the reading; Innoview on its Spyder profile.
3. Keep both session JSONs. Exit: white xy, Y, fitted gamma and primaries for both displays.

### Phase 0 results (2026-11-12, iPhone 15 Pro, iOS 27.2 probe; dark-ish room)

| | ASUS PG32UCDM3 (Racing, 6500K, 2.2) | Innoview (Spyder profile, DDC brightness 50) |
|---|---|---|
| White xy (probe) | 0.3071, 0.3059 | 0.2982, 0.2957 |
| White Y (probe units) | 725 | 397 (ratio 0.55) |
| Black Y | 0.17 | 3.90 |
| Grey-ramp gamma | 1.90 | 2.08 |
| Green primary (probe) | 0.288, 0.521 | 0.290, 0.513 |

Findings:
- **The probe is not colorimetric on these panels.** Both greens read near 0.29, 0.52; the
  panels' real greens are ~0.249, 0.718 (ASUS EDID) and ~0.263, 0.698 (Innoview, Spyder). Every
  white reads blue/magenta of D65 as a result.
- **The white-to-white gap (ΔE00 5.0) is probably sensor bias, not a real mismatch.** The Innoview
  is Spyder-corrected to D65 and the ASUS is factory-calibrated, yet the probe reads them 5 apart.
  A sensor-driven white match between these two panels would likely make them look *less* alike.
- Trustworthy per panel: grey-ramp gamma, black level, and relative brightness changes on one
  panel. Cross-panel Y ratio is also spectrally biased; treat 0.55 as a rough indication only.
- Fixes needed to get here: hold-last-value for the event-on-change ALS (OLED black starved the
  black patch), and `--sampling`/`--settling` flags (hand-held probe dropped too many samples).
- Host bug: a probe killed mid-connection keeps the lease until the host restarts.

Consequence for Phases 2–3: per-display spectral correction is needed before matching whites
across panel types (a 3×3 matrix per panel, fitted once against a known reference, e.g. the
Innoview's Spyder white and the ASUS EDID primaries), or the white match is done by eye with the
probe used only for gamma and brightness.

### Per-display correction and eye match (2026-11-12)

- Three-colour correction (`scripts/profile-tools/probe_correction.py`: each panel's known
  primaries, measured luminances, no white reference) put **both** whites ~15 ΔE00 from D65 on the
  green side. The ALS's luminance weighting per primary is off too, so even a per-panel matrix
  can't make absolute or cross-panel whites trustworthy without a reference instrument.
- The probe's suggested Innoview gains (R 0.94, G 1, B 0.72) were far off. The eye match landed
  near neutral: **User preset, RGB gain 50/49/50, brightness 42** (Spyder profile still selected),
  saved in `local/compare-saves.json`.
- Innoview RGB gains only take effect in its User preset (0x14 = 11); in 6500K (5) they are
  ignored but still read back as written.
- `tools/compare/` is the matching tool that worked: one full-screen page per display, synced by
  a local server that writes only to the secondary over DDC, with A/B flips and saves.

## Phase 1 — compare

- `d65 compare <reference.json> <secondary.json>`: white xy/CCT, Y ratio, gamma, primaries, and
  ΔE00 between the two whites (relative, same sensor).
- Tests: synthetic records with known offsets.

## Phase 2 — match the secondary to the reference

- `--target-from <reference.json>`: white target = reference's measured white chromaticity
  instead of D65, plugged into the existing white-target path (`SessionModel.whiteTarget`).
- `--match-luminance`: sensor-verified DDC brightness search on the secondary until white Y is
  within 3 % of the reference's; reuse the `--brightness-test` restoration search. Software dimming
  only if DDC can't reach it.
- RGB balance: try DDC gains first (verify each write); fall back to the existing gamma-table
  solve for the residual.
- Exit: secondary white within ΔE00 2 of the reference white and Y within 3 %, re-measured.

## Phase 3 — export as an ICC profile

- `d65 export-icc <session.json> --out <file.icc>`: v2 matrix/TRC profile with
  - primaries: measured if the blue path checks out (upstream open question 1), else EDID;
  - TRC: fitted gamma;
  - `vcgt`: the solved correction table.
- Install to `~/Library/ColorSync/Profiles`, select it, save to a BetterDisplay favourite slot.
- Verify with `scripts/profile-tools/icc_audit.py` and a re-measure through the profile.
- Optional for the reference: a measured profile for the ASUS (software only), if its measured
  white is off the factory D65 by more than ΔE00 2.

## Phase 4 — leftovers via BetterDisplay

Only for what Phases 2–3 can't express (for example a saturation difference): BetterDisplay
software adjustments, saved as a preset, with the d65 agent off for that display.

## Risks

- QD-OLED vs LCD spectra: the ALS may not be colorimetric (upstream: cyan additivity off by ΔE 18.6).
  Whites are the most trustworthy reading; treat primaries with care.
- OLED ABL makes full-field patches dimmer than desktop windows; match luminance at the level the
  desktop actually sits at.
- Probe signing expires every 7 days on a free Apple ID.
- macOS 27.3 beta: private IOHID/IOAVService paths may change.
