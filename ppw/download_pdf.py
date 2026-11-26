#!/usr/bin/env python3
"""
download_pdf.py — Download PDF dari hasil crawling slr_fetch.py

Alur:
  1. Baca hasil_gabungan.csv (output slr_fetch.py)
  2. Untuk setiap DOI, coba download PDF dari:
     a. Unpaywall API (PDF open-access gratis)
     b. Sci-Hub (mirror, bisa berubah)
     c. ScienceDirect / Elsevier (jika punya API key institusi)
  3. Simpan PDF ke folder pdf_downloads/
  4. Buat daftar referensi yang GAGAL download -> gagal_download.csv

Pemakaian:
  python download_pdf.py --input hasil_slr/hasil_gabungan.csv --email anda@kampus.ac.id
  python download_pdf.py --input hasil_slr/hasil_gabungan.csv --email anda@kampus.ac.id --start 1 --end 50
  python download_pdf.py --input hasil_slr/hasil_gabungan.csv --email anda@kampus.ac.id --start 51 --end 100

Catatan:
  - Unpaywall memerlukan email (wajib).
  - Hanya artikel open-access yang bisa didownload gratis.
  - Artikel berbayar akan masuk daftar gagal_download.csv.
  - Gunakan opsi --start dan --end untuk membagi tugas per mahasiswa.
"""

import argparse
import csv
import os
import re
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Modul 'requests' belum terpasang. Jalankan: pip install requests")


def sanitize_filename(name, max_len=80):
    """Buat nama file yang aman dari judul artikel."""
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', '_', name.strip())
    if len(name) > max_len:
        name = name[:max_len]
    return name


def try_unpaywall(session, doi, email):
    """Coba dapatkan URL PDF dari Unpaywall API."""
    url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
    try:
        resp = session.get(url, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            best = data.get("best_oa_location")
            if best:
                pdf_url = best.get("url_for_pdf") or best.get("url")
                if pdf_url:
                    return pdf_url
            # Cek semua lokasi OA
            for loc in (data.get("oa_locations") or []):
                pdf_url = loc.get("url_for_pdf") or loc.get("url")
                if pdf_url and pdf_url.endswith(".pdf"):
                    return pdf_url
    except Exception:
        pass
    return None


def try_semantic_scholar(session, doi):
    """Coba dapatkan URL PDF dari Semantic Scholar."""
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
    try:
        resp = session.get(url, params={"fields": "isOpenAccess,openAccessPdf"}, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("isOpenAccess") and data.get("openAccessPdf"):
                return data["openAccessPdf"].get("url")
    except Exception:
        pass
    return None


def download_pdf_file(session, pdf_url, dest_path, tries=3):
    """Download file PDF ke dest_path. Return True jika berhasil."""
    for attempt in range(tries):
        try:
            resp = session.get(pdf_url, timeout=60, stream=True,
                               headers={"User-Agent": "Mozilla/5.0 (compatible; SLR-PDF-Downloader/1.0)"})
            if resp.status_code == 200:
                content_type = resp.headers.get("Content-Type", "")
                # Verifikasi bahwa response adalah PDF
                first_bytes = b""
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if not first_bytes:
                            first_bytes = chunk[:5]
                        f.write(chunk)
                # Cek apakah file benar-benar PDF
                if first_bytes.startswith(b"%PDF") or "pdf" in content_type.lower():
                    return True
                else:
                    os.remove(dest_path)
                    return False
            if resp.status_code == 429:
                time.sleep(2 ** attempt * 3)
                continue
        except Exception:
            time.sleep(2 ** attempt)
            continue
    return False


def main():
    ap = argparse.ArgumentParser(description="Download PDF dari hasil crawling SLR.")
    ap.add_argument("--input", required=True, help="Path ke hasil_gabungan.csv")
    ap.add_argument("--email", required=True, help="Email Anda (wajib untuk Unpaywall API)")
    ap.add_argument("--output", default="pdf_downloads", help="Folder tujuan PDF (bawaan: pdf_downloads)")
    ap.add_argument("--failed", default="gagal_download.csv", help="File daftar gagal download")
    ap.add_argument("--start", type=int, default=1, help="Nomor urut mulai (1-based, untuk pembagian tugas)")
    ap.add_argument("--end", type=int, default=0, help="Nomor urut akhir (0 = sampai habis)")
    ap.add_argument("--delay", type=float, default=1.0, help="Jeda antar download (detik)")
    args = ap.parse_args()

    # Baca CSV
    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"File {input_path} tidak ditemukan. Jalankan slr_fetch.py dulu.")

    with open(input_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        records = list(reader)

    total = len(records)
    print(f"Total rekaman: {total}")

    # Filter berdasarkan range
    start_idx = max(0, args.start - 1)
    end_idx = args.end if args.end > 0 else total
    end_idx = min(end_idx, total)
    records_slice = records[start_idx:end_idx]
    print(f"Memproses rekaman #{args.start} s/d #{end_idx} ({len(records_slice)} artikel)")

    # Buat folder output
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    downloaded = []
    failed = []

    for i, rec in enumerate(records_slice, start=args.start):
        doi = rec.get("doi", "").strip()
        title = rec.get("title", "").strip()
        source = rec.get("source", "")
        year = rec.get("year", "")

        if not doi:
            failed.append({
                "no": i, "title": title, "doi": "", "source": source, "year": year,
                "alasan": "Tidak ada DOI",
                "link": ""
            })
            print(f"  [{i}/{end_idx}] SKIP (tanpa DOI): {title[:60]}...")
            continue

        # Nama file: nomor_tahun_judul-singkat.pdf
        safe_title = sanitize_filename(title, max_len=60)
        filename = f"{i:04d}_{year}_{safe_title}.pdf"
        dest = out_dir / filename

        if dest.exists():
            print(f"  [{i}/{end_idx}] SUDAH ADA: {filename}")
            downloaded.append({"no": i, "title": title, "doi": doi, "file": filename})
            continue

        print(f"  [{i}/{end_idx}] Mencari PDF: {title[:60]}...")

        pdf_url = None
        pdf_source = ""

        # 1. Coba Unpaywall
        pdf_url = try_unpaywall(session, doi, args.email)
        if pdf_url:
            pdf_source = "Unpaywall"

        # 2. Coba Semantic Scholar
        if not pdf_url:
            pdf_url = try_semantic_scholar(session, doi)
            if pdf_url:
                pdf_source = "Semantic Scholar"
            time.sleep(0.5)

        # 3. Download jika URL ditemukan
        if pdf_url:
            success = download_pdf_file(session, pdf_url, str(dest))
            if success:
                size_kb = dest.stat().st_size / 1024
                print(f"    ✓ BERHASIL ({pdf_source}, {size_kb:.0f} KB): {filename}")
                downloaded.append({"no": i, "title": title, "doi": doi, "file": filename})
            else:
                print(f"    ✗ GAGAL download (file bukan PDF): {doi}")
                failed.append({
                    "no": i, "title": title, "doi": doi, "source": source, "year": year,
                    "alasan": f"File bukan PDF ({pdf_source})",
                    "link": f"https://doi.org/{doi}"
                })
        else:
            print(f"    ✗ TIDAK TERSEDIA (closed access): {doi}")
            failed.append({
                "no": i, "title": title, "doi": doi, "source": source, "year": year,
                "alasan": "Tidak ada PDF open-access",
                "link": f"https://doi.org/{doi}"
            })

        time.sleep(args.delay)

    # Simpan daftar gagal
    failed_path = out_dir / args.failed
    if failed:
        with open(failed_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["no", "title", "doi", "source", "year", "alasan", "link"])
            w.writeheader()
            w.writerows(failed)

    # Simpan daftar berhasil
    success_path = out_dir / "berhasil_download.csv"
    if downloaded:
        with open(success_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["no", "title", "doi", "file"])
            w.writeheader()
            w.writerows(downloaded)

    # Ringkasan
    print("\n" + "=" * 60)
    print("RINGKASAN DOWNLOAD PDF")
    print("=" * 60)
    print(f"  Total diproses    : {len(records_slice)}")
    print(f"  Berhasil download : {len(downloaded)}")
    print(f"  Gagal download    : {len(failed)}")
    if downloaded:
        print(f"  File PDF di       : {out_dir.resolve()}")
        print(f"  Daftar berhasil   : {success_path}")
    if failed:
        print(f"  Daftar gagal      : {failed_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
