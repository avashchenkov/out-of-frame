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

Data © OpenStreetMap contributors, available under the Open Database License (ODbL) 1.0:
<https://www.openstreetmap.org/copyright>.
