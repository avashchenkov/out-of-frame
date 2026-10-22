# B-Plan WFS fixtures

Recorded Berlin B-Plan WFS responses, as GeoJSON in EPSG:4326, one per layer, kept as
returned:

- `freiheit-22.json`: the plans in procedure (`bplan:a_bp_iv`) and in force (`bplan:b_bp_fs`)
  that the WFS returns for the square around the 500 m circle around Freiheit 22, 13597
  Berlin, 2026-10-14: roughly those whose bounds overlap the square. The WFS also returns
  plans a few metres beyond it, such as VIII-B4.

Recorded on 2026-10-16 by `evals/label.py`: the plans that the WFS returns around each
end-to-end address, from which its labels were written. Named as the Overpass fixtures, such
as `e4-teutonenstrasse-10.json` for E4.

Recorded on 2026-10-22 by the production WFS queries during the held-out address preflight:

- `e6-oberhofer-weg-45.json`: the full responses around Oberhofer Weg 45, from which code
  selects XII-94, XII-181, XII-87, XII-159 and XII-284.
- `e7-teltower-strasse-31.json`: the full responses around Teltower Straße 31, selecting X-129.

Each has both layers, including the empty in-procedure response. No features were removed.

Data: Geoportal Berlin, B-Plan WFS, licence dl-de/zero-2.0.
