"""网页搜索:科学期刊优先 + Edge 无头浏览器 + 多引擎并行聚合。

- 科学类查询(物理/医学/生物/化学等关键词命中)会直接检索期刊官方渠道:
  PubMed(医学/生物学)、arXiv(物理/数学/天文)、Nature/Lancet/Science/Cell/NEJM/PNAS 站内搜索,
  期刊结果排在最前;
- Microsoft Edge 无头浏览器打开必应作为首选通用来源;
- DuckDuckGo/必应/百度/谷歌 并行兜底;
- 合并去重(URL+标题)、跳转链接解包、可排除指定站点、偏好域名排前。
"""
import base64
import functools
import html as html_mod
import os
import re
import subprocess
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import requests

from ..config import DATA_DIR
from .net import request as net_request

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
_EDGE_EXE = next((p for p in _EDGE_CANDIDATES if os.path.exists(p)), None)

# 科学类关键词:命中时启用期刊检索并让期刊结果排前
SCIENCE_KEYWORDS = [
    "科学", "物理", "医学", "生物", "化学", "天文", "航天", "神经", "基因",
    "量子", "研究", "论文", "期刊", "最新进展", "诺奖", "诺贝尔", "黑洞",
    "癌症", "疫苗", "临床", "药物", "粒子", "宇宙", "进化", "细胞",
    "nature", "science", "cell", "lancet", "pubmed", "arxiv", "doi",
    "physics", "biology", "medicine", "astronomy", "quantum", "genome",
    "cancer", "vaccine", "clinical", "particle",
]


def _is_science_query(query):
    q = (query or "").lower()
    return any(k in q for k in SCIENCE_KEYWORDS)


def _unwrap(url):
    """解包 DDG 的 /l/?uddg= 重定向,返回真实链接;无效链接返回 None。"""
    if "duckduckgo.com/l/?" in url:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        target = qs.get("uddg", [None])[0]
        if not target:
            return None
        return urllib.parse.unquote(target)
    return url if url.startswith("http") else None


def _unredirect(url):
    """解包必应 /ck/a 与百度 /link 等跳转链接,返回真实 URL;无法解包则原样返回。"""
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc.lower()
        qs = urllib.parse.parse_qs(parsed.query)
        if "ck/a" in parsed.path and "bing.com" in host:
            u = qs.get("u", [None])[0]
            if u:
                pad = u + "=" * (-len(u) % 4)
                real = base64.urlsafe_b64decode(pad).decode("utf-8", "ignore")
                if real.startswith("http"):
                    return real
        if "baidu.com" in host and "/link?" in url:
            u = qs.get("url", [None])[0]
            if u:
                pad = u + "=" * (-len(u) % 4)
                real = base64.urlsafe_b64decode(pad).decode("utf-8", "ignore")
                if real.startswith("http"):
                    return real
    except Exception:
        pass
    return url


def _clean(html_fragment):
    return html_mod.unescape(re.sub(r"<[^>]+>", "", html_fragment)).strip()


def _domain(url):
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""


def _parse_ddg(text):
    results = []
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S
    )
    for m in pattern.finditer(text):
        href = _unwrap(html_mod.unescape(m.group(1)))
        if not href:
            continue
        title = _clean(m.group(2))
        if not title:
            continue
        results.append({"title": title, "url": href, "snippet": ""})
    snippets = re.findall(
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', text, re.S
    )
    for i, sn in enumerate(snippets):
        if i < len(results):
            results[i]["snippet"] = _clean(sn)
    return results or None


def _parse_bing(text):
    results = []
    for block in re.findall(r'<li class="b_algo".*?</li>', text, re.S):
        m = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        url = html_mod.unescape(m.group(1))
        if not url.startswith("http"):
            continue
        title = _clean(m.group(2))
        if not title:
            continue
        pm = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
        snippet = _clean(pm.group(1)) if pm else ""
        results.append({"title": title, "url": url, "snippet": snippet})
    return results or None


def _parse_baidu(text):
    results = []
    for block in re.split(r'class="result', text)[1:]:
        m = re.search(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        url = html_mod.unescape(m.group(1))
        title = _clean(m.group(2))
        if not title:
            continue
        host = urllib.parse.urlparse(url).netloc.lower()
        if "baidu.com" in host and "/link?" not in url:
            continue  # 跳过百度站内链接(保留 /link? 重定向,那才是真实结果)
        sm = re.search(
            r'class="content-right[^"]*"[^>]*>(.*?)</span>', block, re.S
        ) or re.search(r'class="c-abstract[^"]*"[^>]*>(.*?)</span>', block, re.S)
        snippet = _clean(sm.group(1)) if sm else ""
        results.append({"title": title, "url": url, "snippet": snippet})
    return results or None


def _parse_google(text):
    if "consent.google.com" in text or "unusual traffic" in text:
        return None
    results = []
    for block in re.split(r'<div class="g', text)[1:]:
        m = re.search(r'<a href="(https?://[^"]+)"', block)
        if not m:
            continue
        url = html_mod.unescape(m.group(1))
        tm = re.search(r"<h3[^>]*>(.*?)</h3>", block, re.S)
        title = _clean(tm.group(1)) if tm else ""
        if not title:
            continue
        sm = re.search(r'class="VwiC3b[^"]*"[^>]*>(.*?)</div>', block, re.S)
        snippet = _clean(sm.group(1)) if sm else ""
        results.append({"title": title, "url": url, "snippet": snippet})
    return results or None


ENGINES = [
    ("https://html.duckduckgo.com/html/?", _parse_ddg),
    ("https://cn.bing.com/search?", _parse_bing),
    ("https://www.baidu.com/s?", _parse_baidu),
    ("https://www.google.com/search?", _parse_google),
]


def _edge_bing(q, timeout):
    """用 Microsoft Edge 无头模式打开必应搜索,返回渲染后的 HTML;失败返回 None。"""
    if not _EDGE_EXE:
        return None
    profile = DATA_DIR / "edge_profile"
    try:
        profile.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [
                _EDGE_EXE,
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                f"--user-data-dir={profile}",
                "--virtual-time-budget=4000",
                "--dump-dom",
                "https://www.bing.com/search?" + q,
            ],
            capture_output=True,
            timeout=timeout + 5,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout.decode("utf-8", errors="ignore")
    except Exception:
        return None


# ---------- 科学期刊检索(免费官方接口,无需 Key) ----------


def _bilibili_fetch(query_raw, timeout):
    """B 站视频搜索(公开接口,免 Key);失败返回空列表。"""
    try:
        url = "https://api.bilibili.com/x/web-interface/search/type?" + urllib.parse.urlencode(
            {"search_type": "video", "keyword": query_raw}
        )
        resp = net_request("get",
            url,
            headers={"User-Agent": UA, "Referer": "https://search.bilibili.com/"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return []
        result = (resp.json().get("data") or {}).get("result") or []
        out = []
        for it in result[:8]:
            title = _clean(it.get("title") or "")
            bvid = it.get("bvid") or ""
            page = it.get("arcurl") or (
                f"https://www.bilibili.com/video/{bvid}" if bvid else ""
            )
            desc = _clean(it.get("description") or "")[:100]
            if title and page.startswith("http"):
                out.append({"title": title, "url": page, "snippet": desc})
        return out
    except Exception:
        return []


def _wikipedia_fetch(query_raw, timeout):
    """维基百科搜索(MediaWiki 官方接口,中英双语,免 Key)。"""
    out = []
    for lang, base in (
        ("zh", "https://zh.wikipedia.org"),
        ("en", "https://en.wikipedia.org"),
    ):
        try:
            url = base + "/w/api.php?" + urllib.parse.urlencode(
                {
                    "action": "query",
                    "list": "search",
                    "srsearch": query_raw,
                    "format": "json",
                    "srlimit": 3,
                    "utf8": 1,
                }
            )
            resp = net_request("get",url, headers={"User-Agent": UA}, timeout=timeout)
            if resp.status_code != 200:
                continue
            hits = (resp.json().get("query") or {}).get("search") or []
            for h in hits[:3]:
                title = h.get("title") or ""
                snippet = _clean(h.get("snippet") or "")[:140]
                if not title:
                    continue
                page = base + "/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
                out.append(
                    {
                        "title": f"[{lang.upper()}维基] {title}",
                        "url": page,
                        "snippet": snippet,
                    }
                )
        except Exception:
            continue
    return out


def _pubmed_fetch(query_raw, timeout):
    """PubMed(美国国家医学图书馆):医学/生物学/临床文献。"""
    try:
        term = urllib.parse.quote(query_raw)
        url = (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
            f"?db=pubmed&term={term}&retmax=5&retmode=json"
        )
        resp = net_request("get",url, headers={"User-Agent": UA}, timeout=timeout)
        ids = (resp.json().get("esearchresult") or {}).get("idlist") or []
        if not ids:
            return []
        sum_url = (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
            f"?db=pubmed&retmode=json&id={','.join(ids)}"
        )
        resp2 = net_request("get",sum_url, headers={"User-Agent": UA}, timeout=timeout)
        docs = resp2.json().get("result") or {}
        out = []
        for pid in ids:
            d = docs.get(pid) or {}
            title = _clean(d.get("title") or "")
            journal = d.get("fulljournalname") or d.get("source") or ""
            date = (d.get("pubdate") or "")[:10]
            if title:
                out.append(
                    {
                        "title": title,
                        "url": "https://pubmed.ncbi.nlm.nih.gov/" + pid,
                        "snippet": f"{journal} · {date}",
                        "science": True,
                    }
                )
        return out
    except Exception:
        return []


def _arxiv_fetch(query_raw, timeout):
    """arXiv 预印本库(官方 Atom 接口):前沿物理/数学/天文/计算机。"""
    try:
        url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode(
            {"search_query": f"all:{query_raw}", "max_results": 5}
        )
        resp = net_request("get",url, headers={"User-Agent": UA}, timeout=timeout)
        if resp.status_code != 200:
            return []
        text = resp.text
        out = []
        for e in re.findall(r"<entry>.*?</entry>", text, re.S)[:5]:
            tm = re.search(r"<title>(.*?)</title>", e, re.S)
            lm = re.search(r"<id[^>]*>(.*?)</id>", e, re.S)
            sm = re.search(r"<summary>(.*?)</summary>", e, re.S)
            title = _clean(tm.group(1)) if tm else ""
            link = (lm.group(1).strip() if lm else "").replace("http://", "https://")
            snippet = _clean(sm.group(1))[:120] if sm else ""
            if title and link.startswith("http"):
                out.append({"title": title, "url": link, "snippet": snippet, "science": True})
        return out
    except Exception:
        return []


SITE_SEARCHES = [
    ("nature.com", "https://www.nature.com/search?q={q}"),
    ("thelancet.com", "https://www.thelancet.com/action/doSearch?text={q}"),
    ("science.org", "https://www.science.org/action/doSearch?text={q}"),
    ("cell.com", "https://www.cell.com/action/doSearch?text={q}"),
    ("nejm.org", "https://www.nejm.org/search?q={q}"),
    ("pnas.org", "https://www.pnas.org/action/doSearch?text={q}"),
]

_NAV_PATH = (
    "/search", "/about", "/cookie", "/privacy", "/login", "/feed",
    "/sitemap", "/help", "/contact", "/subscribe", "/account",
    "/advertising", "/content", "/journals/lancet", "/guidelines",
)


def _site_search_fetch(query_raw, timeout):
    """期刊站内搜索(宽松解析,失败自动跳过)。"""
    out = []
    for name, base in SITE_SEARCHES:
        if len(out) >= 6:
            break
        try:
            url = base.format(q=urllib.parse.quote(query_raw))
            resp = net_request("get",url, headers={"User-Agent": UA}, timeout=timeout)
            if resp.status_code != 200:
                continue
            text = resp.text
            site_host = _domain(url)
            found = 0
            for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', text, re.S):
                href = html_mod.unescape(m.group(1))
                title = _clean(m.group(2))
                if len(title) < 10:
                    continue
                if href.startswith("//"):
                    href = "https:" + href
                elif href.startswith("/"):
                    href = "https://" + site_host + href
                if not href.startswith("http"):
                    continue
                if _domain(href) != site_host:
                    continue
                path = urllib.parse.urlparse(href).path.lower()
                if any(x in path for x in _NAV_PATH):
                    continue
                if not any(ch.isdigit() for ch in path):
                    continue  # 论文链接路径通常含文章编号
                out.append({"title": title[:120], "url": href, "snippet": "", "science": True})
                found += 1
                if found >= 2:
                    break
        except Exception:
            continue
    return out


class Searcher:
    def __init__(self, config):
        self.config = config

    def _preferred(self):
        return set(self.config.get("search", "preferred_domains", default=[]) or [])

    def _get(self, url, timeout):
        try:
            resp = net_request("get",url, headers={"User-Agent": UA}, timeout=timeout)
            if resp.status_code != 200:
                return None
            return resp.text
        except requests.RequestException:
            return None

    def _merge(self, engine_lists, preferred, limit, science_first=False):
        """轮询合并:去重(URL+标题)、来源轮流取;期刊结果/偏好域名排前。"""
        seen_urls = set()
        seen_titles = set()
        merged = []
        idxs = [0] * len(engine_lists)
        alive = list(range(len(engine_lists)))
        while alive:
            took = False
            for e in list(alive):
                lst = engine_lists[e]
                while idxs[e] < len(lst):
                    r = lst[idxs[e]]
                    idxs[e] += 1
                    url = r.get("url", "")
                    nt = re.sub(r"\s+", "", r.get("title") or "").lower()
                    if url in seen_urls or (nt and nt in seen_titles):
                        continue
                    seen_urls.add(url)
                    if nt:
                        seen_titles.add(nt)
                    merged.append(r)
                    took = True
                    break
                if idxs[e] >= len(lst):
                    alive.remove(e)
            if not took:
                break
        if preferred or science_first:
            def score(r):
                s = 0 if (science_first and r.get("science")) else 1
                p = 0 if (_domain(r.get("url", "")) in preferred) else 1
                return (s, p)

            merged.sort(key=score)
        return merged[:limit]

    def search(self, query, max_results=None):
        """科学期刊 + Edge + 各引擎并行,合并去重后返回 [{title, url, snippet}]。"""
        max_results = max_results or self.config.get("search", "max_results", default=5)
        timeout = self.config.get("search", "timeout", default=8)
        query_raw = query
        q = urllib.parse.urlencode({"q": query})
        blocked = [
            d.lower().strip()
            for d in self.config.get("search", "blocked_domains", default=[]) or []
            if d and d.strip()
        ]
        science_cfg = self.config.get("science", default={}) or {}
        science_on = bool(science_cfg.get("enabled", True)) and _is_science_query(query_raw)

        def req_fetch(base, parser):
            text = self._get(base + q, timeout)
            if not text:
                return []
            try:
                return parser(text) or []
            except Exception:
                return []

        def edge_fetch():
            html = _edge_bing(q, timeout)
            if not html:
                return []
            try:
                return _parse_bing(html) or []
            except Exception:
                return []

        def pubmed_fetch():
            return _pubmed_fetch(query_raw, timeout)

        def arxiv_fetch():
            return _arxiv_fetch(query_raw, timeout)

        def site_fetch():
            return _site_search_fetch(query_raw, timeout)

        def bili_fetch():
            return _bilibili_fetch(query_raw, timeout)

        def wiki_fetch():
            return _wikipedia_fetch(query_raw, timeout)

        tasks = [edge_fetch, bili_fetch, wiki_fetch]
        if science_on:
            tasks += [pubmed_fetch, arxiv_fetch, site_fetch]
        tasks += [
            functools.partial(req_fetch, base, parser) for base, parser in ENGINES
        ]
        with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
            lists = list(ex.map(lambda f: f(), tasks))

        # 解包跳转链接,再按真实域名过滤
        for lst in lists:
            for r in lst:
                real = _unredirect(r.get("url", ""))
                if real:
                    r["url"] = real
        if blocked:
            lists = [
                [
                    r for r in lst
                    if not any(b in _domain(r.get("url", "")) for b in blocked)
                ]
                for lst in lists
            ]
        lists = [lst for lst in lists if lst]
        if not lists:
            return None

        return self._merge(lists, self._preferred(), max_results, science_first=science_on)


def format_results(results):
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(
            f"[{i}] 标题:{r['title']}\n    链接:{r['url']}\n    摘要:{r['snippet'] or '(无摘要)'}"
        )
    return "\n".join(lines)
