# Fabric calculator (phase 11)

`POST /v1/yardage` with `{style_id, fabric_width_in (36|45|60), measurements: [sheet items], allowances?}`
returns yards (rounded up to a quarter), the exact figure, the answer for all three cloth widths, the piece
list, the layout, and notes (low-confidence inputs, pieces joined because they are wider than the cloth).

## How it works (`calculator.py`)

1. Each style (`senator`, `kaftan`, `gown`, `iro_buba`) is a list of rectangular pieces sized from the
   measurements plus ease.
2. A shelf packer lays the pieces across the usable width (cloth width minus selvages, minus shrinkage).
   Short pieces stack in leftover columns; tapered trouser legs nest; the iro wrapper may turn sideways.
3. Allowances multiply the length: shrinkage, extra for cutting, print matching. The total is rounded up
   to the next quarter yard.

The tailor can set `seam_in`, `hem_in`, `shrink_pct`, `extra_pct`, `pattern_match_pct`, `round_to_yd`.

## Status: first estimates, not tailor data

The piece lists, ease amounts and allowance defaults are my estimates of standard cuts. The plan's
"done when" is that the pilot tailor agrees within half a yard for each style. Until then treat every
number as unconfirmed. Things most worth checking with the tailor:

- **Kaftan** comes out high (about 7.5 yards at 45" for an average body): the long robe's front and back
  are each about 28" wide so they cannot sit side by side on 45" cloth. Is that how the tailor cuts it?
- **Senator** (about 5.25 yards at 45") against what the tailor normally uses.
- Ease, trouser taper nesting (0.85), and whether the kaftan and senator should include trousers at all.
- Default shrinkage (5%) is applied to both usable width and length.

Only the cut dimensions are modelled (no curved pattern shapes), so results lean slightly high.
