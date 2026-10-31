import argparse, os
from . import search

ap = argparse.ArgumentParser(prog="pinterest-taste", description="Pinterest search ranked by taste")
ap.add_argument("query")
ap.add_argument("--limit", type=int, default=60, help="pins to fetch")
ap.add_argument("--top", type=int, default=20, help="pins to keep")
ap.add_argument("--cookies", default="cookies.txt")
ap.add_argument("--save", metavar="DIR", help="save the top images here")
a = ap.parse_args()
rows = search(a.query, a.limit, a.top, a.cookies)
if a.save:
    os.makedirs(a.save, exist_ok=True)
for i, r in enumerate(rows, 1):
    print(f"{r['score']:.3f}  {r['id']}  {r['url']}")
    if a.save:
        r["image"].save(f"{a.save}/{i:02d}_{r['score']:.3f}_{r['id']}.jpg", quality=92)
