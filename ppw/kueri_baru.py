# =============================================================================
# kueri_baru.py — Kueri pencarian SLR berdasarkan "Kata Kunci baru.txt"
# Topik: Sentinel-2, cloud removal/reconstruction, deep learning vs traditional,
#        classification accuracy, agricultural land cover
# =============================================================================

TAHUN_MULAI = 2016
TAHUN_AKHIR = 2026

# --- Scopus (LIMIT-TO tidak berlaku di API; pakai DOCTYPE() dan LANGUAGE()) ---
SCOPUS = (
    'TITLE-ABS-KEY(("Sentinel-2" OR "multispectral imagery" OR "optical satellite data" '
    'OR "agricultural fields") '
    'AND ("cloud removal" OR "cloud reconstruction" OR "gap-filling" OR "deep learning" '
    'OR "CNN" OR "GAN" OR "Transformer") '
    'AND ("traditional methods" OR "cloud masking" OR "without cloud removal" '
    'OR "statistical methods") '
    'AND ("classification accuracy" OR "Overall Accuracy" OR "OA" OR "F1-Score" '
    'OR "Kappa coefficient" OR "performance improvement") '
    'AND ("agricultural land cover classification" OR "crop type mapping" '
    'OR "precision agriculture" OR "remote sensing")) '
    'AND (DOCTYPE(ar) OR DOCTYPE(cp)) AND LANGUAGE(english)'
)

# --- Web of Science (TS = Topic) ---
WOS = (
    'TS=("Sentinel-2" OR "multispectral imagery" OR "optical satellite data" '
    'OR "agricultural fields") '
    'AND TS=("cloud removal" OR "cloud reconstruction" OR "gap-filling" OR "deep learning" '
    'OR CNN OR GAN OR Transformer) '
    'AND TS=("traditional methods" OR "cloud masking" OR "without cloud removal" '
    'OR "statistical methods") '
    'AND TS=("classification accuracy" OR "Overall Accuracy" OR OA OR "F1-Score" '
    'OR "Kappa coefficient" OR "performance improvement") '
    'AND TS=("agricultural land cover classification" OR "crop type mapping" '
    'OR "precision agriculture" OR "remote sensing")'
)

# --- ScienceDirect: field "title" (judul) AND "qs" (isi lengkap), masing-masing maks 250 karakter.
#     Dua kueri terpisah agar tidak melebihi 250 karakter per field.
SCIENCEDIRECT = [
    {
        "title": (
            '"Sentinel-2" OR "multispectral" OR "optical satellite" '
            'OR "agricultural" OR "crop" OR "land cover" OR "remote sensing"'
        ),
        "qs": (
            '("cloud removal" OR "cloud reconstruction" OR "gap-filling") AND '
            '("deep learning" OR "CNN" OR "GAN" OR "Transformer")'
        ),
    },
    {
        "title": (
            '"Sentinel-2" OR "land cover classification" OR "crop type mapping" '
            'OR "precision agriculture" OR "remote sensing"'
        ),
        "qs": (
            '("classification accuracy" OR "Overall Accuracy" OR "F1-Score") AND '
            '("cloud masking" OR "traditional methods" OR "statistical methods")'
        ),
    },
]
