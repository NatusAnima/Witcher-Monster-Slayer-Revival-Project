# OpenStreetMap encoder and retained integration record

For current setup, index generation, public routing and placement configuration, use the [OSM operator guide](../../../docs/MAPS.md). The following page retains codec details and the LAB 13–15 integration experiments.

This sidecar replaces the retired Google Semantic Tile service with FeatureTiles generated from OpenStreetMap data. Coverage depends on the regional index or optional Overpass fallback. The encoder and sidecar remain in use; the client examples below preserve the LAB 13–15 integration checkpoints. For current builds and configured HTTPS endpoints, use the [client guide](../../../client/README.md).

- **LAB 14 / LAB 15** (standalone): a client build whose tile host points at the sidecar, so the map loads without a Frida script or a workstation attach. LAB 14 reaches a workstation sidecar through `adb reverse`; LAB 15 reaches a sidecar on the Debian host through WireGuard. See [Iteration 39](../../../docs/ITERATION-39.md).
- **LAB 13 with Frida**: the tile redirect is done at run time by [redirect_map_osm_live01.js](../../../client/redirect_map_osm_live01.js), which also offers render counters and mask diagnostics.

Result on the Android test device: the world map shows the OSM street network, parks and forests, water bodies and buildings around the player. See [Iteration 37](../../../docs/ITERATION-37.md) for roads and [Iteration 38](../../../docs/ITERATION-38.md) for land cover, water and buildings.

## Components

| File | Role |
| --- | --- |
| [osm_extract_index.py](osm_extract_index.py) | Builds a SQLite R-tree from a regional `.osm.pbf` extract: highway and river/canal lines, plus park, forest, beach, water and building areas, including multipolygon relations. Needs `pip install osmium` only for building; reading uses the standard library. |
| [osm_area_geometry.py](osm_area_geometry.py) | Clips polygons to the tile, triangulates them (Python port of mapbox/earcut, ISC) and encodes `Area` and `ExtrudedArea` messages. |
| [osm_live_codec.py](osm_live_codec.py) | Encodes one FeatureTile per request. Every feature has a unique `placeId`; street and area names are sent as `displayName`. Also contains the grid and area canaries. |
| [osm_live_sidecar.py](osm_live_sidecar.py) | HTTP server for `/lab/feature-tile/{z}/{x}/{y}` (Frida redirect) and `/v1/featuretiles/@{x},{y},{z}z` (LAB 14; the query string is ignored). Listens on loopback unless `--bind` says otherwise. Sources: the local index (queried per tile), the Overpass API as a roads-only fallback, or synthetic canaries. |
| [redirect_map_osm_live01.js](../../../client/redirect_map_osm_live01.js) | Probe 06 without the redirect caps, plus aggregate render-pipeline counters mirrored to logcat (tag `OSMLAB`) and optional terrain-mask diagnostics. |
| [repack_local14_maptiles.py](../../../client/repack_local14_maptiles.py) | Builds an unsigned standalone APK (LAB 14, LAB 15, …) from the pinned LAB 13 APK: plain HTTP for map tiles, the tile host literal replaced, Gadget no longer waiting at start. |
| [osm-live-tiles.service](osm-live-tiles.service) | systemd user unit that runs the sidecar on a server's private network address for one admitted client (LAB 15). |

The OSM-to-game class mapping is authored for this LAB; it is not recovered game data.

Only ArterialRoad and Highway segments are moved by the client to layer 16 (`MapPresentationLayer` segment `DidCreate`), which feeds the big-road mask and draws the wide paved band; all other roads are thin paths. Reference screenshots show that band on major roads and on the main alleys and a cycle path in the Silesian Park, while town streets are thin, hence the promotions and demotions in the table (`road_feature_type` in `osm_live_codec.py`). The index keeps `surface` and `width` for this decision.

Two filters bring OSM closer to the one-line-per-street look of the original Google data, as seen in reference gameplay screenshots:

- The index skips separately mapped sidewalks and crossings (`footway=sidewalk/crossing/...`), parking aisles and driveways (`service=parking_aisle/driveway/...`) and highway areas (`area=yes`, whose outline would draw as a path). In Wielkopolska this removes about 101,000 of 472,000 highway ways.
- The encoder drops paths (`highway=footway/path/cycleway/steps/bridleway`, judged by their OSM class, so promoted cycleways are included) that mostly run alongside a street: at least 60 % of their sampled length within 15 m of, and within 25° of, a street segment in the same tile. Park paths and crossings remain.

| Game feature | FeatureType | OSM source |
| --- | --- | --- |
| Highway (wide paved band) | 532 | `motorway`, `trunk`, `primary` and their links |
| Arterial road (wide paved band) | 531 | `secondary`; `pedestrian` streets and main park alleys; `cycleway`; named or ≥ 3 m wide paved `footway`/`path` |
| Local road (thin) | 530 | `tertiary`, `unclassified`, `residential`, `living_street`, `service`, `road`, `track` |
| Footpath (thin) | 34 | other `footway`, `path`, `steps`, `bridleway` |
| Park | 49 | `leisure=park/garden/golf_course/recreation_ground/common`, `landuse=recreation_ground`; at least 2,500 m² |
| Forest | 51 | `landuse=forest`, `natural=wood`; at least 2,500 m² |
| Beach | 50 | `natural=beach`; at least 1,000 m² |
| Water area | 4 (areas) | `natural=water`, `landuse=reservoir/basin`, `waterway=riverbank/dock`; at least 150 m² |
| River line | 4 (lines) | `waterway=river/canal` |
| Building | 1 (extruded area) | `building=*` except `no` |

## Why the map was empty before

Each blocker was confirmed on the device:

1. **Coverage.** The client requests about 220 z17 tiles within the 1 km `MapSettings.MaxDistance`. The fixed Poznań pack answered almost all of them with 404.
2. **Loading stalls.** The client opens about 100 tile connections at once through `adb reverse`. With the `socketserver` default listen backlog of 5, requests reached the server only after the client's 40 s curl timeout, and loading stopped at "Ładujemy mapę 56%". The sidecar uses a backlog of 1024 and never blocks a request on a slow fetch.
3. **One feature per tile.** `GameObjectManager` keeps one GameObject per `(tile, placeId)` and skips repeated IDs, so features without `placeId` collapsed to the first one per tile.

Roads, land cover and buildings become GameObjects, and the `MapLoaded` handler then enables two orthographic cameras that render them into 2048×2048 terrain masks. The mask render uses the replacement shader `Witcher/Map/One_color_replacement`, which outputs `vertex colour × material _Color`:

| Mask | Channel | Written by | Read by |
| --- | --- | --- | --- |
| `map_global_mask_1` | R | Park/forest/beach regions (`forest` material) | `Map_plane` tree texture (threshold 0.53) |
| | G | Roads (`small_road` material) | `Map_plane` road texture (threshold 0.906) |
| | B | Buildings (`building` material) | grass/building shading (threshold 0.946) |
| | A | Cleared to 1; water areas lower it toward 0 away from the shore | `Map_plane` shore blend and the animated `Witcher/Map/water` plane (visible below about 0.59) |
| `map_global_mask_2` | G | Layer-16 objects | `Map_plane` big-road texture |

The replacement shader writes the flat material colour, but the dumped masks have soft transitions tens of metres wide: every region, road and water body produces a halo, including outside its own outline. Two consequences drove the class filters above:

- Park halos accumulate. With every OSM lawn, meadow, playground and pitch classified as a park, the halos merged into one green blanket over the city and hid the river corridor. Keeping only real parks (122,497 → 1,478 areas in Wielkopolska) restores the look of the reference screenshots, where green regions are limited to parks and forests.
- Water shows only where the alpha channel falls well below 0.59. Lakes (for example Malta in Poznań) render fully; a river about 70 m wide reaches only about 0.47 in its centre and appears as a faint band, and dense paths along embankments further reduce the water plane (its factor is multiplied by `3 − 3·G`). Ponds narrower than about 30 m stay grass. Water areas need `has_external_edges`: the same areas without edge flags produced no water at all on the device.

The encoder marks edges created by tile clipping as internal (`Area.internal_edges`) so that tile borders do not become artificial shores.

Area wire format (from `Area.WriteTo` and its codecs): 2 vertex offsets, 3 type (`IndexedTriangles` = 1), 4 triangle indices, 5 z-order, 6 loop breaks (ring end indices), 7 `has_external_edges`, 8 internal edges. `Geometry` uses 1 areas, 2 lines, 3 extruded areas; `ExtrudedArea` uses 1 area, 2 `min_z`, 3 `max_z`. Equal heights make the client use its 10 m default. A Region feature without any area makes `DecodeRegionishArea` throw, so the encoder drops features whose clipped geometry is empty.

## Run it

From the prototype directory, once per region (the extract and index stay local under `server/data/`, which is excluded from Git):

```sh
mkdir -p server/data/osm-extract-01
curl -L -o server/data/osm-extract-01/region-latest.osm.pbf \
  https://download.geofabrik.de/europe/poland/wielkopolskie-latest.osm.pbf
python -m venv /tmp/osm-build && /tmp/osm-build/bin/pip install osmium
/tmp/osm-build/bin/python server/connection/map-road-fixture-01/osm_extract_index.py \
  --input server/data/osm-extract-01/region-latest.osm.pbf \
  --output server/data/osm-extract-01/region-features-v4.sqlite
```

Pick the Geofabrik extract that contains the test location. The Wielkopolskie extract (about 160 MB) indexes in about 90 seconds into a 370 MB database with 0.47 million highway ways and 2 million areas, most of them buildings.

Start the sidecar on the workstation port that the device's `tcp:18081` reverse mapping points to (18082 in the Debian route):

```sh
python server/connection/map-road-fixture-01/osm_live_sidecar.py --port 18082 \
  --index server/data/osm-extract-01/region-features-v4.sqlite
```

A z17 tile takes about 5–15 ms to query and encode. Without `--index`, or for areas outside the extract, the sidecar queries the public Overpass API once per z15 area for roads only and caches the result in `server/data/osm-live-cache-01/`. Public Overpass instances often return 504 under load; use the local index for play sessions and `--offline` to forbid network fetches.

### Standalone client (LAB 14)

Build LAB 14 once for the tile host the device will reach (at most 25 characters, because the host replaces a 25-byte string literal in place), sign it with the local LAB key and install it as an update:

```sh
cd client
python3 repack_local14_maptiles.py --tile-host 127.0.0.1:18081
PATH="$PATH:$ANDROID_BUILD_TOOLS" python3 sign_lab_apk.py local14-maptiles
adb -s "$LAB_SERIAL" install -r --no-incremental lab-1116-local14-maptiles.apk
adb -s "$LAB_SERIAL" reverse tcp:18081 tcp:18082
```

Unity extracts `global-metadata.dat` to `Android/data/<LAB package>/files/il2cpp/` on the first start and keeps using that copy after an update install, so the new tile host is ignored until the copy is gone. The extracted directories are not writable by the ADB shell, but their parent is, so move the whole directory aside while LAB is stopped (the next start extracts the patched file):

```sh
adb -s "$LAB_SERIAL" shell mv /sdcard/Android/data/<LAB package>/files/il2cpp \
  /sdcard/Android/data/<LAB package>/files/il2cpp.stale
```

Then start the Debian bridge for the game server as usual and launch LAB 14 from the launcher; no Frida runner is needed for the map.

Install with `--no-incremental`. A default incremental install returns before the 2.4 GB APK has been copied to the device and streams the rest in the background; LAB 15 crashed with SIGTRAP in Unity's `Loading.Preload` thread when started during that phase, and it depends on the workstation until streaming ends.

### Sidecar on a server over WireGuard (LAB 15)

The sidecar can run on another host that the device reaches through a private network. It refuses to listen outside loopback without `--allow-client`, and it closes connections from any other source address before reading the request. Run it with `--offline` so that tile bounds are never sent to a public Overpass instance.

1. Copy `osm_live_sidecar.py`, `osm_live_codec.py`, `osm_extract_index.py`, `osm_area_geometry.py`, `osm_tile_codec.py` and `road_tile_codec.py` to `~/.local/share/monster-slayer-lab/osm-live/code/` on the server, and the index to `…/osm-live/data/`. Python 3.10 or later is enough; the reader has no third-party dependencies.
2. Create `~/.config/monster-slayer-osm-tiles.env` (mode 600) with `OSM_BIND` (the server's tunnel address), `OSM_PORT`, `OSM_CLIENT` (the device's tunnel address) and `OSM_INDEX` (absolute path of the index).
3. Install [osm-live-tiles.service](osm-live-tiles.service) to `~/.config/systemd/user/` and run `systemctl --user enable --now osm-live-tiles.service`. The account needs lingering (`loginctl show-user ACCOUNT_NAME -p Linger`, replacing `ACCOUNT_NAME` locally) to start the unit at boot. The unit retries every 15 s while the tunnel address does not exist yet.
4. Build the client for that address, for example `repack_local14_maptiles.py --tile-host <OSM_BIND>:<OSM_PORT> --variant local15-wgtiles --lab 15`, then sign it, install it and move the extracted `il2cpp` directory aside as above.

The event records go to the user journal (`journalctl --user -u osm-live-tiles`) and contain no addresses. Health checks from the server itself work because the unit also admits `OSM_BIND`. Connections from other peers only raise the `refused_client` counter.

### LAB 13 with the Frida redirect

Start the Debian bridge as usual and launch LAB with the live script (the device wrapper still pins probe 06, so call the runner directly):

```sh
cd client
.venv/bin/python run_instrumented_interactive01.py osmlive-example \
  --adb "$LAB_ADB" --serial "$LAB_SERIAL" \
  --script redirect_map_osm_live01.js --external-forward --until-stop
```

The client keeps a disk cache of tiles in its external cache directory (`Android/data/<LAB package>/cache/Google.Maps/Feature/`). Tiles served by earlier fixtures stay there and are decoded instead of requested. Delete that directory while LAB is stopped when switching tile sources or index versions.

With the live script, render counters are available during the session (LAB 14 has none; use the sidecar's `/health` counters):

```sh
adb -s "$LAB_SERIAL" logcat -s OSMLAB:I
```

## Diagnostics

- `--grid-canary H,V,D` serves an invented road grid with the given `FeatureType` values.
- `--only-kinds road,water,...` keeps only the listed classes from the real index (`road`, `water_line`, `water`, `park`, `forest`, `beach`, `building`), which isolates one class in the mask.
- `--area-canary river` serves an invented river strip crossing every tile plus a small lake.
- `--area-canary [KINDS[:CELL]]` serves invented land-cover shapes: forest squares, park octagons, water triangles, building squares and beach plus signs, cycling per cell (default cell 512 tile units). For example, `--area-canary water,forest:2048` gives large areas.
- Setting `OSMLAB_DIAGNOSTICS = true` in the live script adds main-thread snapshots of the map plane, water plane and mask cameras, and writes both terrain masks as PNG files to the app's external files directory about 15 seconds and about 100 seconds after start. These main-thread calls are for diagnostic runs only.

Clear the client tile cache after any canary run.

## Privacy and licensing

The sidecar's event records contain request numbers, status, byte and feature counts, and zoom level; they never contain tile addresses, coordinates or paths. The index, the Overpass cache and any mask dumps contain map data for the areas used and stay local. The Overpass fallback sends the bounding box of the requested area to the selected public endpoint; the local index does not.

Tiles are derived from OpenStreetMap data (© OpenStreetMap contributors, ODbL 1.0) and carry that attribution in `ProviderInfo`. Distributing generated tiles or indexes requires ODbL attribution and share-alike compliance.

## Tests

```sh
cd server/connection/map-road-fixture-01
python -m unittest test_osm_live_codec test_osm_live_sidecar test_osm_extract_index test_osm_area_geometry -v
```

These 37 tests use invented data and the standard library only. They cover place IDs, road class promotion and demotion, the street-parallel footpath filter, the sidewalk tag filter, the region class and size filter, the external-edge switch, clipping, earcut area correctness with holes, internal tile-border edges, extruded areas, feature ordering, the canaries, routing of both path forms, the client allowlist, the listen backlog, fail-fast 503 handling, address- and query-free event records and the index reader. They do not run the Unity client.

## Limits

- Classification is authored: parks, forests and beaches share the game's single region material, so they look the same.
- Small ponds and narrow rivers do not reach the water threshold; rivers mapped only as lines use the game's 30 m river width. OSM has more embankment paths than the original data, which further weakens urban rivers.
- The Overpass fallback has no areas.
- The historical LAB 14/15 builders below have a fixed tile host of at most 25 characters and use plain HTTP (inside the tunnel for LAB 15). They changed only the map and still needed the workstation game bridge. Later standalone builds configure game, news and HTTPS map endpoints separately; see the [client guide](../../../client/README.md).
- Rendering was verified on one device around one location. Quest route construction was not tested.

## Current HTTPS relay and update checks

The [LAB 28 acceptance](../../../docs/ORIGINAL-ASSETS-LAB28-20261003.md) found two
retained issues that can leave a working game session without roads or buildings.
First, compare the extracted LAB `global-metadata.dat` hash with the payload in
the installed APK: a data-retaining update can keep an older tile host. Stop only
the LAB application and retain the stale metadata/cache directories under fresh
names before allowing Unity to regenerate them. Do not reset the player profile
or touch the original game package.

Second, the sidecar sees the HTTPS relay's source address, rather than the phone's
address. Its repeated `--allow-client` options must include that explicitly
configured private relay peer while preserving existing clients and local health
access. An active sidecar whose `refused_client` counter rises can make the proxy
return 502. Validate the proxy route, nonempty feature responses and visible
phone geometry separately; HTTP 200 alone is not a rendering check. Preserve the
original unit and use a dedicated reversible drop-in for an added relay peer.
