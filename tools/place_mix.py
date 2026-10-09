"""Report the places the placement service draws around chosen spots of a map index: how many each map cell gets and
which ground they lie on (paths, parks, woods, water, urban), against the shares of the dashboard's Tuning page.

  local/venv/Scripts/python tools/place_mix.py --index local/maps/israel-features.sqlite
      [--tuning local/server116/world/tuning.json] [--at "Name=32.0804,34.7806" ...]

Each spot is its map cell and the eight around it, for today's places. Without --at it uses a few Israel spots (a city
centre, a suburb, towns by woods, a forest edge, a coast). Without --tuning it uses the defaults.
"""
import argparse, collections, os, sys, time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "server", "connection", "map-road-fixture-01"))
import playable_locations as pl  # noqa: E402
import s2cells  # noqa: E402
from osm_extract_index import FeatureIndex  # noqa: E402

SPOTS = {
    "Tel Aviv centre": (32.0804, 34.7806), "Kfar Saba (suburb)": (32.1750, 34.9069),
    "Jerusalem centre": (31.7857, 35.2007), "Ein Kerem (forest edge)": (31.7647, 35.1568),
    "Zichron Yaakov (town by woods)": (32.5700, 34.9500), "Mevaseret Zion (town by woods)": (31.8000, 35.1500),
    "Haifa (coast)": (32.8180, 34.9580),
}


def mix(counts):
    total = sum(counts.values()) or 1
    return "  ".join(f"{ground} {100 * counts[ground] / total:3.0f}%" for ground in pl.MIX)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--index", required=True, help="a map index built by osm_extract_index.py")
    ap.add_argument("--tuning", type=Path, help="a world/tuning.json (the defaults without it)")
    ap.add_argument("--at", action="append", metavar="NAME=LAT,LNG", help="a spot to look at (repeatable)")
    args = ap.parse_args()
    service = pl.PlayableLocations(FeatureIndex(args.index), tuning_path=args.tuning)
    spots = {name: tuple(map(float, at.split(","))) for name, at in (a.split("=", 1) for a in args.at)} if args.at else SPOTS
    tuning = service.tuning.values()
    shares = {ground: tuning["places." + ground] for ground in pl.MIX}
    print(f"{'shares':32s} {'':18s}{mix(shares)}   ({tuning['places.perCell']} places a cell at "
          f"{tuning['places.spacing']} m, {tuning['places.streetClearance']} m from streets)")
    epoch, everywhere = int(time.time() // 86400), collections.Counter()
    for name, (lat, lng) in spots.items():
        counts, cells = collections.Counter(), 0
        cell = s2cells.cell_of(lat, lng, pl.CELL_LEVEL)
        for cell_id in [cell] + s2cells.neighbors(cell):
            places = service.cell(cell_id, epoch)
            counts.update(p["ground"] for p in places)
            cells += 1
        everywhere += counts
        print(f"{name:32s} {sum(counts.values()) / cells:5.1f} a cell     {mix(counts)}")
    print(f"{'all spots':32s} {'':18s}{mix(everywhere)}")


if __name__ == "__main__":
    main()
