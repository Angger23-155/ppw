"""
Klasifikasi Berita Detik.com (SPORT vs FINANCE)
Pilihan metode: Skip-gram (Word2Vec) + GaussianNB  atau  TF-IDF + MultinomialNB

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

APP_DIR = os.path.dirname(os.path.abspath(__file__))

METODE_SKIPGRAM = "Skip-gram + Naive Bayes"
METODE_TFIDF = "TF-IDF + Naive Bayes"

MODEL_DEFAULT = {
    METODE_SKIPGRAM: os.path.join(APP_DIR, "model_skipgram_nb.pkl"),
    METODE_TFIDF: os.path.join(APP_DIR, "model_tfidf_nb.pkl"),
}

# Pastikan dijalankan lewat `streamlit run app.py`
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
# 1. PREPROCESSING (HARUS SAMA PERSIS DENGAN YANG DIPAKAI SAAT LATIH MODEL)
#    - Skip-gram : cleansing + case folding + tokenisasi
#                  (TANPA stopword removal dan TANPA stemming)
#    - TF-IDF    : cleansing + case folding + tokenisasi
#                  + stopword removal + stemming
# ----------------------------------------------------------------------
@st.cache_resource(show_spinner="Menyiapkan stopword dan stemmer...")
def siapkan_nlp():
    """Hanya dipanggil pada jalur TF-IDF, jadi jalur Skip-gram tidak butuh NLTK/Sastrawi."""
    import nltk
    from nltk.corpus import stopwords
    from Sastrawi.Stemmer.StemmerFactory import StemmerFactory

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


def bersihkan_teks(text, hapus_stopword=True, stemming=True):
    if not isinstance(text, str):
        return ""
    text = re.sub(r"[^a-zA-Z\s]", " ", text).lower()      # cleansing + case folding
    text = re.sub(r"\s+", " ", text).strip()
    words = [w for w in text.split() if len(w) > 1]         # tokenisasi, buang token 1 huruf
    if hapus_stopword:
        stop, _ = siapkan_nlp()
        words = [w for w in words if w not in stop]
    if stemming:
        _, stem = siapkan_nlp()
        words = [stem(w) for w in words]
    return " ".join(words)


def praproses_tfidf(text):
    return bersihkan_teks(text, hapus_stopword=True, stemming=True)


def praproses_skipgram(text):
    return bersihkan_teks(text, hapus_stopword=False, stemming=False)


# ----------------------------------------------------------------------
# 2. MEMUAT MODEL
# ----------------------------------------------------------------------
def _is_classifier(o):
    return (hasattr(o, "predict_proba") and hasattr(o, "classes_")) or hasattr(o, "steps")


def _is_vectorizer(o):
    return hasattr(o, "transform") and hasattr(o, "vocabulary_")


def _is_wordvectors(o):
    if hasattr(o, "wv"):          # objek Word2Vec
        return True
    return hasattr(o, "vector_size") and hasattr(o, "__contains__") and hasattr(o, "__getitem__")


def _daftar_kandidat(obj):
    if isinstance(obj, dict):
        return list(obj.values())
    if isinstance(obj, (list, tuple)):
        return list(obj)
    return [obj]


@st.cache_resource(show_spinner="Memuat model...")
def muat_model(path, metode):
    """Kembalikan dict komponen model.
    Skip-gram -> {'clf', 'wv'}      TF-IDF -> {'clf', 'vectorizer'}"""
    obj = joblib.load(path)
    kandidat = _daftar_kandidat(obj)

    if metode == METODE_TFIDF:
        # Bisa berupa dict {'vectorizer', 'clf'} atau sklearn Pipeline(tfidf, nb)
        if hasattr(obj, "steps") and len(obj.steps) >= 2 and _is_vectorizer(obj.steps[0][1]):
            return {"vectorizer": obj.steps[0][1], "clf": obj.steps[-1][1]}
        vec = next((o for o in kandidat if _is_vectorizer(o)), None)
        clf = next((o for o in kandidat if _is_classifier(o)), None)
        return {"vectorizer": vec, "clf": clf}

    clf = next((o for o in kandidat if _is_classifier(o)), None)
    wv = next((o for o in kandidat if _is_wordvectors(o)), None)
    if wv is not None and hasattr(wv, "wv"):
        wv = wv.wv

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
    return {"clf": clf, "wv": wv}


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
def _susun_hasil(clf, vec, teks_bersih, tokens, dikenal, keterangan):
    proba = clf.predict_proba(vec)[0]
    kelas = list(clf.classes_)
    return {
        "label": kelas[int(np.argmax(proba))],
        "proba": dict(zip(kelas, proba)),
        "n_token": len(tokens),
        "n_dikenal": len(dikenal),
        "teks_bersih": teks_bersih,
        "keterangan": keterangan,
    }


def klasifikasi_skipgram(teks, clf, wv):
    teks_bersih = praproses_skipgram(teks)            # tanpa stopword removal & stemming
    tokens = teks_bersih.split()
    dikenal = [t for t in tokens if t in wv]
    if not dikenal:
        return None
    vec = doc_vector(tokens, wv).reshape(1, -1)       # rata-rata vektor kata Skip-gram
    return _susun_hasil(clf, vec, teks_bersih, tokens, dikenal,
                        "cleansing + case folding + tokenisasi (tanpa stopword removal dan stemming)")


def klasifikasi_tfidf(teks, clf, vectorizer):
    teks_bersih = praproses_tfidf(teks)               # dengan stopword removal & stemming
    tokens = teks_bersih.split()
    kosakata = vectorizer.vocabulary_
    dikenal = [t for t in tokens if t in kosakata]
    if not dikenal:
        return None
    vec = vectorizer.transform([teks_bersih])         # vektor TF-IDF (sparse)
    return _susun_hasil(clf, vec, teks_bersih, tokens, dikenal,
                        "cleansing + case folding + tokenisasi + stopword removal + stemming")


def klasifikasi(judul, isi, metode, komponen):
    teks = f"{judul} {isi}"
    if metode == METODE_TFIDF:
        return klasifikasi_tfidf(teks, komponen["clf"], komponen["vectorizer"])
    return klasifikasi_skipgram(teks, komponen["clf"], komponen["wv"])


# ----------------------------------------------------------------------
# 5. ANTARMUKA
# ----------------------------------------------------------------------
st.title("📰 Klasifikasi Berita Detik.com")

with st.sidebar:
    st.header("Pengaturan")
    metode = st.radio(
        "Metode representasi teks",
        [METODE_SKIPGRAM, METODE_TFIDF],
        help="Skip-gram: vektor kata Word2Vec dirata-rata per berita. "
             "TF-IDF: bobot kata pada kosakata hasil latihan.",
    )
    model_path = st.text_input("Lokasi file model (.pkl)", MODEL_DEFAULT[metode], key=f"path_{metode}")
    if metode == METODE_SKIPGRAM:
        st.caption("Preprocessing: cleansing, case folding, tokenisasi. "
                   "**Tanpa** stopword removal dan stemming.")
    else:
        st.caption("Preprocessing: cleansing, case folding, tokenisasi, "
                   "stopword removal, dan stemming (Sastrawi).")
    st.markdown(
        "Model dilatih hanya dari berita **detik.com** kategori **sport** dan "
        "**finance**. Berita dari topik lain tetap akan dipaksa masuk ke salah satu "
        "dari dua kelas tersebut."
    )

st.caption(f"Metode aktif: {metode} · Kelas: SPORT / FINANCE")

komponen = None

# Jika diisi nama file saja, cari relatif ke folder app.py
if not os.path.isabs(model_path) and not os.path.exists(model_path):
    model_path = os.path.join(APP_DIR, model_path)

if not os.path.exists(model_path):
    st.error(f"File model tidak ditemukan: `{model_path}`. Letakkan di folder yang sama dengan app.py "
             f"(`{APP_DIR}`) atau isi lokasi lengkapnya di sidebar.")
    st.stop()

try:
    komponen = muat_model(model_path, metode)
except Exception as e:
    st.error(f"Gagal memuat model: {e}")
    st.info("Pastikan versi scikit-learn dan gensim sama dengan yang dipakai saat model disimpan.")
    st.stop()

if komponen.get("clf") is None:
    st.error("Classifier Naive Bayes tidak ditemukan di dalam file .pkl.")
    st.stop()
if metode == METODE_SKIPGRAM and komponen.get("wv") is None:
    st.error(
        "Model Skip-gram tidak ditemukan. File .pkl harus memuat vektor kata Skip-gram "
        "(Word2Vec/KeyedVectors) bersama classifier-nya: "
        "`joblib.dump({'wv': model_sg.wv, 'clf': gnb_final}, 'model_skipgram_nb.pkl')`."
    )
    st.stop()
if metode == METODE_TFIDF and komponen.get("vectorizer") is None:
    st.error(
        "TfidfVectorizer tidak ditemukan di file .pkl. File ini harus memuat vectorizer "
        "bersama classifier-nya: "
        "`joblib.dump({'vectorizer': tfidf_final, 'clf': mnb_final}, 'model_tfidf_nb.pkl')`."
    )
    st.stop()

tab_link, tab_teks = st.tabs(["🔗 Dari link", "✍️ Tempel teks manual"])

judul, isi = "", ""
berita_baru = False

with tab_link:
    url = st.text_input("Link berita", placeholder="https://finance.detik.com/...")
    if st.button("Klasifikasikan", type="primary", key="btn_link"):
        st.session_state.pop("berita", None)
        if not url.strip():
            st.warning("Masukkan link berita terlebih dahulu.")
        elif not urlparse(url).scheme.startswith("http"):
            st.warning("Link harus diawali http:// atau https://")
        else:
            if "detik.com" not in urlparse(url).netloc:
                st.info("Link ini bukan dari detik.com🗿. Hasil bisa kurang akurat karena model dilatih dari detik.com.")
            try:
                with st.spinner("Mengunduh dan mengekstrak berita..."):
                    judul, isi = ambil_berita(url.strip())
                berita_baru = True
            except ValueError as e:
                st.error(str(e))
                st.caption("Jika terus gagal, gunakan tab 'Tempel teks manual'.")

with tab_teks:
    judul_manual = st.text_input("Judul (opsional)")
    isi_manual = st.text_area("Isi berita", height=200)
    if st.button("Klasifikasikan", type="primary", key="btn_teks"):
        st.session_state.pop("berita", None)
        if len(isi_manual.strip()) < 30:
            st.warning("Isi berita terlalu pendek.")
        else:
            judul, isi, berita_baru = judul_manual, isi_manual, True

# Berita disimpan di session_state agar saat metode diganti di sidebar,
# berita yang sama langsung diklasifikasikan ulang tanpa mengunduh lagi.
if berita_baru:
    st.session_state["berita"] = (judul, isi)

if "berita" in st.session_state:
    judul, isi = st.session_state["berita"]
    with st.spinner("Memproses teks dan mengklasifikasikan..."):
        hasil = klasifikasi(judul, isi, metode, komponen)

    st.divider()
    if hasil is None:
        st.error("Tidak ada kata dari berita ini yang dikenal model, sehingga tidak bisa diklasifikasikan.")
    else:
        ikon = {"SPORT": "⚽", "FINANCE": "💹"}.get(hasil["label"], "📰")
        st.subheader(f"{ikon} Prediksi: {hasil['label']}")
        st.caption(f"Metode: {metode}")

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
            st.caption(f"Langkah: {hasil['keterangan']}")
            st.write(hasil["teks_bersih"])
