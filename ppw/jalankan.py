# =============================================================================
# jalankan.py â€” Menjalankan slr_fetch.py langsung dari Python
# (VS Code tombol Run, IDLE F5, Spyder, PyCharm, atau Jupyter: %run jalankan.py)
#
# Simpan file ini di folder yang sama dengan slr_fetch.py dan kueri.py.
# Isi bagian PENGATURAN, lalu jalankan file ini.
# =============================================================================
import os
import sys
from pathlib import Path

# ----------------------------- PENGATURAN ------------------------------------
SCOPUS_API_KEY = ""          # key Elsevier (dipakai Scopus dan ScienceDirect)
WOS_API_KEY = ""             # key Web of Science Starter API (kosongkan jika belum punya)
EMAIL = ""                   # email Anda, untuk OpenAlex (dianjurkan)

DATABASE = ["scopus", "sciencedirect"]   # wos dilewati jika belum ada key   # hapus yang tidak dipakai
FILE_KUERI = "kueri_baru.py"      # file kueri
FOLDER_HASIL = "hasil_slr"   # folder output
LENGKAPI_ABSTRAK = True      # False = tidak mencari abstrak di OpenAlex/Semantic Scholar
# -----------------------------------------------------------------------------

# Pindah ke folder tempat file ini berada, agar kueri.py dan slr_fetch.py ditemukan
FOLDER = Path(__file__).resolve().parent
os.chdir(FOLDER)
sys.path.insert(0, str(FOLDER))

# Key harus dipasang SEBELUM slr_fetch diimpor
if SCOPUS_API_KEY:
    os.environ["SCOPUS_API_KEY"] = SCOPUS_API_KEY
if WOS_API_KEY:
    os.environ["WOS_API_KEY"] = WOS_API_KEY

import slr_fetch  # noqa: E402

# Pasang juga langsung ke modul (penting di Jupyter, yang menyimpan modul dari run sebelumnya)
if SCOPUS_API_KEY:
    slr_fetch.SCOPUS_API_KEY = SCOPUS_API_KEY
if WOS_API_KEY:
    slr_fetch.WOS_API_KEY = WOS_API_KEY

argumen = ["slr_fetch.py", "--sources", *DATABASE,
           "--config", FILE_KUERI, "--out", FOLDER_HASIL]
if EMAIL:
    argumen += ["--email", EMAIL]
if not LENGKAPI_ABSTRAK:
    argumen.append("--no-enrich")

sys.argv = argumen
try:
    slr_fetch.main()
except SystemExit as e:          # agar IDLE/Jupyter tidak tertutup saat ada pesan galat
    if e.code not in (None, 0):
        print(e.code)

