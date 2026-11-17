import time
import re
from urllib.parse import urlparse, urljoin, urldefrag
from collections import deque
import requests
from bs4 import BeautifulSoup

IGNORED_EXTENSIONS = (
    '.pdf', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico',
    '.zip', '.tar', '.gz', '.rar', '.7z', '.exe', '.dmg', '.apk',
    '.mp4', '.mp3', '.avi', '.mov', '.wmv', '.flv', '.wav',
    '.css', '.js', '.json', '.xml', '.csv', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx'
)

USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 (compatible; UASCrawler/1.0; +http://lab.ti.ac.id)"
)

def normalize_url(url: str) -> str:
    """
    Normalisasi URL:
    - Hilangkan fragment (#section)
    - Lowercase scheme dan netloc
    - Hilangkan query tracking (utm_*, ref, dsb)
    - Hilangkan trailing slash berlebih (kecuali root path)
    """
    try:
        url, _ = urldefrag(url.strip())
        parsed = urlparse(url)
        
        scheme = parsed.scheme.lower()
        if scheme not in ('http', 'https'):
            return ""
            
        netloc = parsed.netloc.lower()
        # Hilangkan port default jika ada
        if netloc.endswith(':80') and scheme == 'http':
            netloc = netloc[:-3]
        elif netloc.endswith(':443') and scheme == 'https':
            netloc = netloc[:-4]
            
        path = parsed.path
        if not path:
            path = "/"
        elif len(path) > 1 and path.endswith('/'):
            path = path[:-1]
            
        # Filter tracking query parameters
        filtered_query = []
        if parsed.query:
            for pair in parsed.query.split('&'):
                if '=' in pair:
                    k, v = pair.split('=', 1)
                    if not k.lower().startswith(('utm_', 'ref', 'fbclid', 'gclid', 'session')):
                        filtered_query.append(f"{k}={v}")
        query_str = f"?{'&'.join(filtered_query)}" if filtered_query else ""
        
        return f"{scheme}://{netloc}{path}{query_str}"
    except Exception:
        return ""

def is_valid_http_url(url: str) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        if not parsed.netloc:
            return False
        # Cek ekstensi file yang diabaikan
        path_lower = parsed.path.lower()
        if any(path_lower.endswith(ext) for ext in IGNORED_EXTENSIONS):
            return False
        return True
    except Exception:
        return False

def get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""

class WebCrawler:
    def __init__(self, seed_url: str, mode: str = "same_domain", max_depth: int = 2, max_pages: int = 30, delay: float = 0.2, timeout: int = 6):
        """
        Web Crawler Rekursif berbasis Breadth-First Search (BFS).
        mode:
          - 'same_domain': Hanya menelusuri halaman di domain/subdomain yang sama
          - 'cross_domain': Menelusuri tautan antar-domain (eksternal)
          - 'all': Menelusuri semua tautan (internal + eksternal)
        """
        self.seed_url = normalize_url(seed_url)
        self.seed_domain = get_domain(self.seed_url)
        self.mode = mode
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.delay = delay
        self.timeout = timeout
        
        self.visited_urls = set()
        self.nodes = {}       # url -> {'title': str, 'domain': str, 'depth': int, 'status': int}
        self.edges = []       # list of (source_url, target_url, anchor_text)
        self.logs = []
        
    def should_crawl(self, target_url: str) -> bool:
        if not is_valid_http_url(target_url):
            return False
        target_domain = get_domain(target_url)
        if not target_domain:
            return False
            
        if self.mode == "same_domain":
            return target_domain == self.seed_domain or target_domain.endswith("." + self.seed_domain)
        elif self.mode == "cross_domain":
            return True
        elif self.mode == "all":
            return True
        return True

    def crawl(self, progress_callback=None):
        """
        Menjalankan proses crawling dengan antrean BFS.
        progress_callback: fungsi callback(current_url, depth, total_visited, queue_size)
        """
        if not is_valid_http_url(self.seed_url):
            self.logs.append(f"[ERROR] Seed URL tidak valid: {self.seed_url}")
            return self.get_results()
            
        # Antrean BFS: (url, depth)
        queue = deque([(self.seed_url, 0)])
        self.visited_urls.add(self.seed_url)
        
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENTS})
        
        while queue and len(self.visited_urls) <= self.max_pages:
            current_url, depth = queue.popleft()
            
            if progress_callback:
                progress_callback(
                    current_url=current_url,
                    depth=depth,
                    total_visited=len(self.nodes),
                    queue_size=len(queue)
                )
                
            self.logs.append(f"[FETCH] Depth {depth} | {current_url}")
            
            try:
                response = session.get(current_url, timeout=self.timeout, allow_redirects=True)
                final_url = normalize_url(response.url) or current_url
                status_code = response.status_code
                
                content_type = response.headers.get("Content-Type", "").lower()
                if "text/html" not in content_type:
                    self.nodes[final_url] = {
                        "title": "(Non-HTML Document)",
                        "domain": get_domain(final_url),
                        "depth": depth,
                        "status": status_code
                    }
                    continue
                    
                soup = BeautifulSoup(response.text, "html.parser")
                page_title = soup.title.string.strip() if soup.title and soup.title.string else get_domain(final_url)
                # Bersihkan newline dari title
                page_title = re.sub(r'\s+', ' ', page_title).strip()
                
                self.nodes[final_url] = {
                    "title": page_title[:80],
                    "domain": get_domain(final_url),
                    "depth": depth,
                    "status": status_code
                }
                
                # Jika sudah mencapai max_depth, tidak perlu mengekstrak tautan keluar untuk antrean
                if depth >= self.max_depth:
                    continue
                    
                # Ekstrak semua tautan <a href="...">
                found_links = set()
                for a_tag in soup.find_all("a", href=True):
                    raw_href = a_tag["href"].strip()
                    if not raw_href or raw_href.startswith(("#", "javascript:", "mailto:", "tel:", "whatsapp:")):
                        continue
                        
                    # Gabungkan URL relatif
                    absolute_url = normalize_url(urljoin(final_url, raw_href))
                    if not is_valid_http_url(absolute_url):
                        continue
                        
                    anchor_text = a_tag.get_text(strip=True)[:40] or "Link"
                    
                    # Tambahkan edge relasi hyperlink (hindari self-loop langsung di graf bila diinginkan)
                    if absolute_url != final_url:
                        edge = (final_url, absolute_url, anchor_text)
                        if edge not in self.edges:
                            self.edges.append(edge)
                            
                    # Tentukan apakah tautan ini layak dikunjungi di depth berikutnya
                    if self.should_crawl(absolute_url):
                        if absolute_url not in self.visited_urls and len(self.visited_urls) < self.max_pages:
                            self.visited_urls.add(absolute_url)
                            queue.append((absolute_url, depth + 1))
                            
                # Politeness delay agar tidak membebani server
                if self.delay > 0:
                    time.sleep(self.delay)
                    
            except requests.exceptions.RequestException as e:
                self.logs.append(f"[WARN] Gagal mengakses {current_url}: {str(e)[:70]}")
                self.nodes[current_url] = {
                    "title": "(Akses Gagal / Timeout)",
                    "domain": get_domain(current_url),
                    "depth": depth,
                    "status": 0
                }
            except Exception as e:
                self.logs.append(f"[ERROR] Error parsing {current_url}: {str(e)[:70]}")
                
        # Pastikan semua target dalam edges juga terdaftar sebagai node minimal
        for src, dst, _ in self.edges:
            if src not in self.nodes:
                self.nodes[src] = {"title": src, "domain": get_domain(src), "depth": 0, "status": 200}
            if dst not in self.nodes:
                self.nodes[dst] = {"title": dst, "domain": get_domain(dst), "depth": self.max_depth + 1, "status": 200}
                
        return self.get_results()

    def get_results(self):
        return {
            "nodes": self.nodes,
            "edges": self.edges,
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "logs": self.logs
        }
