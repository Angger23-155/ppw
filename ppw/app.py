"""
Klasifikasi Berita Detik.com (SPORT vs FINANCE)
Skip-gram (Word2Vec) + Naive Bayes

Jalankan:  streamlit run app.py
"""
import os
import re
from functools import lru_cache
from urllib.parse import urlparse

import joblib
import numpy as np
import streamlit as st
import trafilatura
import nltk
from nltk.corpus import stopwords
from Sastrawi.Stemmer.StemmerFactory import StemmerFactory

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH_DEFAULT = os.path.join(APP_DIR, "model_skipgram_nb.pkl")

# Pastikan dijalankan lewat `streamlit run app.py`, bukan `python app.py`
try:
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    _berjalan_di_streamlit = get_script_run_ctx() is not None
except Exception:
    _berjalan_di_streamlit = True
if not _berjalan_di_streamlit:
    import sys
    print("\nAplikasi ini harus dijalankan dengan perintah:\n"
          f'    streamlit run "{os.path.abspath(__file__)}"\n')
    sys.exit(0)

st.set_page_config(page_title="Klasifikasi Berita", page_icon="📰", layout="centered")


# ----------------------------------------------------------------------
# 1. PREPROCESSING (HARUS SAMA PERSIS DENGAN NOTEBOOK)
# ----------------------------------------------------------------------
@st.cache_resource(show_spinner="Menyiapkan stopword dan stemmer...")
def siapkan_nlp():
    nltk.download("stopwords", quiet=True)
    stop = set(stopwords.words("indonesian")).union(set(stopwords.words("english")))
    stop |= {
        'dan','atau','yang','dengan','juga','karena','namun','sehingga','adalah','akan',
        'saat','pada','untuk','dari','oleh','dalam','dapat','kami','mereka','kita','saya',
        'ini','itu','tersebut','tsb','dll','dkk','spt','yg','dgn','dr','jr','sr','thn',
        'tdk','gak','nggak','ya','ia','terkait','berdasarkan','setelah','sebelum',
        'sambil','selain','sekitar','hingga','maupun','bisa','per','waktu','apakah','adanya'
    }
    stemmer = StemmerFactory().create_stemmer()

    @lru_cache(maxsize=None)
    def stem_cached(w):
        return stemmer.stem(w)

    return stop, stem_cached


def bersihkan_teks(text):
    stop, stem = siapkan_nlp()
    if not isinstance(text, str):
        return ""
    text = re.sub(r"[^a-zA-Z\s]", " ", text).lower()
    text = re.sub(r"\s+", " ", text).strip()
    words = [w for w in text.split() if w not in stop and len(w) > 1]
    return " ".join(stem(w) for w in words)


# ----------------------------------------------------------------------
# 2. MEMUAT MODEL
# ----------------------------------------------------------------------
def _is_classifier(o):
    return hasattr(o, "predict_proba") and hasattr(o, "classes_") or hasattr(o, "steps")


def _is_wordvectors(o):
    if hasattr(o, "wv"):          # objek Word2Vec
        return True
    return hasattr(o, "vector_size") and hasattr(o, "__contains__") and hasattr(o, "__getitem__")


def _ambil_komponen(obj):
    """Cari classifier dan word-vectors dari berbagai kemungkinan format .pkl."""
    kandidat = []
    if isinstance(obj, dict):
        kandidat = list(obj.values())
    elif isinstance(obj, (list, tuple)):
        kandidat = list(obj)
    else:
        kandidat = [obj]

    clf = next((o for o in kandidat if _is_classifier(o)), None)
    w2v = next((o for o in kandidat if _is_wordvectors(o)), None)
    if w2v is not None and hasattr(w2v, "wv"):
        w2v = w2v.wv
    return clf, w2v


@st.cache_resource(show_spinner="Memuat model...")
def muat_model(path):
    obj = joblib.load(path)
    clf, wv = _ambil_komponen(obj)

    # Jika .pkl hanya berisi classifier, coba cari model Skip-gram terpisah
    if wv is None:
        folder = os.path.dirname(os.path.abspath(path))
        for nama in ("model_skipgram.model", "skipgram.model", "word2vec.model",
                     "model_skipgram.w2v", "model_skipgram.kv"):
            p = os.path.join(folder, nama)
            if os.path.exists(p):
                from gensim.models import Word2Vec, KeyedVectors
                try:
                    wv = Word2Vec.load(p).wv
                except Exception:
                    wv = KeyedVectors.load(p)
                break

    return clf, wv


def doc_vector(tokens, wv):
    vecs = [wv[t] for t in tokens if t in wv]
    if not vecs:
        return np.zeros(wv.vector_size)
    return np.mean(vecs, axis=0)


# ----------------------------------------------------------------------
# 3. AMBIL BERITA DARI LINK
# ----------------------------------------------------------------------
def ambil_berita(url):
    """Kembalikan (judul, isi) dari URL. Raise ValueError jika gagal."""
    html = trafilatura.fetch_url(url)
    if not html:
        raise ValueError("Halaman tidak dapat diunduh (cek link/koneksi internet).")
    isi = trafilatura.extract(html)
    if not isi:
        raise ValueError("Isi berita tidak berhasil diekstrak dari halaman ini.")
    meta = trafilatura.extract_metadata(html)
    judul = (meta.title if meta and meta.title else "") or ""
    return judul.strip(), isi.strip()


# ----------------------------------------------------------------------
# 4. KLASIFIKASI
# ----------------------------------------------------------------------
def klasifikasi(judul, isi, clf, wv):
    teks_bersih = bersihkan_teks(f"{judul} {isi}")
    tokens = teks_bersih.split()
    dikenal = [t for t in tokens if t in wv]
    if not dikenal:
        return None
    vec = doc_vector(tokens, wv).reshape(1, -1)
    proba = clf.predict_proba(vec)[0]
    kelas = list(clf.classes_)
    return {
        "label": kelas[int(np.argmax(proba))],
        "proba": dict(zip(kelas, proba)),
        "n_token": len(tokens),
        "n_dikenal": len(dikenal),
        "teks_bersih": teks_bersih,
    }


# ----------------------------------------------------------------------
# 5. ANTARMUKA
# ----------------------------------------------------------------------
st.title("📰 Klasifikasi Berita Detik.com")
st.caption("Model: Skip-gram (Word2Vec) + Naive Bayes · Kelas: SPORT / FINANCE")

with st.sidebar:
    st.header("Pengaturan")
    model_path = st.text_input("Lokasi file model (.pkl)", MODEL_PATH_DEFAULT)
    st.markdown(
        "Model dilatih hanya dari berita **detik.com** kategori **sport** dan "
        "**finance**. Berita dari topik lain tetap akan dipaksa masuk ke salah satu "
        "dari dua kelas tersebut."
    )

clf, wv = None, None

# Jika diisi nama file saja, cari relatif ke folder app.py
if not os.path.isabs(model_path) and not os.path.exists(model_path):
    model_path = os.path.join(APP_DIR, model_path)

if not os.path.exists(model_path):
    st.error(f"File model tidak ditemukan: `{model_path}`. Letakkan di folder yang sama dengan app.py "
             f"(`{APP_DIR}`) atau isi lokasi lengkapnya di sidebar.")
    st.stop()

try:
    clf, wv = muat_model(model_path)
except Exception as e:
    st.error(f"Gagal memuat model: {e}")
    st.info("Pastikan versi scikit-learn dan gensim sama dengan yang dipakai saat model disimpan.")
    st.stop()

if clf is None:
    st.error("Classifier Naive Bayes tidak ditemukan di dalam file .pkl.")
    st.stop()
if wv is None:
    st.error(
        "Model Skip-gram tidak ditemukan. File .pkl harus memuat model Skip-gram "
        "(Word2Vec/KeyedVectors) bersama classifier-nya. Lihat petunjuk cara menyimpan "
        "model yang benar."
    )
    st.stop()

tab_link, tab_teks = st.tabs(["🔗 Dari link", "✍️ Tempel teks manual"])

judul, isi = "", ""
jalankan = False

with tab_link:
    url = st.text_input("Link berita", placeholder="https://finance.detik.com/...")
    if st.button("Klasifikasikan", type="primary", key="btn_link"):
        if not url.strip():
            st.warning("Masukkan link berita terlebih dahulu.")
        elif not urlparse(url).scheme.startswith("http"):
            st.warning("Link harus diawali http:// atau https://")
        else:
            if "detik.com" not in urlparse(url).netloc:
                st.info("Link ini bukan dari detik.com. Hasil bisa kurang akurat karena model dilatih dari detik.com.")
            try:
                with st.spinner("Mengunduh dan mengekstrak berita..."):
                    judul, isi = ambil_berita(url.strip())
                jalankan = True
            except ValueError as e:
                st.error(str(e))
                st.caption("Jika terus gagal, gunakan tab 'Tempel teks manual'.")

with tab_teks:
    judul_manual = st.text_input("Judul (opsional)")
    isi_manual = st.text_area("Isi berita", height=200)
    if st.button("Klasifikasikan", type="primary", key="btn_teks"):
        if len(isi_manual.strip()) < 30:
            st.warning("Isi berita terlalu pendek.")
        else:
            judul, isi, jalankan = judul_manual, isi_manual, True

if jalankan:
    with st.spinner("Memproses teks dan mengklasifikasikan..."):
        hasil = klasifikasi(judul, isi, clf, wv)

    st.divider()
    if hasil is None:
        st.error("Tidak ada kata dari berita ini yang dikenal model, sehingga tidak bisa diklasifikasikan.")
    else:
        ikon = {"SPORT": "⚽", "FINANCE": "💹"}.get(hasil["label"], "📰")
        st.subheader(f"{ikon} Prediksi: {hasil['label']}")

        for kelas, p in sorted(hasil["proba"].items(), key=lambda x: -x[1]):
            st.write(f"**{kelas}** — {p:.1%}")
            st.progress(float(p))

        rasio = hasil["n_dikenal"] / max(hasil["n_token"], 1)
        c1, c2, c3 = st.columns(3)
        c1.metric("Token (setelah preprocessing)", hasil["n_token"])
        c2.metric("Token dikenal model", hasil["n_dikenal"])
        c3.metric("Rasio dikenal", f"{rasio:.0%}")

        if rasio < 0.5:
            st.warning("Kurang dari separuh kata dikenal model. Berita mungkin di luar topik latih; hasil kurang dapat diandalkan.")
        st.caption("Catatan: peluang Naive Bayes cenderung terlalu yakin (mendekati 0%/100%), jadi anggap sebagai indikasi kasar.")

        if judul:
            st.markdown(f"**Judul terdeteksi:** {judul}")
        with st.expander("Pratinjau isi berita"):
            st.write(isi[:1500] + ("..." if len(isi) > 1500 else ""))
        with st.expander("Teks setelah preprocessing"):
            st.write(hasil["teks_bersih"])