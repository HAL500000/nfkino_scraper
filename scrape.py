#!/usr/bin/env python3
"""
scrape.py — henter kinoprogrammet for Oslo fra nfkino.no og skriver program.json.

Kjøres av GitHub Actions et par ganger om dagen. Ingen tredjepartspakker,
kun Python 3 standardbibliotek.

    python3 scrape.py --out program.json
"""

import argparse
import gzip
import html as htmllib
import io
import json
import os
import re
import ssl
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://www.nfkino.no"
CITY = "oslo"
INDEX_PATHS = ["/filmer?city={city}", "/?city={city}"]
MAX_FILMS = 300
WORKERS = 5
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")


# --------------------------------------------------------------------- fetch
def fetch(url, timeout=30, retries=2):
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "nb-NO,nb;q=0.9,no;q=0.8,en;q=0.5",
                "Accept-Encoding": "gzip",
            })
            with urllib.request.urlopen(req, timeout=timeout,
                                        context=ssl.create_default_context()) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                return raw.decode(r.headers.get_content_charset() or "utf-8",
                                  errors="replace")
        except Exception as exc:                       # noqa: BLE001
            last = exc
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError("klarte ikke hente %s: %s" % (url, last))


# --------------------------------------------------------------------- parse
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean(s):
    if not s:
        return ""
    return WS_RE.sub(" ", htmllib.unescape(TAG_RE.sub(" ", s))).strip()


def parse_duration(s):
    """'2 timer 52 min' -> 172 ; '1 time 49 min' -> 109 ; '98 min' -> 98"""
    if not s:
        return None
    s = s.lower()
    h = re.search(r"(\d+)\s*tim", s)
    m = re.search(r"(\d+)\s*min", s)
    total = (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)
    if not h and not m:
        n = re.search(r"\d+", s)
        total = int(n.group(0)) if n else 0
    return total or None


def parse_index(html):
    slugs, seen = [], set()
    for m in re.finditer(r'href="[^"]*?/film/([A-Za-z0-9\-_%]+)', html):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            slugs.append(m.group(1))
    return slugs


RE_NID = re.compile(r'data-cinema-nid="(\d+)"')
RE_CNAME = re.compile(r'<div class="cinema-name">(.*?)</div>', re.S)
RE_DATE = re.compile(r'<time datetime="(\d{4}-\d{2}-\d{2})"')
RE_SHOW = re.compile(
    r'<a\s+href="([^"]*?/screening/[^"]*?)"\s*class="movies-screenings-button-link"\s*>(.*?)</a>',
    re.S)
RE_ROOM = re.compile(r'<div class="room">(.*?)</div>', re.S)
RE_TIME = re.compile(r'<div class="time">\s*<div>\s*(\d{1,2})[.:](\d{2})', re.S)
RE_VERSION = re.compile(r'<div class="version">(.*?)</div>', re.S)


def parse_film(html, slug):
    m = re.search(r'<h1[^>]*class="[^"]*node-title[^"]*"[^>]*>(.*?)</h1>', html, re.S)
    title = clean(m.group(1)) if m else ""
    if not title:
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
        title = clean(m.group(1)) if m else slug

    minutes = None
    m = re.search(r'field--name-field-duration(.{0,400}?)'
                  r'<div class="field__item">(.*?)</div>', html, re.S)
    if m:
        minutes = parse_duration(clean(m.group(2)))

    age = ""
    m = re.search(r'field--name-field-censur(.{0,600}?)vocabulary-movie-censur'
                  r'(.{0,300}?)field__item">(.*?)</div>', html, re.S)
    if m:
        age = clean(m.group(3))

    poster = None
    m = re.search(r'<img[^>]+src="([^"]*movie-poster[^"]*)"', html, re.I)
    if m:
        poster = m.group(1)
        if poster.startswith("/"):
            poster = BASE + poster

    screenings = []
    for chunk in html.split('<div class="cinema-shows-wrapper"')[1:]:
        nid, cname = RE_NID.search(chunk), RE_CNAME.search(chunk)
        if not nid or not cname:
            continue
        for slide in chunk.split('<div class="slide__content">')[1:]:
            d = RE_DATE.search(slide)
            if not d:
                continue
            for a in RE_SHOW.finditer(slide):
                inner = a.group(2)
                t = RE_TIME.search(inner)
                if not t:
                    continue
                room = RE_ROOM.search(inner)
                ver = RE_VERSION.search(inner)
                version = re.sub(r"\s*,\s*", ", ",
                                 clean(ver.group(1)) if ver else "").strip(" ,")
                screenings.append({
                    "slug": slug, "title": title, "minutes": minutes,
                    "age": age, "poster": poster,
                    "cinemaId": nid.group(1), "cinema": clean(cname.group(1)),
                    "date": d.group(1),
                    "startMin": int(t.group(1)) * 60 + int(t.group(2)),
                    "room": clean(room.group(1)) if room else "",
                    "version": version, "url": a.group(1),
                })

    return {"slug": slug, "title": title, "minutes": minutes,
            "age": age, "poster": poster, "screenings": screenings}


# --------------------------------------------------------------------- build
def build(log=print):
    slugs = []
    for path in INDEX_PATHS:
        try:
            slugs = parse_index(fetch(BASE + path.format(city=CITY)))
        except Exception as exc:                       # noqa: BLE001
            log("  oversikt feilet (%s): %s" % (path, exc))
            continue
        if slugs:
            log("  fant %d filmlenker via %s" % (len(slugs), path))
            break
    if not slugs:
        raise RuntimeError("fant ingen filmer på nfkino.no")
    links_found = len(slugs)
    if links_found > MAX_FILMS:
        log("  ADVARSEL: kutter fra %d til %d filmer (MAX_FILMS)" % (links_found, MAX_FILMS))

    def one(slug):
        try:
            return parse_film(fetch("%s/film/%s?city=%s" % (BASE, slug, CITY)), slug)
        except Exception as exc:                       # noqa: BLE001
            log("  hoppet over %s: %s" % (slug, exc))
            return None

    films = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for res in pool.map(one, slugs[:MAX_FILMS]):
            if res and res["screenings"]:
                films.append(res)
    if not films:
        raise RuntimeError("ingen visninger funnet")

    screenings = [s for f in films for s in f["screenings"]]
    screenings.sort(key=lambda s: (s["date"], s["startMin"], s["title"]))

    cinemas, seen = [], set()
    for s in screenings:
        if s["cinemaId"] not in seen:
            seen.add(s["cinemaId"])
            cinemas.append({"id": s["cinemaId"], "name": s["cinema"]})
    cinemas.sort(key=lambda c: c["name"])

    log("  %d filmer, %d visninger, %d kinoer"
        % (len(films), len(screenings), len(cinemas)))
    for c in cinemas:
        log("    - %s" % c["name"])

    return {
        "generated": int(time.time()),
        "city": CITY,
        "linksFound": links_found,
        "truncated": links_found > MAX_FILMS,
        "films": [{k: f[k] for k in ("slug", "title", "minutes", "age", "poster")}
                  for f in films],
        "cinemas": cinemas,
        "screenings": screenings,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="program.json")
    args = ap.parse_args()

    print("Henter kinoprogram fra nfkino.no …")
    data = build()

    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    os.replace(tmp, args.out)
    print("Skrev %s (%.1f kB)" % (args.out, os.path.getsize(args.out) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
