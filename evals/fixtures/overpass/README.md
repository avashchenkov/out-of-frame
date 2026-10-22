# Overpass fixtures

Recorded Overpass API responses, kept as returned:

- `l1-way-985575964.json`: the L1 object and the addresses inside it, 2026-10-03.
- `freiheit-22.json`: the map objects of every category around Freiheit 22, 13597 Berlin,
  the E1 candidate, 2026-10-10.
- `freiheit-22-addresses.json`: the addresses inside the five nearest industrial objects
  there, from one query, 2026-10-13.

Recorded on 2026-10-16 by `evals/label.py`: the map objects of every category around each
end-to-end address, from which its labels were written. Named after the address, with the
task first, such as `e1-freiheit-22.json` for E1; the addresses are in
`../nominatim/README.md`.

Recorded on 2026-10-22 by the production map query during the held-out address preflight:

- `e6-oberhofer-weg-45.json`: Heizkraftwerk Lichterfelde; the other map categories are empty.
- `e7-teltower-strasse-31.json`: Katjes and two track elements grouped as railway ref 6118.

These are complete query responses, including the category counts and geometry. Both use
the OSM base timestamp 2026-10-22T15:31:05Z. No inside-building address query was recorded
for these fixtures; both industry objects already have street addresses in their own tags.

Map data © OpenStreetMap contributors, available under the Open Database License (ODbL) 1.0:
<https://www.openstreetmap.org/copyright>.
