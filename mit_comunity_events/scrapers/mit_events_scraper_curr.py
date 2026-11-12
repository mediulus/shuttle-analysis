#!/usr/bin/env python3
"""
MIT events scraper -> CSV files.

Collects three kinds of public MIT schedule data and writes them as CSV files:

  1. Varsity sports games/meets   (each team's schedule page on mitathletics.com)
  2. Academic calendar key dates  (registrar.mit.edu: holidays, breaks, exams, schedule swaps)
  3. Class meeting times          (Fireroad course feed, the same source the Hydrant planner uses)

plus summary CSVs (class start/end times, weekly busy hours, games by day and hour).

Output (in the --out folder, default mit_events_data/):
  sports_games.csv, academic_calendar.csv, class_meetings.csv,
  summary_class_start_end_times.csv, summary_class_busy_hours.csv, summary_games_by_day_hour.csv

Usage
-----
    pip install requests beautifulsoup4 pdfplumber
    python mit_events_scraper.py                       # writes CSVs to mit_events_data/
    python mit_events_scraper.py --past-calendars      # + 2021-22 .. 2025-26 calendars
    python mit_events_scraper.py --sports-since 2019   # + every team's past seasons since 2019
    python mit_events_scraper.py --calendar-pdfs ~/Downloads/Key_dates_2022-23.pdf
    python mit_events_scraper.py -o my_folder --save-html cache/
    python mit_events_scraper.py --skip classes        # skip a part (sports|calendar|classes)
    python mit_events_scraper.py --classes-json fireroad.json   # use a saved Fireroad dump

The script honours robots.txt, waits between requests (--delay), and identifies itself
with a generic User-Agent. If a page's layout changes, that part logs a warning and the
rest still runs; --save-html keeps every fetched page so you can see what came back.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.robotparser
from collections import Counter
from datetime import date, datetime, time as dtime
from pathlib import Path
from urllib.parse import urlparse

# config setup

ATHLETICS = "https://mitathletics.com"
CALENDAR_URL = "https://registrar.mit.edu/calendar/current-key-dates"
FIREROAD_URL = "https://fireroad.mit.edu/courses/all?full=true"

# (display name, URL slug) for every MIT sport 
SPORTS = [
    ("Baseball", "baseball"),
    ("Men's Basketball", "mens-basketball"),
    ("Women's Basketball", "womens-basketball"),
    ("Men's Heavyweight Crew", "mcrewhvy"),
    ("Men's Lightweight Crew", "mcrewlt"),
    ("Women's Lightweight Crew", "wcrewlt"),
    ("Women's Openweight Crew", "wcrewop"),
    ("Men's Cross Country", "mens-cross-country"),
    ("Women's Cross Country", "womens-cross-country"),
    ("Men's Fencing", "mens-fencing"),
    ("Women's Fencing", "womens-fencing"),
    ("Field Hockey", "field-hockey"),
    ("Football", "football"),
    ("Men's Lacrosse", "mens-lacrosse"),
    ("Women's Lacrosse", "womens-lacrosse"),
    ("Rifle", "rifle"),
    ("Sailing", "sailing"),
    ("Men's Soccer", "mens-soccer"),
    ("Women's Soccer", "womens-soccer"),
    ("Softball", "softball"),
    ("Men's Squash", "mens-squash"),
    ("Men's Swimming & Diving", "mens-swimming-and-diving"),
    ("Women's Swimming & Diving", "womens-swimming-and-diving"),
    ("Men's Tennis", "mens-tennis"),
    ("Women's Tennis", "womens-tennis"),
    ("Men's Track & Field", "mens-track-and-field"),
    ("Women's Track & Field", "womens-track-and-field"),
    ("Men's Volleyball", "mens-volleyball"),
    ("Women's Volleyball", "womens-volleyball"),
    ("Men's Water Polo", "mens-water-polo"),
]

USER_AGENT = "mit-events-scraper/1.0 (personal schedule research; python-requests)"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MONTH_RE = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|"
            r"Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)



class Fetcher:
    """requests session with robots.txt checks, a delay, and optional HTML caching."""

    def __init__(self, delay: float, save_dir: Path | None):
        import requests
        self.s = requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT
        self.delay = delay
        self.save_dir = save_dir
        self.robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._last = 0.0
        if save_dir:
            save_dir.mkdir(parents=True, exist_ok=True)

    def allowed(self, url: str) -> bool:
        host = urlparse(url).scheme + "://" + urlparse(url).netloc
        if host not in self.robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.s.get(host + "/robots.txt", timeout=20)
                rp.parse(r.text.splitlines() if r.ok else [])
            except Exception:
                rp.parse([])
            self.robots[host] = rp
        return self.robots[host].can_fetch(USER_AGENT, url)

    def get_bytes(self, url: str, name: str | None = None) -> bytes | None:
        if not self.allowed(url):
            log(f"  robots.txt disallows {url}; skipped")
            return None
        wait = self.delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        try:
            r = self.s.get(url, timeout=60)
            self._last = time.time()
            r.raise_for_status()
        except Exception as e:
            log(f"  failed {url}: {e}")
            return None
        if self.save_dir and name:
            (self.save_dir / name).write_bytes(r.content)
        return r.content

    def get(self, url: str, name: str | None = None) -> str | None:
        if not self.allowed(url):
            log(f"  robots.txt disallows {url}; skipped")
            return None
        wait = self.delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        try:
            r = self.s.get(url, timeout=60)
            self._last = time.time()
            r.raise_for_status()
        except Exception as e:
            log(f"  failed {url}: {e}")
            return None
        if self.save_dir and name:
            (self.save_dir / name).write_text(r.text, encoding="utf-8")
        return r.text


# Shared Parsing Tools

def parse_clock(text: str) -> dtime | None:
    """'6 p.m.', '6:00 PM', '12 Noon', '10:00 AM/6:00 PM' -> first time; None for TBA/All Day."""
    t = text.lower().replace(".", "")
    if "noon" in t:
        return dtime(12, 0)
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", t)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if h == 12:
        h = 0
    if ap == "pm":
        h += 12
    return dtime(h, mi)


def season_years(label: str) -> tuple[int, int] | None:
    """'2026' -> (2026, 2026); '2026-27' -> (2026, 2027)."""
    m = re.search(r"(20\d\d)(?:\s*[-–/]\s*(\d{2,4}))?", label)
    if not m:
        return None
    y1 = int(m.group(1))
    y2 = m.group(2)
    if not y2:
        return (y1, y1)
    y2 = int(y2) if len(y2) == 4 else int(str(y1)[:2] + y2)
    return (y1, y2)


def year_for(month: int, years: tuple[int, int]) -> int:
    """Within a split season (e.g. 2026-27), Jul-Dec belong to the first year."""
    y1, y2 = years
    return y1 if (y1 == y2 or month >= 7) else y2


# Sports

def parse_sidearm_classic(soup, years: tuple[int, int] | None) -> list[dict]:
    """Classic Sidearm Sports markup: <li class="sidearm-schedule-game ...">."""
    out = []
    for li in soup.select("li.sidearm-schedule-game"):
        classes = " ".join(li.get("class", []))
        ha = ("home" if "home-game" in classes else "away" if "away-game" in classes
              else "neutral" if "neutral-game" in classes else "")
        spans = [s.get_text(" ", strip=True) for s in
                 li.select(".sidearm-schedule-game-opponent-date span")]
        date_txt = spans[0] if spans else ""
        time_txt = spans[1] if len(spans) > 1 else ""
        dm = re.search(rf"({MONTH_RE})\.?\s+(\d{{1,2}})", date_txt)
        if not dm or not years:
            continue
        mon = MONTHS[dm.group(1)[:3].lower()]
        d = date(year_for(mon, years), mon, int(dm.group(2)))

        def txt(sel):
            el = li.select_one(sel)
            return el.get_text(" ", strip=True) if el else ""
        out.append(dict(date=d, time_raw=time_txt, start=parse_clock(time_txt),
                        event=txt(".sidearm-schedule-game-opponent-name"),
                        home_away=ha, location=txt(".sidearm-schedule-game-location"),
                        result=txt(".sidearm-schedule-game-result")))
    return out


def _iter_jsonld(obj):
    if isinstance(obj, list):
        for x in obj:
            yield from _iter_jsonld(x)
    elif isinstance(obj, dict):
        t = obj.get("@type", "")
        t = " ".join(t) if isinstance(t, list) else str(t)
        if "Event" in t:
            yield obj
        for k in ("@graph", "itemListElement", "item", "subEvent"):
            if k in obj:
                yield from _iter_jsonld(obj[k])


def parse_jsonld(soup) -> list[dict]:
    """schema.org SportsEvent entries embedded in the page (full dates with years)."""
    out = []
    for sc in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(sc.string or "")
        except Exception:
            continue
        for ev in _iter_jsonld(data):
            sd = str(ev.get("startDate", ""))
            m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?", sd)
            if not m:
                continue
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            st = None
            if m.group(4) and (m.group(4), m.group(5)) != ("00", "00"):
                st = dtime(int(m.group(4)), int(m.group(5)))
            loc = ev.get("location") or {}
            if isinstance(loc, list):
                loc = loc[0] if loc else {}
            loc_txt = loc.get("name", "") if isinstance(loc, dict) else str(loc)
            if isinstance(loc, dict) and isinstance(loc.get("address"), dict):
                a = loc["address"]
                extra = ", ".join(x for x in (a.get("addressLocality"), a.get("addressRegion")) if x)
                loc_txt = f"{loc_txt} ({extra})" if loc_txt and extra else (loc_txt or extra)
            name = str(ev.get("name", ""))
            home = ev.get("homeTeam") or {}
            home_name = home.get("name", "") if isinstance(home, dict) else str(home)
            ha = ""
            if home_name:
                ha = "home" if "MIT" in home_name or "Massachusetts Institute" in home_name else "away"
            elif re.search(r"\bat\b", name):
                ha = "away"
            elif re.search(r"\bvs\.?\b", name):
                ha = "home"
            out.append(dict(date=d, time_raw=sd, start=st, event=name, home_away=ha,
                            location=loc_txt, result=""))
    return out


def season_label(years: tuple[int, int] | None) -> str:
    if not years:
        return ""
    return f"{years[0]}" if years[0] == years[1] else f"{years[0]}-{str(years[1])[2:]}"


def parse_schedule_page(html: str):
    """-> (season years, games) for one team-season schedule page."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    label = " ".join(x.get_text(" ", strip=True) for x in soup.select("title, h1, h2")[:4])
    years = season_years(label)
    classic = parse_sidearm_classic(soup, years)
    ld = parse_jsonld(soup)
    if years:
        # Archive pages also embed the *current* season's events as structured data, so keep
        # only games dated inside the season the page is about.
        y1, y2 = years
        lo, hi = (date(y1, 1, 1), date(y1, 12, 31)) if y1 == y2 else (date(y1, 6, 1), date(y2, 8, 31))
        classic = [g for g in classic if lo <= g["date"] <= hi]
        ld = [g for g in ld if lo <= g["date"] <= hi]
    return years, soup, (classic if len(classic) >= len(ld) else ld)


SEASON_PATH = r"/sports/{slug}/schedule/((?:19|20)\d\d(?:-\d\d(?:\d\d)?)?)\b"


def past_season_urls(soup, slug: str, current: tuple[int, int] | None, since: int) -> list[tuple[str, str]]:
    """(season, url) for seasons from `since` up to (not incl.) the current one.
    First from the page's own season dropdown/links; otherwise built from the usual address."""
    rx = re.compile(SEASON_PATH.format(slug=re.escape(slug)))
    found = {}
    for el in soup.find_all(["option", "a"]):
        for attr in ("value", "href", "data-url"):
            m = rx.search(el.get(attr) or "")
            if m:
                found[m.group(1)] = f"{ATHLETICS}/sports/{slug}/schedule/{m.group(1)}"
    split = bool(current and current[0] != current[1])
    if not found and current:                       # build the addresses ourselves
        for y in range(since, current[0] + 1):
            key = f"{y}-{str(y + 1)[2:]}" if split else f"{y}"
            found[key] = f"{ATHLETICS}/sports/{slug}/schedule/{key}"
    out = []
    for key, url in found.items():
        yrs = season_years(key)
        if yrs and yrs[0] >= since and (not current or yrs != current) and (not current or yrs[0] <= current[0]):
            out.append((key, url))
    return sorted(out, key=lambda x: x[0])


def scrape_sports(f: Fetcher, only: set[str] | None, since: int | None = None) -> list[dict]:
    rows = []
    for name, slug in SPORTS:
        if only and slug not in only:
            continue
        url = f"{ATHLETICS}/sports/{slug}/schedule"
        log(f"sports: {name}")
        html = f.get(url, f"sport_{slug}.html")
        if not html:
            continue
        years, soup, games = parse_schedule_page(html)
        pages = [(url, years, games)]
        if since:
            past = past_season_urls(soup, slug, years, since)
            for key, purl in past:
                phtml = f.get(purl, f"sport_{slug}_{key}.html")
                pyears, pgames = None, []
                if phtml:
                    pyears, _, pgames = parse_schedule_page(phtml)
                want = season_years(key)
                if pyears != want:     # missing, or redirected to another season: try the other address style
                    alt = (f"{want[0]}" if want[0] != want[1] else f"{want[0]}-{str(want[0] + 1)[2:]}")
                    aurl = f"{ATHLETICS}/sports/{slug}/schedule/{alt}"
                    ahtml = f.get(aurl, f"sport_{slug}_{alt}.html")
                    if ahtml:
                        pyears, _, pgames = parse_schedule_page(ahtml)
                        purl = aurl
                    if not ahtml or not pyears or pyears[0] != want[0]:
                        log(f"  {key}: no archive page found")
                        continue
                pages.append((purl, pyears, pgames))
        total = 0
        for purl, pyears, pgames in pages:
            season = season_label(pyears)
            for g in pgames:
                g.update(sport=name, season=season, source_url=purl)
                rows.append(g)
            total += len(pgames)
        seasons = [f"{season_label(y) or '?'} ({len(g)})" for _, y, g in pages]
        if not total:
            log(f"  no games found on {url} (layout may have changed; try --save-html)")
            continue
        log(f"  {total} events, seasons {', '.join(seasons)}")
        for purl, y, g in pages[1:]:
            if not g:
                log(f"  no games read from {purl} (try --save-html and send me that page)")
    seen, uniq = set(), []
    for r in sorted(rows, key=lambda r: (r["date"], r["start"] or dtime(23, 59), r["sport"])):
        k = (r["sport"], r["date"], r["start"], r["event"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq


# Academic Calendar

CATEGORIES = [  # (keyword regex, category, means no regular classes)
    (r"summer session", "term", False),
    (r"half-term|\bh[1-4]\b.*exam", "halfterm_exams", False),   # regular classes continue
    (r"data entry|exam schedule|schedule (posted|published|available|displayed)", "admin", False),
    (r"final exam|exam period|examination", "exams", True),
    (r"spring break|vacation|break", "break", True),
    (r"holiday|labor day|indigenous|columbus|veterans|thanksgiving|martin luther|"
     r"presidents|patriots|memorial day|juneteenth|independence", "holiday", True),
    (r"schedule of classes|schedule swap", "schedule_swap", False),
    (r"commencement", "commencement", False),
    (r"registration", "registration", False),
    (r"add date|drop date|last day to (add|drop)|deadline", "deadline", False),
    (r"first day of (?:\w+ )?classes|begins|\bstart", "term_start", False),
    (r"last day of|\bends\b|end of", "term_end", False),
]


def categorize(event: str) -> tuple[str, bool]:
    e = event.lower()
    for rx, cat, off in CATEGORIES:
        if re.search(rx, e):
            # a "Monday schedule of classes" day is a normal class day
            return cat, off and "schedule of classes" not in e
    return "other", False


DATE_SPAN = re.compile(
    rf"(?P<m1>{MONTH_RE})\.?\s+(?P<d1>\d{{1,2}})(?:,?\s*(?P<y1>20\d\d))?"
    rf"(?:\s*(?:-|–|—|to|through|thru)\s*(?:(?P<m2>{MONTH_RE})\.?\s+)?(?P<d2>\d{{1,2}})"
    rf"(?:,?\s*(?P<y2>20\d\d))?)?", re.I)
TERM_RE = re.compile(r"\b(Fall|Spring|Summer|IAP|Independent Activities Period)\b[^0-9]{0,20}(20\d\d)", re.I)


def date_spans(text: str, years: tuple[int, int]) -> list[tuple[date, date]]:
    spans = []
    for m in DATE_SPAN.finditer(text):
        m1 = MONTHS[m.group("m1")[:3].lower()]
        y1 = int(m.group("y1") or m.group("y2") or year_for(m1, years))
        d1 = date(y1, m1, int(m.group("d1")))
        if m.group("d2"):
            m2 = MONTHS[m.group("m2")[:3].lower()] if m.group("m2") else m1
            y2 = int(m.group("y2") or (y1 if m2 >= m1 else y1 + 1))
            d2 = date(y2, m2, int(m.group("d2")))
        else:
            d2 = d1
        spans.append((d1, d2))
    return spans


def term_for(d: date, event: str = "") -> str:
    """MIT term a date belongs to (Jan = IAP, Feb-May = spring, Jun-Jul = summer, Aug-Dec = fall),
    with the event's own wording winning around the IAP/spring boundary."""
    e, m = event.lower(), d.month
    if m in (1, 2) and "iap" in e:
        return f"IAP {d.year}"
    if m == 1 and "spring" in e:
        return f"Spring {d.year}"
    kind = "IAP" if m == 1 else "Spring" if m <= 5 else "Summer" if m <= 7 else "Fall"
    return f"{kind} {d.year}"


def parse_registrar_table(main) -> list[dict]:
    """registrar.mit.edu key-dates layout (as of Nov 2026): one table whose rows are
    [year in <h4>] | [month (first row of that month only)] [day(s)] [weekday(s)] [event],
    with day cells like '7', '26-27' or '14, 17-19', and full spans like
    'June 7 - August 17' in a colspan cell."""
    rows, year, month = [], None, None
    for tr in main.select("table tr"):
        cells = [c.get_text(" ", strip=True).replace("\xa0", " ").strip() for c in tr.find_all(["td", "th"])]
        if not any(cells):
            continue
        h4 = tr.find("h4")
        if h4 and re.fullmatch(r"20\d\d", h4.get_text(strip=True)):
            year = int(h4.get_text(strip=True))
            continue
        if year is None:
            continue
        event = cells[-1].strip()
        if not event:
            continue
        first = cells[0]
        spans: list[tuple[date, date]] = []
        if DATE_SPAN.search(first) and re.search(r"\d", first):      # 'June 7 - August 17'
            spans = date_spans(first, (year, year))
        else:
            mm = re.fullmatch(MONTH_RE, first, re.I)
            if mm:
                month = MONTHS[first[:3].lower()]
            if month is None or len(cells) < 2:
                continue
            for part in re.split(r"\s*,\s*", cells[1]):              # '14, 17-19'
                dm = re.fullmatch(r"(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?", part)
                if dm:
                    d1 = date(year, month, int(dm.group(1)))
                    spans.append((d1, date(year, month, int(dm.group(2) or dm.group(1)))))
        cat, off = categorize(event)
        for d1, d2 in spans:
            rows.append(dict(start=d1, end=d2, term=term_for(d1, event), event=event, category=cat,
                             no_classes=off, raw=" | ".join(c for c in cells if c)))
    return rows


def parse_calendar(html: str) -> list[dict]:
    """Registrar table layout first; otherwise walk headings and table rows / list items
    in page order, tracking the current term."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("main") or soup.body or soup
    specific = parse_registrar_table(main)
    if len(specific) >= 3:
        return sorted(specific, key=lambda r: (r["start"], r["event"]))
    term, years = "", (date.today().year, date.today().year)
    rows = []
    use_tables = bool(main.select("table tr td"))
    tags = ["h1", "h2", "h3", "h4", "h5", "caption", "strong"] + (["tr"] if use_tables else ["li", "p"])
    for el in main.find_all(tags):
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        if el.name in ("h1", "h2", "h3", "h4", "h5", "caption", "strong"):
            tm = TERM_RE.search(text)
            if tm and len(text) < 60:
                kind = tm.group(1).title()
                kind = "IAP" if kind.lower().startswith(("iap", "independent")) else kind
                y = int(tm.group(2))
                term = f"{kind} {y}"
                years = (y, y)
            continue
        if el.name == "tr":
            cells = [c.get_text(" ", strip=True) for c in el.find_all(["td", "th"])]
            date_cells = [c for c in cells if DATE_SPAN.search(c)]
            if not date_cells:
                continue
            date_txt = date_cells[0]
            event = " — ".join(c for c in cells if c != date_txt and c)
        else:
            if el.find(["li", "p"]):      # skip containers; their children are visited
                continue
            date_txt = text
            event = DATE_SPAN.sub("", text)
            event = re.sub(r"^[\s,:;–—-]*(\((?:mon|tue|wed|thu|fri|sat|sun)[a-z]*(?:\s*[-–]\s*[a-z]+)?\))?[\s,:;–—-]*",
                           "", event, flags=re.I).strip(" :–—-")
        spans = date_spans(date_txt, years)
        if not spans or not event:
            continue
        cat, off = categorize(event)
        for d1, d2 in spans:
            rows.append(dict(start=d1, end=d2, term=term, event=event, category=cat,
                             no_classes=off, raw=text))
    seen, out = set(), []
    for r in rows:
        k = (r["start"], r["end"], r["event"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return sorted(out, key=lambda r: (r["start"], r["event"]))


# ---- past years: the registrar's "Key Catalog & Schedule Dates" PDFs -------------------
# Each PDF has one small table per month (Day | Date | Event) under a month label, and
# colour-codes rows by office: red = Academic Calendar, black = Committee on Curricula,
# green = Catalog, blue = Schedules. Add newer/older years with --calendar-pdfs.
KEY_DATES_PDFS = [
    "https://registrar.mit.edu/sites/default/files/2021-08/Key_catalog_and_schedules_dates_21-22.pdf",
    "https://registrar.mit.edu/sites/default/files/2022-09/Key_catalog_and_schedule_dates_2022-2023.pdf",
    "https://registrar.mit.edu/sites/default/files/2023-10/Key_catalog_and_schedule_dates_2023-2024.pdf",
    "https://registrar.mit.edu/sites/default/files/2024-08/Key_catalog_and_schedule_dates_2024-2025.pdf",
    "https://registrar.mit.edu/sites/default/files/2025-07/Key_catalog_and_schedule_dates_2025-2026.pdf",
]
OFFICE_COLORS = {
    "Academic Calendar": (0.75, 0.0, 0.0),
    "Committee on Curricula": (0.0, 0.0, 0.0),
    "Catalog": (0.0, 0.69, 0.31),
    "Schedules": (0.0, 0.44, 0.75),
}
FULL_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"]
DAY_NAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _rgb(ch) -> tuple | None:
    v = ch.get("non_stroking_color")
    if not isinstance(v, (list, tuple)) or not v:
        return None
    v = [float(x) for x in v]
    if len(v) == 1:
        return (v[0],) * 3
    if len(v) == 4:                                      # CMYK -> RGB
        c, m, y, k = v
        return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return tuple(v[:3])


def office_of(chars) -> str:
    """Office whose legend colour is nearest the most common text colour in a cell."""
    cnt = Counter(c for c in map(_rgb, chars) if c)
    if not cnt:
        return ""
    rgb = cnt.most_common(1)[0][0]
    return min(OFFICE_COLORS, key=lambda k: sum((a - b) ** 2 for a, b in zip(rgb, OFFICE_COLORS[k])))


def parse_key_dates_pdf(data: bytes, source: str) -> tuple[list[dict], list[str]]:
    import io
    import pdfplumber
    from datetime import timedelta
    rows, notes = [], []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        head = " ".join((p.extract_text() or "") for p in pdf.pages[:2])
        ym = re.search(r"Dates,?\s*((?:19|20)\d\d\s*[-–]\s*\d{2,4})", head) or re.search(r"(20\d\d\s*[-–]\s*\d{2,4})", head)
        if not ym:
            return [], [f"{source}: couldn't find the academic year in the title"]
        years = season_years(ym.group(1))
        label = f"{years[0]}-{str(years[1])[2:]}"
        month = None
        for page in pdf.pages:
            tables = sorted(page.find_tables(), key=lambda t: t.bbox[1])
            if not tables:
                continue

            def in_table(w):
                return any(t.bbox[0] - 1 <= w["x0"] and w["x1"] <= t.bbox[2] + 1 and
                           t.bbox[1] - 1 <= w["top"] and w["bottom"] <= t.bbox[3] + 1 for t in tables)
            outside = [w for w in page.extract_words() if not in_table(w)]
            labels = []
            for w in outside:
                if w["text"] in FULL_MONTHS:
                    same_line = [o for o in outside if abs(o["top"] - w["top"]) < 3]
                    if len(same_line) == 1:                  # a month name on a line of its own
                        labels.append((w["top"], FULL_MONTHS.index(w["text"]) + 1))
            for t in tables:
                above = [m for top, m in labels if top < t.bbox[1]]
                if above:
                    month = above[-1]
                if month is None:
                    continue
                for row in t.rows:
                    if len(row.cells) != 3 or any(c is None for c in row.cells[::2]):
                        continue
                    if row.cells[1] is None:                 # 'Date TBD', 'Tuesdays and Thursdays in IAP'
                        continue
                    subs = [page.within_bbox(c) for c in row.cells]
                    day_txt, date_txt, event = [" ".join((s.extract_text() or "").split()) for s in subs]
                    if not event or not re.search(r"\d", date_txt):
                        continue
                    office = office_of(subs[2].chars)
                    y = year_for(month, years)
                    week = day_txt.lower().startswith("week of")
                    spans = []
                    for part in re.split(r"\s*,\s*", date_txt):
                        dm = re.fullmatch(r"(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?", part)
                        if not dm:
                            continue
                        try:
                            d1 = date(y, month, int(dm.group(1)))
                            d2 = date(y, month, int(dm.group(2) or dm.group(1)))
                        except ValueError:
                            notes.append(f"{label}: no such date '{FULL_MONTHS[month-1]} {part}' ({event})")
                            continue
                        if week and d1 == d2 and d1.weekday() <= 4:
                            d2 = d1 + timedelta(days=4 - d1.weekday())   # 'Week of N' = N .. Friday
                        spans.append((d1, d2))
                    if not spans:
                        continue
                    first = spans[0][0]
                    if week:   # a week normally starts Monday, or Tuesday after a Monday holiday
                        ok = "yes" if first.weekday() == 0 else "check"
                        if ok == "check":
                            notes.append(f"{label}: 'Week of {FULL_MONTHS[month-1]} {date_txt}' starts on a "
                                         f"{WEEKDAYS[first.weekday()]} ({event}); expected only right after a Monday holiday, so worth checking")
                    else:
                        want = DAY_NAMES.get(day_txt[:3].lower())
                        ok = "" if want is None else ("yes" if first.weekday() == want else "NO")
                        if ok == "NO":
                            notes.append(f"{label}: listed as '{day_txt} {FULL_MONTHS[month-1]} {date_txt}', but that "
                                         f"date is a {WEEKDAYS[first.weekday()]} ({event})")
                    cat, off = categorize(event)
                    for d1, d2 in spans:
                        rows.append(dict(start=d1, end=d2, term=term_for(d1, event), event=event, category=cat,
                                         no_classes=off and office == "Academic Calendar", office=office,
                                         source=f"Key dates PDF {label}", weekday_listed=day_txt,
                                         weekday_ok=ok, raw=f"{day_txt} | {date_txt} | {event}"))
    return rows, notes


def scrape_calendar(f: Fetcher, pdfs: list[str] | None = None, all_offices: bool = False) -> list[dict]:
    log("calendar: registrar key dates")
    rows = []
    html = f.get(CALENDAR_URL, "registrar_key_dates.html")
    if html:
        rows = parse_calendar(html)
        for r in rows:
            r.update(office="Academic Calendar", source="Registrar key dates page")
        log(f"  {len(rows)} dated entries")
        if not rows:
            log("  no dates parsed (layout may have changed; try --save-html)")
    for src in pdfs or []:
        name = src.rstrip("/").rsplit("/", 1)[-1]
        log(f"calendar: {name}")
        if src.startswith("http"):
            data = f.get_bytes(src, name)
        else:
            p = Path(src).expanduser()
            data = p.read_bytes() if p.exists() else None
            if data is None:
                log(f"  file not found: {src}")
        if not data:
            continue
        try:
            got, notes = parse_key_dates_pdf(data, name)
        except ImportError:
            log("  needs pdfplumber: python -m pip install pdfplumber")
            return rows
        if not all_offices:
            got = [r for r in got if r["office"] == "Academic Calendar"]
        log(f"  {len(got)} dated entries")
        for n in notes:
            log(f"  note: {n}")
        rows += got
    return sorted(rows, key=lambda r: (r["start"], r["event"]))


# class times

# MIT subject-listing times: without the evening flag, 6-11.30 are AM, 12 is noon, 1-5.30 are PM.
def mit_minutes(tok: str, evening: bool) -> int:
    tok = tok.strip().upper().replace(" PM", "").replace("PM", "").strip()
    h, _, m = tok.partition(".")
    h, m = int(h), int(m or 0)
    if evening:
        h = h if h == 12 else h + 12
    elif h < 6:
        h += 12
    return h * 60 + m


def parse_meeting(slot: str, evening: bool) -> tuple[int, int]:
    """'9.30-11' -> (570, 660); single '11' means one hour. Handles '11-2 PM' with evening flag."""
    if "-" in slot:
        a, b = slot.split("-", 1)
        start, end = mit_minutes(a, evening), mit_minutes(b, evening)
        if start > end:                       # e.g. '11-2 PM': start is morning
            start = mit_minutes(a, False)
        return start, end
    s = mit_minutes(slot, evening)
    return s, s + 60


DAY_LETTERS = {"M": "Mon", "T": "Tue", "W": "Wed", "R": "Thu", "F": "Fri", "S": "Sat"}


def parse_schedule(subject: str, schedule: str) -> list[dict]:
    """Fireroad schedule string, e.g.
    'Lecture,32-123/TR/0/11/F/0/2;Recitation,2-147/MW/0/10,2-142/MW/0/11'."""
    out = []
    for chunk in (schedule or "").split(";"):
        kind, *sections = chunk.split(",")
        kind = kind.rstrip("s").strip()
        for i, sec in enumerate(sections, 1):
            if not sec or sec == "TBA":
                continue
            room, *parts = sec.split("/")
            for j in range(0, len(parts) - 2, 3):
                days, eve, slot = parts[j], parts[j + 1], parts[j + 2]
                try:
                    start, end = parse_meeting(slot, eve == "1")
                except ValueError:
                    log(f"  could not read time '{slot}' for {subject}")
                    continue
                for ch in days:
                    if ch in DAY_LETTERS:
                        out.append(dict(subject=subject, kind=kind, section=i, room=room,
                                        weekday=DAY_LETTERS[ch], start_min=start, end_min=end,
                                        raw=sec))
    return out


def scrape_classes(f: Fetcher, local_json: Path | None) -> list[dict]:
    log("classes: Fireroad course feed")
    if local_json:
        courses = json.loads(local_json.read_text())
    else:
        txt = f.get(FIREROAD_URL, "fireroad_courses.json")
        if not txt:
            return []
        courses = json.loads(txt)
    rows = []
    for c in courses:
        sched = c.get("schedule")
        if not sched:
            continue
        for r in parse_schedule(c.get("subject_id", ""), sched):
            r["level"] = c.get("level", "")
            r["title"] = c.get("title", "")
            rows.append(r)
    log(f"  {len(rows)} weekly class meetings from {len({r['subject'] for r in rows})} subjects")
    return rows


# csv output

def _write(path: Path, header: list[str], rows: list[list]) -> None:
    # utf-8-sig so Excel shows curly apostrophes (Presidents’ Day) correctly; pandas reads it fine
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def write_csvs(sports: list[dict], calendar: list[dict], classes: list[dict], out_dir: Path) -> list[Path]:
    """Raw data plus pre-computed summaries (CSV can't hold formulas)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []

    def save(name, header, rows):
        p = out_dir / name
        _write(p, header, rows)
        written.append(p)

    # raw: sports
    if sports:
        save("sports_games.csv",
             ["date", "weekday", "start_time", "start_hour", "sport", "season", "event", "home_away",
              "location", "result", "time_as_posted", "source_url"],
             [[r["date"].isoformat(), WEEKDAYS[r["date"].weekday()],
               r["start"].strftime("%H:%M") if r["start"] else "", r["start"].hour if r["start"] else "",
               r["sport"], r["season"], r["event"], r["home_away"], r["location"],
               r.get("result", ""), r.get("time_raw", ""), r.get("source_url", "")] for r in sports])

        # summary: games by weekday x start hour (long format: one row per non-empty cell)
        cnt = Counter((r["date"].weekday(), r["start"].hour) for r in sports if r["start"])
        save("summary_games_by_day_hour.csv", ["weekday", "start_hour", "games"],
             [[WEEKDAYS[d], h, n] for (d, h), n in sorted(cnt.items())])

    # raw: academic calendar
    if calendar:
        save("academic_calendar.csv",
             ["start_date", "end_date", "weekday", "term", "event", "category", "no_classes", "office",
              "source", "weekday_matches_listing", "text_as_posted"],
             [[r["start"].isoformat(), r["end"].isoformat(), WEEKDAYS[r["start"].weekday()], r["term"],
               r["event"], r["category"], r["no_classes"], r.get("office", ""), r.get("source", ""),
               r.get("weekday_ok", ""), r.get("raw", "")] for r in calendar])

    # raw: class meetings
    if classes:
        save("class_meetings.csv",
             ["subject", "title", "kind", "section", "level", "room", "weekday", "start", "end",
              "minutes", "schedule_as_posted"],
             [[r["subject"], r.get("title", ""), r["kind"], r["section"], r.get("level", ""), r["room"],
               r["weekday"], hhmm(r["start_min"]), hhmm(r["end_min"]), r["end_min"] - r["start_min"],
               r["raw"]] for r in classes])

        # summary: how many meetings start / end at each half hour
        starts = Counter(r["start_min"] // 30 * 30 for r in classes)
        ends = Counter(-(-r["end_min"] // 30) * 30 for r in classes)
        total = sum(starts.values())
        times = sorted(set(starts) | set(ends))
        save("summary_class_start_end_times.csv",
             ["time", "meetings_starting", "meetings_ending", "share_of_starts"],
             [[hhmm(t), starts[t], ends[t], round(starts[t] / total, 4)] for t in times])

        # summary: meetings in progress, weekday x half hour (long format)
        busy = Counter()
        for r in classes:
            t = r["start_min"] // 30 * 30
            while t < r["end_min"]:
                busy[(r["weekday"], t)] += 1
                t += 30
        order = {d: i for i, d in enumerate(WEEKDAYS)}
        save("summary_class_busy_hours.csv", ["weekday", "time", "meetings_in_progress"],
             [[d, hhmm(t), n] for (d, t), n in sorted(busy.items(), key=lambda x: (order[x[0][0]], x[0][1]))])

    return written


# main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", default="mit_events_data", help="output folder for the CSV files")
    ap.add_argument("--skip", nargs="*", default=[], choices=["sports", "calendar", "classes"])
    ap.add_argument("--sports", nargs="*", help="only these team slugs, e.g. football mens-soccer")
    ap.add_argument("--sports-since", type=int, metavar="YEAR",
                    help="also scrape past seasons back to this year, e.g. 2019")
    ap.add_argument("--classes-json", type=Path, help="use a saved Fireroad courses JSON instead of fetching")
    ap.add_argument("--past-calendars", action="store_true",
                    help="also read the registrar's Key Dates PDFs for 2021-22 through 2025-26")
    ap.add_argument("--calendar-pdfs", nargs="*", default=[],
                    help="more Key Dates PDFs to read (file paths or URLs)")
    ap.add_argument("--all-offices", action="store_true",
                    help="keep the PDFs' catalog/schedules/committee dates too, not just the academic calendar")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default 1)")
    ap.add_argument("--save-html", type=Path, help="folder to keep every fetched page for debugging")
    a = ap.parse_args()

    f = Fetcher(a.delay, a.save_html)
    sports = [] if "sports" in a.skip else scrape_sports(f, set(a.sports) if a.sports else None, a.sports_since)
    pdfs = (KEY_DATES_PDFS if a.past_calendars else []) + a.calendar_pdfs
    calendar = [] if "calendar" in a.skip else scrape_calendar(f, pdfs, a.all_offices)
    classes = [] if "classes" in a.skip else scrape_classes(f, a.classes_json)
    written = write_csvs(sports, calendar, classes, Path(a.out))
    log(f"wrote {len(written)} CSV files to {a.out}/: {len(sports)} games, "
        f"{len(calendar)} calendar dates, {len(classes)} class meetings")
    for p in written:
        log(f"  {p.name}")
    if classes:
        top = Counter(r["start_min"] for r in classes).most_common(1)[0]
        log(f"most common class start: {hhmm(top[0])} ({top[1]} meetings)")


if __name__ == "__main__":
    main()