#!/usr/bin/env python3
"""
slr_fetch.py — Ambil judul + abstrak dari Scopus, Web of Science, dan ScienceDirect
(API resmi, gratis)
untuk SLR: Dampak tutupan awan pada klasifikasi LULC pertanian/perkebunan (ML/DL, 2016–2026).

Alur:
  1. Scopus Search API  -> judul, jurnal, tahun, DOI, ISSN (abstrak biasanya TIDAK ikut tanpa langganan)
  2. WoS Starter API    -> judul, jurnal, tahun, DOI, ISSN, kata kunci (tanpa abstrak)
  2c. ScienceDirect API -> judul, jurnal, tahun, DOI (tanpa abstrak)
  3. Gabung + hapus duplikat (DOI, lalu judul ternormalisasi)
  4. Lengkapi abstrak berdasarkan DOI: OpenAlex -> Semantic Scholar
  5. Simpan: hasil_gabungan.csv, hasil_rayyan.ris, abstrak_kosong.csv, log_pencarian.csv

Persiapan (sekali saja):
  pip install requests
  - Scopus : buat API key gratis di https://dev.elsevier.com  (menu "I want an API Key")
  - WoS    : daftar di https://developer.clarivate.com , buat Application, langganan
             "Web of Science Starter API" plan Free (pakai email institusi). Batas: 50 request/hari.
  - ScienceDirect: memakai API key Elsevier yang SAMA dengan Scopus.
  Simpan key sebagai variabel lingkungan (atau isi langsung di bagian KONFIGURASI):
    Windows (PowerShell):  $env:SCOPUS_API_KEY="xxxx";  $env:WOS_API_KEY="yyyy"
    Linux/Mac:             export SCOPUS_API_KEY=xxxx;  export WOS_API_KEY=yyyy

Kueri bisa diubah TANPA mengedit skrip:
  python slr_fetch.py --buat-template      # membuat kueri.py berisi kueri bawaan -> edit file ini
  python slr_fetch.py                      # otomatis membaca kueri.py jika ada
  python slr_fetch.py --config kueri_v2.py --out hasil_v2   # versi kueri lain, folder hasil lain
  python slr_fetch.py --sources scopus --scopus-query "TITLE-ABS-KEY(rice AND sentinel-1)"

Pemakaian:
  python slr_fetch.py                      # semua database yang key-nya sudah diisi
  python slr_fetch.py --sources scopus     # hanya Scopus
  python slr_fetch.py --sources scopus wos sciencedirect   # pilih sendiri
  python slr_fetch.py --no-enrich          # tanpa melengkapi abstrak
  python slr_fetch.py --email anda@kampus.ac.id   # dianjurkan untuk OpenAlex (polite pool)

Halaman yang sudah diunduh disimpan di folder cache/, jadi kalau kuota WoS harian habis,
jalankan lagi besok: skrip melanjutkan dari halaman terakhir.
"""

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Modul 'requests' belum terpasang. Jalankan: pip install requests")

# ============================================================================
# KONFIGURASI — ubah bagian ini sesuai kebutuhan
# ============================================================================
SCOPUS_API_KEY = os.environ.get("SCOPUS_API_KEY", "isi key disini")   # atau tulis langsung: "abc123..."
SCOPUS_INSTTOKEN = os.environ.get("SCOPUS_INSTTOKEN", "")  # opsional, hanya jika kampus memberi
WOS_API_KEY = os.environ.get("WOS_API_KEY", "isikey")
# ScienceDirect memakai key Elsevier yang sama dengan Scopus
SEMANTIC_SCHOLAR_KEY = os.environ.get("S2_API_KEY", "")   # opsional
OPENALEX_API_KEY = os.environ.get("OPENALEX_API_KEY", "")  # opsional

YEAR_START, YEAR_END = 2016, 2026

# Scopus: LIMIT-TO hanya untuk tampilan web; di API dipakai DOCTYPE() dan LANGUAGE().
# Tahun ditambahkan otomatis per tahun (agar tiap kueri < 5.000 hasil, batas API).
SCOPUS_QUERY = (
    'TITLE-ABS-KEY(("land use" OR "land cover" OR "LULC" OR "crop classification" '
    'OR "crop mapping" OR "plantation mapping") '
    'AND ("cloud cover" OR "cloud contamination" OR "cloud-prone" OR "cloud removal" '
    'OR "SAR" OR "Sentinel-1") '
    'AND ("machine learning" OR "deep learning" OR "random forest" OR "support vector" '
    'OR "CNN" OR "U-Net" OR "LSTM" OR "transformer") '
    'AND ("agricultur*" OR "plantation" OR "oil palm" OR "rubber" OR "paddy" OR "rice")) '
    'AND (DOCTYPE(ar) OR DOCTYPE(cp)) AND LANGUAGE(english)'
)

# WoS Starter API: sintaks advanced search WoS (TS = Topic). Tahun ditambahkan otomatis.
WOS_QUERY = (
    'TS=("land use" OR "land cover" OR LULC OR "crop classification" OR "crop mapping" '
    'OR "plantation mapping") '
    'AND TS=("cloud cover" OR "cloud contamination" OR "cloud-prone" OR "cloud removal" '
    'OR SAR OR "Sentinel-1") '
    'AND TS=("machine learning" OR "deep learning" OR "random forest" OR "support vector" '
    'OR CNN OR "U-Net" OR LSTM OR transformer*) '
    'AND TS=(agricultur* OR plantation* OR "oil palm" OR rubber OR paddy OR rice)'
)
# Jenis dokumen WoS yang dipertahankan (filter dilakukan setelah unduh)
WOS_KEEP_TYPES = {"article", "proceedings paper", "early access"}

# ScienceDirect Search API v2 TIDAK punya field "judul-abstrak-kata kunci" (TAK) seperti di web.
# Field yang tersedia: "title" (judul) dan "qs" (SELURUH isi artikel), masing-masing maks 250
# karakter, dan antar-field digabung dengan AND. Pendekatan di sini:
#   judul harus memuat topik lahan/tanaman  AND  isi artikel memuat awan/SAR dan ML/DL.
# Ini pendekatan (proksi) dari pencarian TAK; laporkan field yang dipakai di bagian Metode.
SD_QUERIES = [
    {"title": '"land cover" OR "land use" OR crop OR crops OR rice OR paddy OR plantation '
              'OR "oil palm" OR rubber OR agricultural',
     "qs": '("cloud cover" OR "cloud contamination" OR "Sentinel-1" OR SAR) AND '
           '("machine learning" OR "deep learning" OR "random forest" OR "neural network")'},
]

OUT_DIR = Path("hasil_slr")
CACHE_DIR = OUT_DIR / "cache"

SCOPUS_URL = "https://api.elsevier.com/content/search/scopus"
WOS_URL = "https://api.clarivate.com/apis/wos-starter/v1/documents"
SD_URL = "https://api.elsevier.com/content/search/sciencedirect"
OPENALEX_URL = "https://api.openalex.org/works"
S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"


# ============================================================================
# Utilitas
# ============================================================================
def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def norm_doi(doi):
    if not doi:
        return ""
    doi = doi.strip().lower()
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", doi)
    return doi


def norm_title(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def cache_get(key):
    p = CACHE_DIR / f"{hashlib.md5(key.encode()).hexdigest()}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def cache_put(key, data):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = CACHE_DIR / f"{hashlib.md5(key.encode()).hexdigest()}.json"
    p.write_text(json.dumps(data), encoding="utf-8")


class QuotaExhausted(Exception):
    pass


def http_get(session, url, *, params=None, headers=None, pause=0.2, tries=5, label="",
             method="GET", body=None):
    """GET/PUT dengan retry untuk 429/5xx. Mengangkat QuotaExhausted bila kuota habis."""
    for attempt in range(tries):
        if method == "PUT":
            r = session.put(url, params=params, headers=headers, json=body, timeout=60)
        else:
            r = session.get(url, params=params, headers=headers, timeout=60)
        if r.status_code == 200:
            time.sleep(pause)
            return r.json()
        if r.status_code == 429:
            if attempt == tries - 1:
                raise QuotaExhausted(f"{label}: kuota/batas API habis (HTTP 429). "
                                     f"Coba lagi nanti/besok. Respons: {r.text[:200]}")
            wait = 2 ** attempt * 2
            log(f"{label}: HTTP 429 (terlalu banyak permintaan), menunggu {wait} detik...")
            time.sleep(wait)
            continue
        if r.status_code in (500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        if r.status_code in (401, 403):
            raise RuntimeError(
                f"{label}: akses ditolak (HTTP {r.status_code}). Periksa API key / hak akses.\n"
                f"Respons: {r.text[:400]}"
            )
        raise RuntimeError(f"{label}: HTTP {r.status_code}: {r.text[:400]}")
    raise RuntimeError(f"{label}: gagal setelah {tries} percobaan.")


def blank_record(source):
    return {
        "source": source, "title": "", "abstract": "", "abstract_source": "",
        "authors": "", "year": "", "journal": "", "doi": "", "issn": "", "eissn": "",
        "doc_type": "", "keywords": "", "source_id": "",
    }


# ============================================================================
# 1. Scopus
# ============================================================================
def scopus_parse_entry(e):
    r = blank_record("Scopus")
    r["title"] = e.get("dc:title", "") or ""
    r["authors"] = e.get("dc:creator", "") or ""
    r["year"] = (e.get("prism:coverDate", "") or "")[:4]
    r["journal"] = e.get("prism:publicationName", "") or ""
    r["doi"] = norm_doi(e.get("prism:doi", ""))
    r["issn"] = e.get("prism:issn", "") or ""
    r["eissn"] = e.get("prism:eIssn", "") or ""
    r["doc_type"] = e.get("subtypeDescription", "") or ""
    r["source_id"] = e.get("eid", "") or ""
    desc = e.get("dc:description")  # hanya ada jika akun berlangganan (view COMPLETE)
    if desc:
        r["abstract"], r["abstract_source"] = desc, "Scopus"
    kw = e.get("authkeywords")
    if kw:
        r["keywords"] = kw.replace(" | ", "; ")
    return r


def fetch_scopus(session, query, years):
    if not SCOPUS_API_KEY:
        raise RuntimeError("SCOPUS_API_KEY belum diisi.")
    headers = {"X-ELS-APIKey": SCOPUS_API_KEY, "Accept": "application/json"}
    if SCOPUS_INSTTOKEN:
        headers["X-ELS-Insttoken"] = SCOPUS_INSTTOKEN
    records, per_year = [], {}
    count = 25  # batas aman untuk pengguna non-langganan
    for y in years:
        q = f"{query} AND PUBYEAR = {y}"
        start, total = 0, None
        while True:
            key = f"scopus|{q}|{start}|{count}"
            data = cache_get(key)
            if data is None:
                data = http_get(session, SCOPUS_URL, headers=headers, label=f"Scopus {y}",
                                params={"query": q, "start": start, "count": count,
                                        "view": "STANDARD"}, pause=0.25)
                cache_put(key, data)
            sr = data.get("search-results", {})
            if total is None:
                total = int(sr.get("opensearch:totalResults", 0) or 0)
                per_year[y] = total
                log(f"Scopus {y}: {total} hasil")
                if total > 5000:
                    log(f"  PERINGATAN: >5.000 hasil di {y}; API hanya bisa mengambil 5.000 pertama. "
                        f"Persempit kueri.")
            entries = sr.get("entry", []) or []
            got = [e for e in entries if "error" not in e]
            records += [scopus_parse_entry(e) for e in got]
            start += count
            if not got or start >= min(total, 5000):
                break
    return records, per_year


# ============================================================================
# 2. Web of Science (Starter API)
# ============================================================================
def wos_parse_hit(h):
    r = blank_record("WoS")
    r["title"] = h.get("title", "") or ""
    names = (h.get("names") or {}).get("authors") or []
    r["authors"] = "; ".join(a.get("wosStandard") or a.get("displayName", "") for a in names)
    src = h.get("source") or {}
    r["year"] = str(src.get("publishYear", "") or "")
    r["journal"] = src.get("sourceTitle", "") or ""
    ids = h.get("identifiers") or {}
    r["doi"] = norm_doi(ids.get("doi", ""))
    r["issn"] = ids.get("issn", "") or ""
    r["eissn"] = ids.get("eissn", "") or ""
    r["doc_type"] = "; ".join(h.get("types") or [])
    r["source_id"] = h.get("uid", "") or ""
    kw = (h.get("keywords") or {}).get("authorKeywords") or []
    r["keywords"] = "; ".join(kw)
    return r


def fetch_wos(session, query, years):
    if not WOS_API_KEY:
        raise RuntimeError("WOS_API_KEY belum diisi.")
    headers = {"X-ApiKey": WOS_API_KEY}
    records, per_year = [], {}
    limit = 50
    for y in years:
        q = f"({query}) AND PY={y}"
        page, total = 1, None
        while True:
            key = f"wos|{q}|{page}|{limit}"
            data = cache_get(key)
            if data is None:
                data = http_get(session, WOS_URL, headers=headers, label=f"WoS {y}",
                                params={"db": "WOS", "q": q, "limit": limit, "page": page},
                                pause=1.1)  # plan gratis: 1 request/detik
                cache_put(key, data)
            meta = data.get("metadata") or {}
            if total is None:
                total = int(meta.get("total", 0) or 0)
                per_year[y] = total
                log(f"WoS {y}: {total} hasil")
            hits = data.get("hits") or []
            records += [wos_parse_hit(h) for h in hits]
            if not hits or page * limit >= total:
                break
            page += 1
    return records, per_year


def wos_filter_types(records):
    kept, dropped = [], 0
    for r in records:
        types = {t.strip().lower() for t in r["doc_type"].split(";") if t.strip()}
        if not types or types & WOS_KEEP_TYPES:
            kept.append(r)
        else:
            dropped += 1
    return kept, dropped


# ============================================================================
# 2b. ScienceDirect (Search API v2, PUT)
# ============================================================================
def sd_parse_result(x):
    r = blank_record("ScienceDirect")
    r["title"] = x.get("title", "") or ""
    auths = x.get("authors") or []
    r["authors"] = "; ".join(a.get("name", "") for a in auths if isinstance(a, dict))
    r["year"] = (x.get("publicationDate", "") or "")[:4]
    r["journal"] = x.get("sourceTitle", "") or ""
    r["doi"] = norm_doi(x.get("doi", ""))
    r["source_id"] = x.get("pii", "") or ""
    r["doc_type"] = "Article"
    return r


def fetch_sciencedirect(session, queries, years):
    if not SCOPUS_API_KEY:
        raise RuntimeError("SCOPUS_API_KEY (key Elsevier) belum diisi.")
    headers = {"X-ELS-APIKey": SCOPUS_API_KEY, "Accept": "application/json",
               "Content-Type": "application/json"}
    if SCOPUS_INSTTOKEN:
        headers["X-ELS-Insttoken"] = SCOPUS_INSTTOKEN
    for q in queries:
        for f, v in q.items():
            if len(v) > 250:
                raise RuntimeError(f"ScienceDirect: field '{f}' {len(v)} karakter (maks 250). "
                                   f"Pecah menjadi beberapa kueri di SD_QUERIES.")
    records, per_year = [], {}
    show = 100
    for y in years:
        per_year[y] = 0
        for qi, q in enumerate(queries):
            offset, total = 0, None
            while True:
                body = dict(q, date=str(y), display={"offset": offset, "show": show,
                                                     "sortBy": "date"})
                key = f"sd|{json.dumps(body, sort_keys=True)}"
                data = cache_get(key)
                if data is None:
                    data = http_get(session, SD_URL, headers=headers, method="PUT", body=body,
                                    label=f"ScienceDirect {y}", pause=0.6)  # maks 2 req/detik
                    cache_put(key, data)
                if total is None:
                    total = int(data.get("resultsFound", 0) or 0)
                    per_year[y] += total
                    log(f"ScienceDirect {y} (kueri {qi + 1}): {total} hasil")
                    if total > 6000:
                        log("  PERINGATAN: >6.000 hasil; API hanya bisa mengambil 6.000 pertama.")
                res = data.get("results") or []
                records += [sd_parse_result(x) for x in res]
                offset += show
                if not res or offset >= min(total, 6000):
                    break
    return records, per_year


# ============================================================================
# 3. Gabung & hapus duplikat
# ============================================================================
def deduplicate(records):
    """Gabungkan rekaman yang DOI-nya sama (atau judulnya sama bila tanpa DOI)."""
    merged, by_key = [], {}
    for r in records:
        key = ("doi", r["doi"]) if r["doi"] else ("title", norm_title(r["title"]))
        if not key[1]:
            merged.append(r)
            continue
        if key in by_key:
            base = by_key[key]
            srcs = set(base["source"].split("; ")) | {r["source"]}
            base["source"] = "; ".join(sorted(srcs))
            for f in ("abstract", "abstract_source", "authors", "journal", "issn", "eissn",
                      "keywords", "doi", "year", "doc_type"):
                if not base[f] and r[f]:
                    base[f] = r[f]
            # pakai daftar penulis yang paling lengkap (Scopus STANDARD hanya penulis pertama)
            if r["authors"].count(";") > base["authors"].count(";"):
                base["authors"] = r["authors"]
        else:
            by_key[key] = r
            merged.append(r)
    return merged


# ============================================================================
# 4. Lengkapi abstrak
# ============================================================================
def openalex_abstract(inv_index):
    if not inv_index:
        return ""
    pos = {}
    for word, idxs in inv_index.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def enrich_openalex(session, records, email):
    todo = [r for r in records if not r["abstract"] and r["doi"]]
    log(f"OpenAlex: mencari abstrak untuk {len(todo)} rekaman...")
    found = 0
    for i in range(0, len(todo), 50):
        batch = todo[i:i + 50]
        dois = "|".join(r["doi"] for r in batch)
        params = {"filter": f"doi:{dois}", "per-page": 50,
                  "select": "doi,abstract_inverted_index"}
        if email:
            params["mailto"] = email
        if OPENALEX_API_KEY:
            params["api_key"] = OPENALEX_API_KEY
        key = f"openalex|{dois}"
        data = cache_get(key)
        if data is None:
            data = http_get(session, OPENALEX_URL, params=params, label="OpenAlex", pause=0.15)
            cache_put(key, data)
        amap = {norm_doi(w.get("doi")): openalex_abstract(w.get("abstract_inverted_index"))
                for w in data.get("results", [])}
        for r in batch:
            a = amap.get(r["doi"])
            if a:
                r["abstract"], r["abstract_source"] = a, "OpenAlex"
                found += 1
    log(f"OpenAlex: {found} abstrak ditemukan")


def enrich_semantic_scholar(session, records):
    todo = [r for r in records if not r["abstract"] and r["doi"]]
    log(f"Semantic Scholar: mencari abstrak untuk {len(todo)} rekaman...")
    headers = {"x-api-key": SEMANTIC_SCHOLAR_KEY} if SEMANTIC_SCHOLAR_KEY else {}
    found = 0
    for i in range(0, len(todo), 100):
        batch = todo[i:i + 100]
        key = "s2|" + "|".join(r["doi"] for r in batch)
        data = cache_get(key)
        if data is None:
            for attempt in range(5):
                resp = session.post(S2_BATCH_URL, params={"fields": "externalIds,abstract"},
                                    json={"ids": [f"DOI:{r['doi']}" for r in batch]},
                                    headers=headers, timeout=60)
                if resp.status_code == 200:
                    data = resp.json()
                    cache_put(key, data)
                    break
                wait = 2 ** attempt * 3
                log(f"Semantic Scholar: HTTP {resp.status_code}, menunggu {wait} detik...")
                time.sleep(wait)
            else:
                log("Semantic Scholar: dilewati (terlalu banyak penolakan).")
                return
            time.sleep(1.1)
        for r, paper in zip(batch, data):
            if paper and paper.get("abstract"):
                r["abstract"], r["abstract_source"] = paper["abstract"], "Semantic Scholar"
                found += 1
    log(f"Semantic Scholar: {found} abstrak ditemukan")


# ============================================================================
# 5. Simpan
# ============================================================================
FIELDS = ["source", "title", "abstract", "abstract_source", "authors", "year", "journal",
          "doi", "issn", "eissn", "doc_type", "keywords", "source_id"]


def write_csv(path, records, fields=FIELDS):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig: rapi di Excel
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)


def write_ris(path, records):
    lines = []
    for r in records:
        ty = "CONF" if re.search(r"conference|proceeding", r["doc_type"], re.I) else "JOUR"
        lines.append(f"TY  - {ty}")
        lines.append(f"TI  - {r['title']}")
        for a in [a.strip() for a in r["authors"].split(";") if a.strip()]:
            lines.append(f"AU  - {a}")
        if r["year"]:
            lines.append(f"PY  - {r['year']}")
        if r["journal"]:
            lines.append(f"T2  - {r['journal']}")
        if r["abstract"]:
            lines.append(f"AB  - {' '.join(r['abstract'].split())}")
        for k in [k.strip() for k in r["keywords"].split(";") if k.strip()]:
            lines.append(f"KW  - {k}")
        if r["doi"]:
            lines.append(f"DO  - {r['doi']}")
        sn = r["issn"] or r["eissn"]
        if sn:
            lines.append(f"SN  - {sn}")
        lines.append(f"DB  - {r['source']}")
        if r["source_id"]:
            lines.append(f"AN  - {r['source_id']}")
        lines.append("ER  - ")
        lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


# ============================================================================
# Main
# ============================================================================
def default_queries():
    return {
        "tahun_mulai": YEAR_START,
        "tahun_akhir": YEAR_END,
        "scopus": SCOPUS_QUERY,
        "wos": WOS_QUERY,
        "sciencedirect": SD_QUERIES,
    }


PY_NAMES = {"TAHUN_MULAI": "tahun_mulai", "TAHUN_AKHIR": "tahun_akhir", "SCOPUS": "scopus",
            "WOS": "wos", "SCIENCEDIRECT": "sciencedirect"}


def read_config(cfg):
    """Baca kueri dari kueri.py (format Python) atau file .json."""
    if cfg.suffix.lower() == ".py":
        import runpy
        try:
            ns = runpy.run_path(str(cfg))
        except SyntaxError as e:
            sys.exit(f"Ada kesalahan penulisan di {cfg} baris {e.lineno}: {e.msg}\n"
                     f"  {(e.text or '').strip()}\n"
                     f"Periksa tanda kutip tunggal '...' dan tanda kurung ( ) di sekitar baris itu.")
        out = {PY_NAMES[k]: v for k, v in ns.items() if k in PY_NAMES}
        if not out:
            sys.exit(f"{cfg} tidak berisi variabel kueri (SCOPUS, WOS, SCIENCEDIRECT, ...).")
        for k in ("scopus", "wos"):
            if k in out and not isinstance(out[k], str):
                sys.exit(f"Variabel {k.upper()} di {cfg} harus berupa teks (string).")
        return out
    try:
        user = json.loads(cfg.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        sys.exit(f"File {cfg} tidak valid (format JSON salah): {e}")
    return {k: v for k, v in user.items() if k in PY_NAMES.values()}


def py_string_block(text, indent="    ", width=88):
    """Pecah kueri panjang menjadi beberapa baris '...' gaya Python."""
    parts, cur = [], ""
    for tok in re.split(r"(?<= )", text):
        if len(cur) + len(tok) > width and cur:
            parts.append(cur)
            cur = tok
        else:
            cur += tok
    if cur:
        parts.append(cur)
    return "\n".join(indent + repr(p) for p in parts)


def make_template():
    q = default_queries()
    sd = "\n".join(
        "    {\n"
        + ",\n".join(f'        "{k}": (\n{py_string_block(v, " " * 12)}\n        )'
                     for k, v in item.items())
        + ",\n    },"
        for item in q["sciencedirect"])
    return f"""# kueri.py — Kueri pencarian SLR (dibaca otomatis oleh slr_fetch.py)
# Tulis kueri seperti biasa: tanda kutip ganda di dalam kueri TIDAK perlu di-escape.
# Setiap baris diapit tanda kutip tunggal '...' dan baris-baris itu otomatis tersambung.
# Jangan lupa spasi di akhir baris agar kata tidak menempel.

TAHUN_MULAI = {q["tahun_mulai"]}
TAHUN_AKHIR = {q["tahun_akhir"]}

# Scopus (LIMIT-TO tidak berlaku di API; pakai DOCTYPE() dan LANGUAGE())
SCOPUS = (
{py_string_block(q["scopus"])}
)

# Web of Science (TS = Topic)
WOS = (
{py_string_block(q["wos"])}
)

# ScienceDirect: "title" (judul) AND "qs" (isi lengkap), masing-masing maks 250 karakter
SCIENCEDIRECT = [
{sd}
]
"""


def load_queries(args):
    """Urutan prioritas: bawaan skrip < file kueri.py < argumen di baris perintah."""
    Q = default_queries()
    cfg = Path(args.config)
    if cfg.exists():
        Q.update(read_config(cfg))
        log(f"Kueri dibaca dari {cfg}")
    elif args.config != "kueri.py":
        sys.exit(f"File konfigurasi {cfg} tidak ditemukan.")
    else:
        log("kueri.py tidak ada; memakai kueri bawaan skrip "
            "(buat dengan: python slr_fetch.py --buat-template)")
    if args.scopus_query:
        Q["scopus"] = args.scopus_query
    if args.wos_query:
        Q["wos"] = args.wos_query
    if args.sd_title or args.sd_qs:
        q = {}
        if args.sd_title:
            q["title"] = args.sd_title
        if args.sd_qs:
            q["qs"] = args.sd_qs
        Q["sciencedirect"] = [q]
    if args.from_year:
        Q["tahun_mulai"] = args.from_year
    if args.to_year:
        Q["tahun_akhir"] = args.to_year
    if isinstance(Q["sciencedirect"], dict):
        Q["sciencedirect"] = [Q["sciencedirect"]]
    return Q


def main():
    global OUT_DIR, CACHE_DIR
    ap = argparse.ArgumentParser(
        description="Ambil judul+abstrak dari Scopus, WoS, ScienceDirect untuk SLR.")
    ap.add_argument("--sources", nargs="+", default=["scopus", "wos", "sciencedirect"],
                    choices=["scopus", "wos", "sciencedirect"])
    ap.add_argument("--config", default="kueri.py",
                    help="file kueri .py (atau .json) (bawaan: kueri.py)")
    ap.add_argument("--buat-template", action="store_true",
                    help="buat file kueri.py berisi kueri bawaan untuk diedit, lalu keluar")
    ap.add_argument("--scopus-query", default="", help="kueri Scopus (menimpa file)")
    ap.add_argument("--wos-query", default="", help="kueri WoS (menimpa file)")
    ap.add_argument("--sd-title", default="", help="kueri ScienceDirect untuk field judul")
    ap.add_argument("--sd-qs", default="", help="kueri ScienceDirect untuk field isi (qs)")
    ap.add_argument("--from-year", type=int, default=0)
    ap.add_argument("--to-year", type=int, default=0)
    ap.add_argument("--out", default="hasil_slr", help="folder hasil (bawaan: hasil_slr)")
    ap.add_argument("--no-enrich", action="store_true", help="jangan lengkapi abstrak")
    ap.add_argument("--email", default="", help="email Anda untuk OpenAlex (dianjurkan)")
    args = ap.parse_args()

    if args.buat_template:
        target = Path(args.config)
        if target.exists():
            sys.exit(f"{target} sudah ada; tidak ditimpa. Hapus/ganti nama dulu jika ingin membuat ulang.")
        target.write_text(make_template(), encoding="utf-8")
        print(f"Template dibuat: {target.resolve()}\nEdit kuerinya, lalu jalankan: python slr_fetch.py")
        return

    Q = load_queries(args)
    OUT_DIR = Path(args.out)
    CACHE_DIR = OUT_DIR / "cache"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    years = list(range(int(Q["tahun_mulai"]), int(Q["tahun_akhir"]) + 1))
    (OUT_DIR / "kueri_dipakai.json").write_text(json.dumps(Q, indent=2, ensure_ascii=False),
                                               encoding="utf-8")
    today = dt.date.today().isoformat()
    session = requests.Session()
    session.headers["User-Agent"] = f"slr-fetch/1.0 (mailto:{args.email or 'unknown'})"

    all_records, search_log = [], []

    if "scopus" in args.sources:
        try:
            recs, per_year = fetch_scopus(session, Q["scopus"], years)
            all_records += recs
            search_log.append({"database": "Scopus", "tanggal": today, "kueri": Q["scopus"],
                               "tahun": f"{years[0]}-{years[-1]}",
                               "jumlah_hasil": sum(per_year.values()),
                               "per_tahun": json.dumps(per_year), "catatan": ""})
            write_csv(OUT_DIR / "scopus_mentah.csv", recs)
        except (RuntimeError, QuotaExhausted) as e:
            log(f"Scopus GAGAL: {e}")

    if "wos" in args.sources:
        try:
            recs, per_year = fetch_wos(session, Q["wos"], years)
            recs, dropped = wos_filter_types(recs)
            all_records += recs
            search_log.append({"database": "Web of Science Core Collection", "tanggal": today,
                               "kueri": Q["wos"], "tahun": f"{years[0]}-{years[-1]}",
                               "jumlah_hasil": sum(per_year.values()),
                               "per_tahun": json.dumps(per_year),
                               "catatan": f"{dropped} rekaman dibuang (bukan Article/Proceedings Paper)"})
            write_csv(OUT_DIR / "wos_mentah.csv", recs)
        except QuotaExhausted as e:
            log(f"WoS BERHENTI: {e} Halaman yang sudah diunduh tersimpan; jalankan lagi besok.")
        except RuntimeError as e:
            log(f"WoS GAGAL: {e}")

    if "sciencedirect" in args.sources:
        try:
            recs, per_year = fetch_sciencedirect(session, Q["sciencedirect"], years)
            all_records += recs
            search_log.append({"database": "ScienceDirect", "tanggal": today,
                               "kueri": json.dumps(Q["sciencedirect"], ensure_ascii=False),
                               "tahun": f"{years[0]}-{years[-1]}",
                               "jumlah_hasil": sum(per_year.values()),
                               "per_tahun": json.dumps(per_year),
                               "catatan": "field title AND qs (isi lengkap); bukan TAK"})
            write_csv(OUT_DIR / "sciencedirect_mentah.csv", recs)
        except (RuntimeError, QuotaExhausted) as e:
            log(f"ScienceDirect GAGAL: {e}")

    if not all_records:
        sys.exit("Tidak ada rekaman yang terambil. Periksa API key dan pesan galat di atas.")

    n_before = len(all_records)
    merged = deduplicate(all_records)
    n_dup = n_before - len(merged)
    log(f"Gabungan: {n_before} rekaman -> {len(merged)} unik ({n_dup} duplikat dihapus)")

    if not args.no_enrich:
        try:
            enrich_openalex(session, merged, args.email)
        except (RuntimeError, QuotaExhausted) as e:
            log(f"OpenAlex dilewati: {e}")
        try:
            enrich_semantic_scholar(session, merged)
        except Exception as e:  # layanan opsional, jangan hentikan proses
            log(f"Semantic Scholar dilewati: {e}")

    missing = [r for r in merged if not r["abstract"]]
    for r in missing:
        r["link"] = f"https://doi.org/{r['doi']}" if r["doi"] else ""

    write_csv(OUT_DIR / "hasil_gabungan.csv", merged)
    write_ris(OUT_DIR / "hasil_rayyan.ris", merged)
    write_csv(OUT_DIR / "abstrak_kosong.csv", missing, FIELDS + ["link"])
    search_log.append({"database": "Gabungan", "tanggal": today, "kueri": "",
                       "tahun": "", "jumlah_hasil": len(merged), "per_tahun": "",
                       "catatan": f"{n_dup} duplikat dihapus; {len(missing)} tanpa abstrak"})
    write_csv(OUT_DIR / "log_pencarian.csv", search_log,
              ["database", "tanggal", "kueri", "tahun", "jumlah_hasil", "per_tahun", "catatan"])

    with_abs = len(merged) - len(missing)
    log("SELESAI")
    log(f"  Rekaman unik         : {len(merged)}")
    log(f"  Dengan abstrak       : {with_abs} ({with_abs / len(merged):.0%})")
    log(f"  Tanpa abstrak        : {len(missing)} -> lihat abstrak_kosong.csv (buka link DOI)")
    log(f"  File untuk Rayyan    : {OUT_DIR / 'hasil_rayyan.ris'}")
    log(f"  Angka untuk PRISMA   : {OUT_DIR / 'log_pencarian.csv'}")


if __name__ == "__main__":
    main()
