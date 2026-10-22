# Nominatim fixtures

Recorded Nominatim search responses, kept as returned on 2026-10-10:

- `freiheit-22.json`: "Freiheit 22, 13597 Berlin", one building, the E1 candidate.
- `freiheit-street.json`: "Freiheit, Berlin", streets only.
- `hauptstrasse-1.json`: "Hauptstraße 1, Berlin", several buildings.

Recorded on 2026-10-14:

- `hauptstrasse-1-staaken.json`: "Hauptstraße 1, 13591 Berlin", one of them, in Staaken (I2).
- `huttenstrasse-10.json`: "Huttenstraße 10, 10553 Berlin", one building, but in Frohnau with
  the postcode 13465, not in Moabit.

Recorded on 2026-10-15:

- `karl-marx-allee-3.json`: "Karl-Marx-Allee 3, 10178 Berlin", one building, a destination
  (I1).
- `am-kanal-47-potsdam.json`: "Am Kanal 47, 14467 Potsdam", one building in Brandenburg, a
  destination outside Berlin (I3).

Recorded on 2026-10-16 by `evals/label.py`, one building each, the end-to-end addresses:

- `e1-freiheit-22.json`: "Freiheit 22, 13597 Berlin" (E1).
- `e2-neukoellnische-allee-52.json`: "Neuköllnische Allee 52, 12057 Berlin" (E2).
- `e3-corinthstrasse-60.json`: "Corinthstraße 60, 10245 Berlin" (E3).
- `e4-teutonenstrasse-10.json`: "Teutonenstraße 10, 12524 Berlin" (E4).
- `e5-am-bruchland-22.json`: "Am Bruchland 22, 12524 Berlin" (E5).

Recorded on 2026-10-22 during address selection, kept without another live call:

- `e6-oberhofer-weg-45.json`: "Oberhofer Weg 45, 12209 Berlin" (E6), one building.
- `e7-teltower-strasse-31.json`: "Teltower Straße 31, 14109 Berlin" (E7), two different
  places: way 191355292 in Steinstücken, 14109, and node 2875569798 in Wilhelmstadt, 13597.
  Production geocoding keeps them separate, then selects Steinstücken by the requested
  postcode 14109.

Data © OpenStreetMap contributors, available under the Open Database License (ODbL) 1.0:
<https://www.openstreetmap.org/copyright>.
