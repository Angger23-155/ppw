import json
from typing import Dict, List, Tuple, Any

def generate_visjs_html(
    nodes_info: Dict[str, Dict[str, Any]],
    edges: List[Tuple[str, str, Any]],
    pagerank_scores: Dict[str, float],
    in_degrees: Dict[str, int],
    out_degrees: Dict[str, int],
    height: str = "650px",
    physics_enabled: bool = True
) -> str:
    """
    Menghasilkan kode HTML + JavaScript mandiri (menggunakan Vis-Network)
    untuk visualisasi graf interaktif yang siap disematkan ke dalam Streamlit.
    """
    max_pr = max(pagerank_scores.values()) if pagerank_scores else 1.0
    min_pr = min(pagerank_scores.values()) if pagerank_scores else 0.0
    pr_range = (max_pr - min_pr) if (max_pr - min_pr) > 0 else 1.0
    
    # Kelompokkan warna berdasarkan domain
    domains = list(set(info.get("domain", "other") for info in nodes_info.values()))
    palette = [
        "#4A90E2", "#50E3C2", "#F5A623", "#E94E77", "#9013FE",
        "#7ED321", "#BD10E0", "#B8E986", "#4A4A4A", "#D0021B"
    ]
    domain_color_map = {d: palette[i % len(palette)] for i, d in enumerate(domains)}
    
    # Siapkan data node untuk Vis.js
    vis_nodes = []
    sorted_urls = sorted(pagerank_scores.keys(), key=lambda u: pagerank_scores[u], reverse=True)
    top_3_urls = set(sorted_urls[:3])
    
    for url, info in nodes_info.items():
        pr = pagerank_scores.get(url, 0.0)
        in_deg = in_degrees.get(url, 0)
        out_deg = out_degrees.get(url, 0)
        domain = info.get("domain", "Unknown")
        title = info.get("title", url)
        
        # Skalakan ukuran node: min 14, max 50
        norm_score = (pr - min_pr) / pr_range
        size = 14 + (norm_score * 36)
        
        # Label singkat untuk node
        label = title if len(title) <= 22 else f"{title[:20]}..."
        
        # Warna khusus untuk Top 3 Rank
        if url in top_3_urls:
            node_color = {
                "background": "#FF6B6B" if url == sorted_urls[0] else "#FFA07A",
                "border": "#C70039",
                "highlight": {"background": "#FF1744", "border": "#900C3F"}
            }
        else:
            base_col = domain_color_map.get(domain, "#4A90E2")
            node_color = {
                "background": base_col,
                "border": "#2C3E50",
                "highlight": {"background": "#F39C12", "border": "#E67E22"}
            }
            
        tooltip_html = (
            f"<b>{title}</b><br>"
            f"<b>URL:</b> {url}<br>"
            f"<b>Domain:</b> {domain}<br>"
            f"<b>PageRank:</b> {pr:.6f}<br>"
            f"<b>In-Degree (Backlinks):</b> {in_deg}<br>"
            f"<b>Out-Degree (Links Out):</b> {out_deg}"
        )
        
        vis_nodes.append({
            "id": url,
            "label": label,
            "title": tooltip_html,
            "value": pr,
            "size": round(size, 1),
            "color": node_color,
            "font": {"size": 12, "color": "#2C3E50", "face": "Helvetica"},
            "shape": "dot",
            "shadow": True
        })
        
    # Siapkan data edge untuk Vis.js
    vis_edges = []
    seen_edges = set()
    for src, dst, *_ in edges:
        if (src, dst) in seen_edges:
            continue
        seen_edges.add((src, dst))
        
        vis_edges.append({
            "from": src,
            "to": dst,
            "arrows": "to",
            "color": {"color": "#8E44AD", "opacity": 0.55, "highlight": "#E74C3C"},
            "width": 1.5,
            "smooth": {"type": "curvedCW", "roundness": 0.2}
        })
        
    nodes_json = json.dumps(vis_nodes)
    edges_json = json.dumps(vis_edges)
    physics_val = "true" if physics_enabled else "false"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
      <style type="text/css">
        body, html {{
          margin: 0;
          padding: 0;
          width: 100%;
          height: 100%;
          overflow: hidden;
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
          background: #f8f9fa;
        }}
        #mynetwork {{
          width: 100%;
          height: {height};
          border: 1px solid #e0e0e0;
          border-radius: 8px;
          background: #ffffff;
        }}
        .legend-box {{
          position: absolute;
          top: 12px;
          right: 12px;
          background: rgba(255, 255, 255, 0.95);
          padding: 8px 14px;
          border-radius: 6px;
          box-shadow: 0 2px 8px rgba(0,0,0,0.12);
          font-size: 11px;
          color: #333;
          z-index: 10;
        }}
        .legend-item {{
          display: flex;
          align-items: center;
          margin-bottom: 4px;
        }}
        .legend-dot {{
          width: 10px;
          height: 10px;
          border-radius: 50%;
          margin-right: 6px;
        }}
      </style>
    </head>
    <body>
      <div class="legend-box">
        <div class="legend-item"><span class="legend-dot" style="background:#FF6B6B;"></span><b>Peringkat #1 PageRank</b></div>
        <div class="legend-item"><span class="legend-dot" style="background:#FFA07A;"></span><b>Peringkat #2 & #3</b></div>
        <div class="legend-item"><span class="legend-dot" style="background:#4A90E2;"></span>Node Lainnya (Ukuran ~ Skor PR)</div>
        <div style="margin-top: 4px; font-style: italic; color: #666;">Panah = Hyperlink Keluar</div>
      </div>
      <div id="mynetwork"></div>
      
      <script type="text/javascript">
        var nodesData = {nodes_json};
        var edgesData = {edges_json};
        
        var container = document.getElementById('mynetwork');
        var data = {{
          nodes: new vis.DataSet(nodesData),
          edges: new vis.DataSet(edgesData)
        }};
        
        var options = {{
          nodes: {{
            borderWidth: 2,
            shadow: true
          }},
          edges: {{
            shadow: false,
            arrows: {{
              to: {{ enabled: true, scaleFactor: 0.8 }}
            }}
          }},
          physics: {{
            enabled: {physics_val},
            barnesHut: {{
              gravitationalConstant: -3500,
              centralGravity: 0.35,
              springLength: 130,
              springConstant: 0.04,
              damping: 0.09
            }},
            stabilization: {{
              enabled: true,
              iterations: 150,
              updateInterval: 25
            }}
          }},
          interaction: {{
            hover: true,
            tooltipDelay: 100,
            navigationButtons: true,
            keyboard: true
          }}
        }};
        
        var network = new vis.Network(container, data, options);
      </script>
    </body>
    </html>
    """
    return html_content
