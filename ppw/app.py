import streamlit as st
import pandas as pd
import numpy as np
import time
import json
import os
import streamlit.components.v1 as components

from crawler import WebCrawler, normalize_url, is_valid_http_url
from pagerank import analyze_and_compare, HAS_NETWORKX
from visualizer import generate_visjs_html

# Konfigurasi Halaman Streamlit
st.set_page_config(
    page_title="Web Crawling & Analisis PageRank",
    page_icon="🕸️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling CSS
st.markdown("""
<style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 800;
        color: #1E3A8A;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1.05rem;
        color: #4B5563;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background-color: #F8FAFC;
        border-radius: 10px;
        padding: 15px 20px;
        border-left: 5px solid #3B82F6;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }
    .author-badge {
        display: inline-block;
        background-color: #EFF6FF;
        color: #1D4ED8;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 0.9rem;
        font-weight: 600;
        border: 1px solid #BFDBFE;
        margin-bottom: 15px;
    }
    .highlight-rank-1 {
        background-color: #FEF3C7;
        color: #B45309;
        font-weight: bold;
        padding: 4px 8px;
        border-radius: 6px;
    }
</style>
""", unsafe_allow_html=True)

# Inisialisasi Session State agar data tidak hilang saat re-render
if "crawl_data" not in st.session_state:
    st.session_state["crawl_data"] = None
if "analysis_results" not in st.session_state:
    st.session_state["analysis_results"] = None

# Header Aplikasi
st.markdown('<div class="main-title">🕸️ Web Crawling & Analisis Algoritma PageRank</div>', unsafe_allow_html=True)
st.markdown('<div class="author-badge">👨‍💻 Angger Maulana Effendi (NIM: 230411100155) • Teknik Informatika • Web Structure Mining</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Sistem penambangan struktur web terintegrasi: Ekstraksi relasi hyperlink secara rekursif, pemodelan topologi graf, dan perankingan website terpenting menggunakan PageRank.</div>', unsafe_allow_html=True)

# ================= SIDEBAR KONFIGURASI =================
with st.sidebar:
    st.header("⚙️ Konfigurasi Crawling")
    
    # Preset Pilihan Cepat URL
    preset = st.selectbox(
        "Pilih Contoh Seed URL:",
        [
            "Custom URL",
            "Universitas Trunojoyo Madura (https://www.trunojoyo.ac.id)",
            "Wikipedia Web Mining (https://id.wikipedia.org/wiki/Penambangan_web)",
            "Detik News (https://news.detik.com)",
            "Kompas.com (https://www.kompas.com)"
        ]
    )
    
    default_url = "https://www.trunojoyo.ac.id"
    if "Wikipedia" in preset:
        default_url = "https://id.wikipedia.org/wiki/Penambangan_web"
    elif "Detik" in preset:
        default_url = "https://news.detik.com"
    elif "Kompas" in preset:
        default_url = "https://www.kompas.com"
        
    seed_url_input = st.text_input(
        "Seed URL (Alamat Awal):",
        value=default_url,
        help="Alamat URL website yang menjadi titik awal penelusuran tautan."
    )
    
    crawl_mode = st.radio(
        "Cakupan Crawling (Scope):",
        options=["same_domain", "all"],
        format_func=lambda x: "Halaman Internal (Same Domain)" if x == "same_domain" else "Semua Tautan (Internal & Eksternal)",
        help="'Same Domain' membatasi perayapan hanya pada website/subdomain yang sama. 'Semua Tautan' mencakup tautan keluar ke situs lain."
    )
    
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        max_depth = st.slider("Max Depth:", min_value=1, max_value=3, value=2, help="Kedalaman level penelusuran tautan rekursif.")
    with col_d2:
        max_pages = st.slider("Max Pages:", min_value=10, max_value=60, value=30, step=5, help="Jumlah maksimal halaman yang dikunjungi.")
        
    st.markdown("---")
    st.header("🧮 Parameter PageRank")
    
    damping_factor = st.slider(
        "Damping Factor (d):",
        min_value=0.50,
        max_value=0.99,
        value=0.85,
        step=0.01,
        help="Probabilitas seorang peselancar web acak terus mengikuti link (standar Google PageRank = 0.85)."
    )
    
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        max_iterations = st.number_input("Max Iterasi:", min_value=20, max_value=300, value=100, step=10)
    with col_p2:
        tolerance = st.selectbox("Toleransi (ε):", [1e-4, 1e-5, 1e-6, 1e-7], index=2)
        
    request_delay = st.slider("Request Delay (detik):", min_value=0.0, max_value=1.0, value=0.2, step=0.1, help="Jeda antar request untuk politeness.")
    
    start_button = st.button("🚀 Mulai Crawling & Hitung PageRank", use_container_width=True, type="primary")

# ================= EKSEKUSI CRAWLING =================
if start_button:
    normalized_seed = normalize_url(seed_url_input)
    if not is_valid_http_url(normalized_seed):
        st.error("❌ Mohon masukkan format URL HTTP/HTTPS yang valid!")
    else:
        st.info(f"🔍 Memulai proses crawling pada **{normalized_seed}** (Mode: {crawl_mode}, Max Depth: {max_depth}, Max Pages: {max_pages})...")
        
        progress_bar = st.progress(0.0)
        status_text = st.empty()
        
        crawler = WebCrawler(
            seed_url=normalized_seed,
            mode=crawl_mode,
            max_depth=max_depth,
            max_pages=max_pages,
            delay=request_delay,
            timeout=7
        )
        
        def update_progress(current_url, depth, total_visited, queue_size):
            frac = min(total_visited / max(max_pages, 1), 1.0)
            progress_bar.progress(frac)
            status_text.markdown(f"**Mengunjungi:** `{current_url[:65]}...` (Depth: {depth} | Dikunjungi: {total_visited} | Antrean: {queue_size})")
            
        with st.spinner("Sedang melakukan Web Crawling & Ekstraksi Hyperlink..."):
            crawl_data = crawler.crawl(progress_callback=update_progress)
            
        progress_bar.progress(1.0)
        status_text.success(f"✅ Selesai! Berhasil mengekstrak {crawl_data['total_nodes']} halaman web dan {crawl_data['total_edges']} relasi hyperlink.")
        
        with st.spinner("Menghitung Algoritma PageRank & Validasi Matriks..."):
            analysis = analyze_and_compare(
                nodes_info=crawl_data["nodes"],
                edges=crawl_data["edges"],
                d=damping_factor,
                max_iter=int(max_iterations),
                tol=float(tolerance)
            )
            
        st.session_state["crawl_data"] = crawl_data
        st.session_state["analysis_results"] = analysis
        st.rerun()

# ================= TAMPILAN DASHBOARD =================
if st.session_state["analysis_results"] is not None:
    crawl_data = st.session_state["crawl_data"]
    analysis = st.session_state["analysis_results"]
    df = analysis["dataframe"]
    
    # Ringkasan Metrik
    total_nodes = len(crawl_data["nodes"])
    total_edges = len(crawl_data["edges"])
    
    # Kepadatan Graf: E / (V * (V - 1))
    density = (total_edges / (total_nodes * (total_nodes - 1))) if total_nodes > 1 else 0.0
    
    top_site = df.iloc[0] if not df.empty else None
    
    st.markdown("### 📊 Ringkasan Hasil Analisis Topologi Web")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(label="Total Website / Node (V)", value=f"{total_nodes:,}")
    with c2:
        st.metric(label="Total Hyperlink / Edge (E)", value=f"{total_edges:,}")
    with c3:
        st.metric(label="Kepadatan Graf (Density)", value=f"{density:.4f}")
    with c4:
        if top_site is not None:
            st.metric(
                label="Website Paling Berpengaruh (#1)",
                value=f"{top_site['pagerank_custom']:.5f}",
                delta=f"Rank #1: {top_site['domain']}"
            )
            
    st.markdown("---")
    
    # Tab Navigasi Hasil
    tab_graph, tab_table, tab_theory, tab_logs, tab_export = st.tabs([
        "🕸️ Visualisasi Graf Interaktif",
        "🏆 Tabel Peringkat PageRank",
        "🔬 Validasi Matematis & Konvergensi",
        "📜 Log Crawling Data",
        "💾 Ekspor Data & Hasil"
    ])
    
    # TAB 1: VISUALISASI GRAF
    with tab_graph:
        st.subheader("Visualisasi Struktur Jaringan Hyperlink (Web Structure Graph)")
        st.markdown(
            "Graf di bawah ini menunjukkan keterhubungan antarhalaman. "
            "**Ukuran node merepresentasikan nilai PageRank** (semakin besar nilainya, semakin besar lingkaran). "
            "Node berwarna **Merah/Oranye** adalah 3 website dengan pengaruh tertinggi. Panah menunjukkan arah hyperlink."
        )
        
        col_g1, col_g2 = st.columns([3, 1])
        with col_g2:
            physics_on = st.checkbox("Aktifkan Animasi Fisika (Physics Simulation)", value=True)
            min_pr_filter = st.slider(
                "Filter Min PageRank:",
                min_value=float(df["pagerank_custom"].min()),
                max_value=float(df["pagerank_custom"].max()),
                value=float(df["pagerank_custom"].min()),
                step=0.001,
                format="%.4f"
            )
            
        # Saring node sesuai filter PageRank
        filtered_nodes = {
            url: info for url, info in crawl_data["nodes"].items()
            if analysis["custom_pr"].get(url, 0.0) >= min_pr_filter
        }
        filtered_edges = [
            e for e in crawl_data["edges"]
            if e[0] in filtered_nodes and e[1] in filtered_nodes
        ]
        
        graph_html = generate_visjs_html(
            nodes_info=filtered_nodes,
            edges=filtered_edges,
            pagerank_scores=analysis["custom_pr"],
            in_degrees=analysis["in_degrees"],
            out_degrees=analysis["out_degrees"],
            height="620px",
            physics_enabled=physics_on
        )
        
        components.html(graph_html, height=640, scrolling=False)
        st.caption("💡 Tips: Klik dan seret node untuk memindahkan posisi. Scroll mouse untuk memperbesar/memperkecil (Zoom).")

    # TAB 2: TABEL PERINGKAT
    with tab_table:
        st.subheader("Tabel Peringkat Tingkat Kepentingan Website (PageRank Leaderboard)")
        
        col_s1, col_s2 = st.columns([2, 1])
        with col_s1:
            search_query = st.text_input("🔍 Cari berdasarkan URL atau Judul Halaman:", "")
        with col_s2:
            sort_by = st.selectbox("Urutkan Berdasarkan:", ["pagerank_custom", "in_degree", "out_degree", "diff_abs"])
            
        display_df = df.copy()
        if search_query:
            display_df = display_df[
                display_df["url"].str.contains(search_query, case=False, na=False) |
                display_df["title"].str.contains(search_query, case=False, na=False)
            ]
        display_df = display_df.sort_values(by=sort_by, ascending=False).reset_index(drop=True)
        
        # Format tampilan tabel
        styled_df = display_df[[
            "rank", "url", "title", "domain", "pagerank_custom", "in_degree", "out_degree"
        ]].rename(columns={
            "rank": "Rank",
            "url": "Alamat URL",
            "title": "Judul Halaman (Page Title)",
            "domain": "Domain",
            "pagerank_custom": "Skor PageRank",
            "in_degree": "Backlinks (In-Degree)",
            "out_degree": "Tautan Keluar (Out-Degree)"
        })
        
        st.dataframe(
            styled_df.style.format({
                "Skor PageRank": "{:.6f}",
                "Backlinks (In-Degree)": "{:d}",
                "Tautan Keluar (Out-Degree)": "{:d}"
            }).background_gradient(subset=["Skor PageRank"], cmap="YlOrRd"),
            use_container_width=True,
            height=400
        )
        
        # Grafik Bar Top 10
        st.markdown("#### 10 Website Paling Berpengaruh Berdasarkan PageRank")
        top_10 = df.head(10).copy()
        chart_data = top_10.set_index("title")[["pagerank_custom"]]
        st.bar_chart(chart_data)

    # TAB 3: VALIDASI MATEMATIS
    with tab_theory:
        st.subheader("🔬 Landasan Matematis & Validasi Algoritma PageRank")
        
        st.markdown(r"""
        #### 1. Rumus Matematis PageRank (Random Surfer Model)
        Algoritma PageRank memodelkan perilaku pengguna internet yang mengklik tautan secara acak. Formula umum yang digunakan adalah:
        
        $$PR(u) = \frac{1 - d}{N} + d \sum_{v \in B_u} \frac{PR(v)}{L(v)}$$
        
        **Keterangan Notasi:**
        - $PR(u)$: Nilai PageRank dari halaman $u$.
        - $d$: *Damping factor* (biasanya diatur sebesar **0.85**), yaitu probabilitas pengguna terus mengklik tautan.
        - $1 - d$: Probabilitas teleportasi acak (*random jump*) ke halaman sembarang di seluruh web.
        - $N$: Jumlah total halaman (node) dalam graf.
        - $B_u$: Himpunan semua halaman $v$ yang memiliki hyperlink mengarah ke halaman $u$ (*backlinks / in-links*).
        - $L(v)$: Jumlah tautan keluar (*out-degree*) dari halaman $v$.
        
        #### 2. Penanganan Dead-Ends (Dangling Nodes)
        Jika sebuah halaman tidak memiliki tautan keluar sama sekali ($L(v) = 0$), maka halaman tersebut akan menyerap seluruh probabilitas (*rank sink*). 
        Pada sistem ini, bobot dari *dangling nodes* didistribusikan kembali secara merata ke seluruh $N$ halaman:
        $$\sum_{v \in \text{dangling}} \frac{PR(v)}{N}$$
        """)
        
        st.markdown("---")
        st.markdown("#### 3. Bukti Konvergensi Metode Power Iteration")
        col_c1, col_c2 = st.columns([2, 1])
        with col_c1:
            st.write(rf"Sistem mencapai titik konvergen setelah **{analysis['iterations_taken']} iterasi** (toleransi $\epsilon = {tolerance}$).")
            conv_df = pd.DataFrame({
                "Iterasi ke-": range(1, len(analysis["convergence_history"]) + 1),
                "Perubahan L1-Norm (Delta)": analysis["convergence_history"]
            }).set_index("Iterasi ke-")
            st.line_chart(conv_df)
        with col_c2:
            st.metric(label="Total Iterasi", value=analysis["iterations_taken"])
            st.metric(label="Delta Akhir", value=f"{analysis['convergence_history'][-1]:.8f}")
            if HAS_NETWORKX:
                st.metric(
                    label="MAE vs NetworkX",
                    value=f"{analysis['mae_comparison']:.8f}",
                    help="Mean Absolute Error antara implementasi Custom Power Iteration dan fungsi bawaan NetworkX."
                )
                st.success("✅ Implementasi Custom dan NetworkX identik secara matematis (MAE < 1e-5).")
            else:
                st.info("Pustaka NetworkX opsional.")

    # TAB 4: LOG CRAWLING
    with tab_logs:
        st.subheader("📜 Riwayat Penelusuran (Crawling Logs)")
        st.markdown(f"Total baris riwayat aktivitas crawler: **{len(crawl_data['logs'])} entri**.")
        log_text = "\n".join(crawl_data["logs"])
        st.text_area("Aktivitas HTTP & Parser:", value=log_text, height=350)

    # TAB 5: EKSPOR DATA
    with tab_export:
        st.subheader("💾 Unduh Data & Hasil Eksperimen")
        st.markdown("Anda dapat mengunduh hasil crawling dan perankingan untuk keperluan dokumentasi laporan praktikum/UAS:")
        
        col_e1, col_e2, col_e3 = st.columns(3)
        with col_e1:
            csv_data = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Unduh Ranking CSV",
                data=csv_data,
                file_name="pagerank_ranking_results.csv",
                mime="text/csv",
                use_container_width=True
            )
        with col_e2:
            edges_df = pd.DataFrame(crawl_data["edges"], columns=["source", "target", "anchor_text"])
            edges_csv = edges_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Unduh Edge List CSV (Gephi)",
                data=edges_csv,
                file_name="hyperlink_edges.csv",
                mime="text/csv",
                use_container_width=True
            )
        with col_e3:
            json_export = {
                "metadata": {
                    "seed_url": seed_url_input,
                    "total_nodes": total_nodes,
                    "total_edges": total_edges,
                    "damping_factor": damping_factor,
                    "iterations": analysis["iterations_taken"]
                },
                "nodes": [
                    {"id": u, "pr": analysis["custom_pr"].get(u, 0.0), "in_deg": analysis["in_degrees"].get(u, 0)}
                    for u in crawl_data["nodes"]
                ],
                "edges": [{"from": src, "to": dst} for src, dst, *_ in crawl_data["edges"]]
            }
            json_data = json.dumps(json_export, indent=2).encode('utf-8')
            st.download_button(
                label="📥 Unduh Graf JSON",
                data=json_data,
                file_name="web_graph_pagerank.json",
                mime="application/json",
                use_container_width=True
            )

else:
    # Tampilan Awal Sebelum Crawling Dijalankan
    col_banner1, col_banner2 = st.columns([3, 1])
    with col_banner1:
        st.info("👈 Masukkan **Link Website (Seed URL)** pada panel sebelah kiri, atur batasan kedalaman (*depth*), lalu klik **Mulai Crawling & Hitung PageRank**.")
    with col_banner2:
        csv_nodes_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nodes_pagerank.csv")
        csv_edges_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "edges_pagerank.csv")
        if os.path.exists(csv_nodes_path) and os.path.exists(csv_edges_path):
            if st.button("📂 Muat Data Crawl Tersimpan", use_container_width=True, help="Muat data crawling website yang sudah dieksekusi sebelumnya"):
                df_n = pd.read_csv(csv_nodes_path)
                df_e = pd.read_csv(csv_edges_path)
                nodes_dict = {
                    str(row["url"]): {
                        "title": str(row.get("title", row["url"])),
                        "domain": str(row.get("domain", "")),
                        "depth": int(row.get("depth", 0)),
                        "status": 200
                    }
                    for _, row in df_n.iterrows()
                }
                edges_list = [
                    (str(row["source"]), str(row["target"]), str(row.get("anchor_text", "Link")))
                    for _, row in df_e.iterrows()
                ]
                crawl_data = {
                    "nodes": nodes_dict,
                    "edges": edges_list,
                    "total_nodes": len(nodes_dict),
                    "total_edges": len(edges_list),
                    "logs": ["[INFO] Data berhasil dimuat dari berkas lokal nodes_pagerank.csv dan edges_pagerank.csv."]
                }
                with st.spinner("Menghitung Algoritma PageRank..."):
                    analysis = analyze_and_compare(
                        nodes_info=crawl_data["nodes"],
                        edges=crawl_data["edges"],
                        d=damping_factor,
                        max_iter=int(max_iterations),
                        tol=float(tolerance)
                    )
                st.session_state["crawl_data"] = crawl_data
                st.session_state["analysis_results"] = analysis
                st.rerun()
    
    col_info1, col_info2 = st.columns(2)
    with col_info1:
        st.markdown("""
        #### 📌 Apa yang Dilakukan oleh Aplikasi Ini?
        1. **Crawling Rekursif:** Sistem mengunjungi halaman awal, mengurai dokumen HTML menggunakan `BeautifulSoup`, dan mengekstrak semua tautan `<a href="...">`.
        2. **Normalisasi URL:** Menghapus fragment anchor (`#`), tracking query parameter, dan menyelesaikan URL relatif ke absolut.
        3. **Pemodelan Graf Terarah:** Merepresentasikan setiap halaman unik sebagai *Node* dan setiap hyperlink sebagai *Directed Edge* ($A \rightarrow B$).
        4. **Kalkulasi PageRank:** Menghitung probabilitas kedatangan peselancar acak menggunakan metode *Power Iteration* mandiri serta perbandingan dengan pustaka `NetworkX`.
        5. **Visualisasi Interaktif:** Menampilkan graf jaringan dinamis yang dapat di-zoom, digeser, dan node-nya membesar sesuai nilai pengaruh PageRank.
        """)
    with col_info2:
        st.markdown("""
        #### 🚀 Panduan Deployment di Server Warga Lab:
        Aplikasi ini dibangun menggunakan **Streamlit**, sehingga dapat langsung dijalankan pada server laboratorium dengan port publik:
        ```bash
        # 1. Masuk ke direktori proyek
        cd uas-pagerank-crawler

        # 2. Install dependensi
        pip install -r requirements.txt

        # 3. Jalankan aplikasi pada server lab
        streamlit run app.py --server.port 8501 --server.address 0.0.0.0
        ```
        Setelah itu, aplikasi dapat diakses oleh dosen dan rekan mahasiswa melalui IP server lab: `http://<IP-SERVER-LAB>:8501`.
        """)
