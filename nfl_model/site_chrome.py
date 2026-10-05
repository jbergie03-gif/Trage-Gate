"""Shared nav bar + base styles for every gridironmath.com page.

Builders import `nav()` and `CSS`; `--patch FILE` injects the chrome into an
already-rendered page (used to restyle the deployed sheet without rebuilding it,
which would re-snapshot lines).
"""
import argparse
import re
import sys

PAGES = [
    ("/", "Pick sheet"),
    ("/week", "Numbers"),
    ("/notes", "Notes"),
    ("/standings", "Standings"),
]

CSS = """
:root{--bg:#0f1115;--card:#181b22;--line:#262b36;--text:#e8eaed;--dim:#9aa0ac;
--turf:#2fa84f;--turf-dark:#1b5e2d;--chalk:#f4f1ea;--model:#a371f7;--market:#58a6ff}
html{color-scheme:dark}
body{background:var(--bg);color:var(--text)}
nav.site{display:block;max-width:none;width:auto;font-size:16px;position:sticky;top:0;z-index:50;margin:-20px calc(50% - 50vw) 18px;padding:0 16px;
background:linear-gradient(180deg,#131a16 0%,#0f1115 100%);
border-bottom:2px solid var(--turf-dark);box-shadow:0 1px 0 #1b5e2d33,0 6px 18px #0008}
.site .in{max-width:860px;margin:0 auto;display:flex;align-items:center;gap:4px;
height:52px;overflow-x:auto;scrollbar-width:none}
.site .in::-webkit-scrollbar{display:none}
.site .brand{display:flex;align-items:center;gap:8px;font-weight:800;letter-spacing:-.02em;
font-size:17px;color:var(--chalk);text-decoration:none;margin-right:10px;white-space:nowrap}
.site .brand .ball{display:inline-block;width:22px;height:14px;border-radius:50%/60%;
background:#8b4a1f;border:1.5px solid #c57b3f;position:relative;transform:rotate(-20deg)}
.site .brand .ball:after{content:"";position:absolute;left:7px;right:7px;top:5px;height:2px;
background:var(--chalk);box-shadow:0 0 0 .5px var(--chalk)}
.site a.tab{color:var(--dim);text-decoration:none;font-size:14px;font-weight:600;
padding:8px 12px;border-radius:9px;white-space:nowrap;position:relative}
.site a.tab:hover{color:var(--text);background:#ffffff0d}
.site a.tab.on{color:var(--chalk)}
.site a.tab.on:after{content:"";position:absolute;left:12px;right:12px;bottom:-1px;height:3px;
border-radius:2px;background:var(--turf)}
.site .in::after{content:"";margin-left:auto;width:48px;height:14px;flex:none;
background:repeating-linear-gradient(90deg,var(--turf-dark) 0 2px,transparent 2px 10px);opacity:.7}
@media(max-width:520px){.site .brand span{display:none}}
"""


def nav(active):
    tabs = "".join(
        f'<a class="tab{" on" if active == p else ""}" href="{p}">{label}</a>'
        for p, label in PAGES)
    return ('<nav class="site"><div class="in"><a class="brand" href="/">'
            '<i class="ball"></i><span>Gridiron Math</span></a>'
            f"{tabs}</div></nav>")


def patch(src, active):
    """Inject chrome into rendered HTML; replaces an earlier injection or old <nav>."""
    src = re.sub(r"<style id=\"chrome\">.*?</style>", "", src, flags=re.S)
    src = re.sub(r'<nav class="site">.*?</nav>', "", src, flags=re.S)
    src = re.sub(r"<nav>(?:(?!</nav>).)*</nav>\s*", "", src, flags=re.S)
    src = src.replace("</head>", f'<style id="chrome">{CSS}</style></head>', 1)
    return re.sub(r"<body[^>]*>", lambda m: m.group(0) + nav(active), src, count=1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--patch", required=True, help="HTML file to inject chrome into (in place)")
    ap.add_argument("--active", required=True, choices=[p for p, _ in PAGES])
    a = ap.parse_args()
    with open(a.patch) as fh:
        html = fh.read()
    with open(a.patch, "w") as fh:
        fh.write(patch(html, a.active))
    print(a.patch, file=sys.stderr)
