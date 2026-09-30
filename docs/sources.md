# Sources

Where the agent's facts come from. Code calls the map, plan and transit sources with fixed
queries. Web search is the model's only tool (see [architecture.md](architecture.md)).

| Source | What it gives | Called by | Key |
|---|---|---|---|
| Nominatim | coordinates of an address | code | none |
| Overpass | map elements in a circle around a point | code | none |
| Berlin B-Plan WFS | development plans in a rectangle | code | none |
| Transitous | public transport journeys | code | none |
| Tavily | web search results | the model | required |

## Nominatim

Geocoding over OpenStreetMap data. Public instance at
`https://nominatim.openstreetmap.org/search`. A call returns the places that match an address,
with their coordinates.

[Search](https://nominatim.org/release-docs/latest/api/Search/) returns a list of matches,
which can be empty. A match can be a building, a street or a whole district, so coordinates
alone do not mean the address was found. Several matches can be different places. An empty
list means no match, not that the service is down.

## Overpass

A query service over OpenStreetMap data. Public instance at
`https://overpass-api.de/api/interpreter`. A call takes a query in Overpass QL and returns the
matching elements with their tags. The default response is XML; `[out:json]` gives JSON. The
`around:` filter selects a circle: each checklist class gets its own radius, in metres. The
main OSM API is for map editing and cannot filter by tag or distance.

A response lists OSM elements, not objects: one site can be several elements, and a road or
a railway is many segments. The elements are not sorted by distance, and `out tags` returns
no geometry. The public instance is often busy and answers 429 or 504. After a timeout it can
return a cut-off result with a `remark` field, which code must treat as a failure. See the
[Overpass spike](../spikes/overpass-counts/findings-2026-09-25.md).

## Berlin B-Plan WFS

Berlin's development plans (B-Plan, from Bebauungsplan) as an OGC Web Feature Service at
`https://gdi.berlin.de/services/wfs/bplan`. It has one feature type per procedure status:
`bplan:a_bp_iv` (in procedure), `bplan:b_bp_fs` (in force) and `bplan:c_bp_ak` (no longer in
force). A `GetFeature` call with a bounding box returns plan areas with their attributes,
such as `bp_rechtsstand`, the status. It filters only by this rectangle, so code drops the
plans outside the class's circle. The default response is GML; `outputFormat=application/json`
gives GeoJSON. The default coordinate system is EPSG:25833; EPSG:4326 is also accepted.

A B-Plan sets the permitted use of land. It does not show whether building has started or
finished; that is a question for the investigation.

## Transitous

A journey planner (MOTIS 2) run by volunteers on a best-effort basis, at
`https://api.transitous.org/api/`. For Germany it uses the official DELFI timetable data and
other open feeds, and OpenStreetMap for streets. A call returns journeys between two points
at a given time, with their legs and transfers. It covers the whole Berlin network, buses and
trams included, without an access agreement.

## Tavily

A web search API. The model calls `TavilySearch` from `langchain-tavily`. A call returns pages
with their URL, title and a content snippet. The package also offers other tools, such as
extract and crawl; this project does not use them.

## Data rights

- **OpenStreetMap data** (Nominatim, Overpass) is under the ODbL. Public output credits
  "© OpenStreetMap contributors" and links to <https://www.openstreetmap.org/copyright>. A
  report is a Produced Work and does not have to use the ODbL. Share-alike applies if a
  database derived from OSM data is published: check this before publishing stored source
  responses, for example in eval results.
- **Berlin B-Plan WFS:** licence `dl-de/zero-2.0`, no conditions.
- **Transitous:** no commercial use; the project's code must be open source; a visible link to
  <https://transitous.org/sources/>, and the licences of those sources, OpenStreetMap
  included.
- **Tavily:** a commercial API under its own terms. Each returned page keeps the rights of its
  site.
