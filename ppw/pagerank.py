import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Any

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

def compute_pagerank_custom(
    nodes: List[str],
    edges: List[Tuple[str, str, Any]],
    d: float = 0.85,
    max_iter: int = 100,
    tol: float = 1e-6
) -> Tuple[Dict[str, float], List[float], int]:
    """
    Implementasi algoritma PageRank dari dasar (From Scratch) menggunakan metode Power Iteration.
    
    Formula PageRank:
        PR(u) = (1 - d) / N + d * sum_{v in B_u} (PR(v) / L(v))
        
    Penanganan Dangling Nodes (Dead Ends):
        Halaman tanpa link keluar mendistribusikan probabilitasnya secara merata ke seluruh N halaman.
        
    Returns:
        pagerank_dict: dict {url: score}
        convergence_history: list selisih L1-norm per iterasi
        iterations_taken: jumlah iterasi hingga konvergen
    """
    N = len(nodes)
    if N == 0:
        return {}, [], 0
        
    node_to_idx = {node: idx for idx, node in enumerate(nodes)}
    
    # Hitung Out-degree (jumlah tautan keluar) untuk setiap node
    out_degree = np.zeros(N, dtype=np.float64)
    for src, dst, *_ in edges:
        if src in node_to_idx and dst in node_to_idx:
            out_degree[node_to_idx[src]] += 1.0
            
    # Buat Adjacency List untuk in-links (halaman yang mengarah ke node u)
    in_links = {i: [] for i in range(N)}
    for src, dst, *_ in edges:
        if src in node_to_idx and dst in node_to_idx:
            src_idx = node_to_idx[src]
            dst_idx = node_to_idx[dst]
            in_links[dst_idx].append(src_idx)
            
    # Inisialisasi probabilitas awal seragam: PR_0 = 1 / N
    p = np.full(N, 1.0 / N, dtype=np.float64)
    dangling_mask = (out_degree == 0)
    
    history = []
    iterations = 0
    
    for it in range(1, max_iter + 1):
        iterations = it
        p_new = np.zeros(N, dtype=np.float64)
        
        # Total bobot dari dangling nodes (dead ends)
        dangling_sum = np.sum(p[dangling_mask])
        dangling_contribution = (d * dangling_sum) / N
        teleport_contribution = (1.0 - d) / N
        
        # Hitung kontribusi dari setiap in-link
        for i in range(N):
            incoming_sum = 0.0
            for src_idx in in_links[i]:
                if out_degree[src_idx] > 0:
                    incoming_sum += p[src_idx] / out_degree[src_idx]
            p_new[i] = teleport_contribution + dangling_contribution + (d * incoming_sum)
            
        # Periksa konvergensi dengan L1-norm: sum(|p_new - p|)
        diff = np.sum(np.abs(p_new - p))
        history.append(float(diff))
        p = p_new
        
        if diff < tol:
            break
            
    # Normalisasi agar total probabilitas = 1.0
    total_p = np.sum(p)
    if total_p > 0:
        p = p / total_p
        
    pagerank_dict = {nodes[i]: float(p[i]) for i in range(N)}
    return pagerank_dict, history, iterations


def compute_pagerank_networkx(
    nodes: List[str],
    edges: List[Tuple[str, str, Any]],
    d: float = 0.85,
    max_iter: int = 100,
    tol: float = 1e-6
) -> Dict[str, Any]:
    """
    Menghitung PageRank dan metrik sentralitas graf menggunakan pustaka NetworkX.
    """
    if not HAS_NETWORKX:
        return {}
        
    G = nx.DiGraph()
    G.add_nodes_from(nodes)
    for src, dst, *_ in edges:
        if src in nodes and dst in nodes:
            G.add_edge(src, dst)
            
    # PageRank
    pr_scores = nx.pagerank(G, alpha=d, max_iter=max_iter, tol=tol)
    
    # In-degree & Out-degree
    in_degrees = dict(G.in_degree())
    out_degrees = dict(G.out_degree())
    
    # Degree Centrality
    deg_centrality = nx.degree_centrality(G)
    
    # HITS (Hubs & Authorities)
    try:
        hubs, authorities = nx.hits(G, max_iter=max_iter, tol=tol, normalized=True)
    except Exception:
        hubs, authorities = {n: 0.0 for n in nodes}, {n: 0.0 for n in nodes}
        
    return {
        "graph": G,
        "pagerank": pr_scores,
        "in_degree": in_degrees,
        "out_degree": out_degrees,
        "degree_centrality": deg_centrality,
        "hubs": hubs,
        "authorities": authorities
    }


def analyze_and_compare(
    nodes_info: Dict[str, Dict[str, Any]],
    edges: List[Tuple[str, str, Any]],
    d: float = 0.85,
    max_iter: int = 100,
    tol: float = 1e-6
) -> Dict[str, Any]:
    """
    Menggabungkan analisis PageRank Custom + NetworkX, memvalidasi hasil komparasi,
    dan menyusun DataFrame peringkat terurut untuk dashboard.
    """
    node_urls = list(nodes_info.keys())
    
    # 1. Hitung Custom PageRank
    custom_pr, conv_history, iters = compute_pagerank_custom(
        nodes=node_urls,
        edges=edges,
        d=d,
        max_iter=max_iter,
        tol=tol
    )
    
    # 2. Hitung NetworkX jika tersedia
    nx_results = compute_pagerank_networkx(
        nodes=node_urls,
        edges=edges,
        d=d,
        max_iter=max_iter,
        tol=tol
    ) if HAS_NETWORKX else {}
    
    # 3. Hitung In-degree dan Out-degree manual
    in_deg = {u: 0 for u in node_urls}
    out_deg = {u: 0 for u in node_urls}
    for src, dst, *_ in edges:
        if src in out_deg:
            out_deg[src] += 1
        if dst in in_deg:
            in_deg[dst] += 1
            
    # 4. Susun DataFrame Analisis
    rows = []
    for url in node_urls:
        info = nodes_info.get(url, {})
        c_score = custom_pr.get(url, 0.0)
        nx_score = nx_results.get("pagerank", {}).get(url, c_score) if nx_results else c_score
        
        diff = abs(c_score - nx_score) if nx_results else 0.0
        
        rows.append({
            "url": url,
            "title": info.get("title", url),
            "domain": info.get("domain", ""),
            "pagerank_custom": c_score,
            "pagerank_networkx": nx_score,
            "diff_abs": diff,
            "in_degree": in_deg.get(url, 0),
            "out_degree": out_deg.get(url, 0),
            "hub_score": nx_results.get("hubs", {}).get(url, 0.0) if nx_results else 0.0,
            "authority_score": nx_results.get("authorities", {}).get(url, 0.0) if nx_results else 0.0
        })
        
    df = pd.DataFrame(rows)
    if not df.empty:
        # Urutkan berdasarkan PageRank tertinggi
        df = df.sort_values(by="pagerank_custom", ascending=False).reset_index(drop=True)
        df["rank"] = df.index + 1
        
    mae = float(df["diff_abs"].mean()) if (not df.empty and nx_results) else 0.0
    
    return {
        "dataframe": df,
        "custom_pr": custom_pr,
        "convergence_history": conv_history,
        "iterations_taken": iters,
        "mae_comparison": mae,
        "nx_results": nx_results,
        "in_degrees": in_deg,
        "out_degrees": out_deg
    }
