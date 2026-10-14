# B-Plan WFS fixtures

Recorded Berlin B-Plan WFS responses, as GeoJSON in EPSG:4326, one per layer, kept as
returned:

- `freiheit-22.json`: the plans in procedure (`bplan:a_bp_iv`) and in force (`bplan:b_bp_fs`)
  that the WFS returns for the square around the 500 m circle around Freiheit 22, 13597
  Berlin, 2026-10-14: roughly those whose bounds overlap the square. The WFS also returns
  plans a few metres beyond it, such as VIII-B4.

Data: Geoportal Berlin, B-Plan WFS, licence dl-de/zero-2.0.
