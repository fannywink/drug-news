"""
카드뉴스 생성 (2단계)

- collect_and_summarize.py가 만든 JSON을 읽어 1080×1350 PNG 카드뉴스로 만듦
- 구성: 표지 → 분야별 기사(요약) → 오늘의 한마디
- 한 장에 기사 2건을 넣되, 넘치면 자동으로 1건씩 나눔
- 기사마다 번호를 붙이고, 같은 번호로 원문 링크를 모은 카톡용 텍스트(links.txt)를 함께 만듦
- 웹페이지(index.html)에는 카드뉴스 장마다 바로 아래에 해당 기사 원문 링크를 붙임 → 카톡 버튼이 이 페이지로 연결됨

단독 실행: python make_cardnews.py output/20261028.json
"""

import html
import os
import sys
import json
from datetime import datetime

from playwright.sync_api import sync_playwright

W, H = 1080, 1350
ORG = "경기도약사회 마약퇴치사업본부"
ADDRESS = "경기도 수원시 팔달구 경수대로 708 3층"
SERIES = "마약류 뉴스 브리핑"
WEEKDAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]

# 웹폰트(Pretendard). 인터넷이 안 되면 맑은 고딕으로 표시됨
FONT_LINK = ('<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/'
             'pretendard@v1.3.9/dist/web/static/pretendard.min.css">')
if os.environ.get("NO_WEBFONT"):
    FONT_LINK = ""

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--pine:#123C36;--paper:#F4F7F6;--mint:#DCEBE6;--amber:#E8A33D;--amber-ink:#94590A;
      --ink:#1D2624;--muted:#5E6E6A;--line:#C9D8D3}
html,body{background:var(--paper)}
body{font-family:'Pretendard','Malgun Gothic','Apple SD Gothic Neo','Noto Sans KR','Noto Sans CJK KR',sans-serif;
     color:var(--ink);word-break:keep-all;overflow-wrap:break-word}
.card{width:1080px;height:1350px;overflow:hidden;position:relative;background:var(--paper);
      padding:88px 88px 110px;display:flex;flex-direction:column}
.foot{position:absolute;left:88px;right:88px;bottom:52px;display:flex;justify-content:space-between;
      font-size:22px;color:var(--muted)}

/* 표지 */
.cover{background:var(--pine);color:#fff}
.cover .org{font-size:26px;font-weight:600;opacity:.85}
.capsule{position:absolute;top:70px;right:-70px;width:400px;height:150px;border-radius:75px;
         transform:rotate(-28deg);overflow:hidden;display:flex}
.capsule i{flex:1}
.capsule i:first-child{background:var(--amber)}
.capsule i:last-child{background:#EAF3F0}
.cover .date{margin-top:150px;display:flex;align-items:baseline;gap:26px}
.cover .md{font-size:210px;font-weight:800;line-height:.9;letter-spacing:-6px}
.cover .dow{font-size:34px;font-weight:600;opacity:.8}
.cover .series{margin-top:40px;font-size:34px;font-weight:700;color:var(--amber)}
.cover .sample{margin-left:14px;padding:3px 14px;border:2px solid var(--amber);border-radius:999px;
               font-size:22px;vertical-align:middle}
.cover .headline{margin-top:24px;font-size:62px;font-weight:800;line-height:1.3;letter-spacing:-1.5px;max-width:880px}
.cover .toc{margin-top:auto;list-style:none;border-top:2px solid rgba(255,255,255,.3)}
.cover .toc li{display:flex;justify-content:space-between;padding:20px 0;
               border-bottom:1px solid rgba(255,255,255,.15);font-size:30px}
.cover .toc b{font-weight:700}
.cover .foot{color:rgba(255,255,255,.65)}

/* 기사 페이지: 기본(2건용) — 휴대폰에서 읽기 좋게 본문 크게 */
.bar{display:flex;justify-content:space-between;align-items:center;padding-bottom:24px;
     border-bottom:3px solid var(--pine);margin-bottom:40px}
.bar .cat{font-size:36px;font-weight:800;color:var(--pine)}
.bar .pg{font-size:26px;color:var(--muted)}
.item + .item{margin-top:40px;padding-top:40px;border-top:2px solid var(--line)}
.item h2{font-size:50px;font-weight:800;line-height:1.3;letter-spacing:-1px}
.no{display:inline-flex;align-items:center;justify-content:center;width:1.4em;height:1.4em;margin-right:.4em;
    border-radius:50%;background:var(--pine);color:#fff;font-size:.68em;vertical-align:.12em}
.item .sum{margin-top:18px;font-size:39px;line-height:1.55}
.item .meta{margin-top:14px;display:flex;align-items:center;gap:16px;font-size:28px;color:var(--muted)}
.flag{font-size:26px;font-weight:700;color:var(--pine);background:var(--mint);padding:4px 14px;border-radius:8px}
/* 1건 페이지 */
.solo .item h2{font-size:62px}
.solo .item .sum{margin-top:32px;font-size:48px;line-height:1.6}
.solo .item .meta{margin-top:22px;font-size:32px}
.solo .flag{font-size:30px;padding:6px 16px}
/* 넘칠 때 */
.tight .item h2{font-size:44px}
.tight .item .sum{font-size:34px}

/* 마무리 */
.closing .label{font-size:32px;font-weight:800;color:var(--pine)}
.closing .quote{margin-top:44px;font-size:48px;font-weight:700;line-height:1.5;letter-spacing:-1px;
                border-left:10px solid var(--amber);padding-left:40px}
.closing .contact{margin-top:auto;background:var(--pine);color:#fff;border-radius:20px;padding:40px 44px}
.closing .contact .o{font-size:32px;font-weight:800}
.closing .contact p{font-size:26px;margin-top:10px;opacity:.85;line-height:1.5}
.closing .note{margin-top:26px;font-size:22px;color:var(--muted)}
.closing{padding-bottom:88px}
"""


def esc(s):
    return html.escape(str(s or ""))


def shell(inner, cls):
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8">{FONT_LINK}'
            f'<style>{CSS}</style></head><body><main class="card {cls}">{inner}</main></body></html>')


def parse_date(summary):
    try:
        d = datetime.strptime(summary.get("date", ""), "%Y.%m.%d")
    except ValueError:
        d = datetime.now()
    return d


def cover(summary):
    d = parse_date(summary)
    cats = summary.get("categories", [])
    total = sum(len(c["items"]) for c in cats)
    toc = "".join(f'<li><span>{esc(c["name"])}</span><b>{len(c["items"])}건</b></li>' for c in cats)
    sample = '<span class="sample">디자인 예시</span>' if summary.get("sample") else ""
    inner = f"""
      <div class="capsule"><i></i><i></i></div>
      <p class="org">{ORG}</p>
      <div class="date"><span class="md">{d.month}.{d.day:02d}</span><span class="dow">{WEEKDAYS[d.weekday()]}</span></div>
      <p class="series">{SERIES}{sample}</p>
      <h1 class="headline">{esc(summary.get("headline"))}</h1>
      <ul class="toc">{toc}</ul>
      <div class="foot"><span>오늘 {total}건의 사안을 정리했습니다</span><span>{d.year}</span></div>"""
    return shell(inner, "cover")


def item_page(cat_name, items, pg_label, mode=""):
    blocks = ""
    for it in items:
        flag = '<span class="flag">청소년 관련</span>' if it.get("youth") else ""
        press = ", ".join(dict.fromkeys(s["press"] for s in it.get("sources", [])))
        blocks += f"""
        <article class="item">
          <h2><span class="no">{it.get("_no", "")}</span>{esc(it.get("title"))}</h2>
          <p class="sum">{esc(it.get("summary"))}</p>
          <p class="meta"><span>출처 {esc(press)}</span>{flag}</p>
        </article>"""
    inner = f"""
      <header class="bar"><span class="cat">{esc(cat_name)}</span><span class="pg">{pg_label}</span></header>
      {blocks}
      <div class="foot"><span>{ORG}</span><span>{SERIES}</span></div>"""
    return shell(inner, mode)


def closing(summary):
    inner = f"""
      <p class="label">오늘의 한마디</p>
      <p class="quote">{esc(summary.get("daily_comment"))}</p>
      <div class="contact">
        <p class="o">{ORG}</p>
        <p>{ADDRESS}</p>
      </div>
      <p class="note">기사 원문은 카드뉴스 페이지에서 각 기사 바로 아래 링크로 볼 수 있습니다.</p>"""
    return shell(inner, "closing")


def number_items(summary):
    """카드뉴스와 링크 모음에 같은 번호를 쓰도록 기사에 순번을 매김"""
    n = 0
    for cat in summary.get("categories", []):
        for it in cat["items"]:
            n += 1
            it["_no"] = n


def links_text(summary):
    """카톡에 붙여 넣을 기사 원문 링크 모음 (카톡에서 주소가 자동으로 링크가 됨)"""
    d = parse_date(summary)
    lines = [f"📰 기사 원문 모음 ({d.month}.{d.day:02d})", ""]
    for cat in summary.get("categories", []):
        lines.append(f"[{cat['name']}]")
        for it in cat["items"]:
            lines.append(f"{it['_no']}. {it.get('title', '')}")
            for src in it.get("sources", []):
                lines.append(f"  {src['press']} {src['url']}")
        lines.append("")
    if len(lines) == 2:
        lines.append("오늘은 정리된 기사가 없습니다.")
    return "\n".join(lines).rstrip()


WEB_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--pine:#123C36;--paper:#F4F7F6;--mint:#DCEBE6;--ink:#1D2624;--muted:#5E6E6A;--line:#C9D8D3;--surface:#fff}
@media (prefers-color-scheme: dark){:root{--pine:#7FC4B4;--paper:#0F1716;--mint:#1E3330;--ink:#E4ECEA;--muted:#9AABA7;
  --line:#2A3B38;--surface:#16211F}}
body{font-family:'Pretendard','Malgun Gothic','Apple SD Gothic Neo',sans-serif;background:var(--paper);color:var(--ink);
     word-break:keep-all;line-height:1.6;font-size:21px}
.wrap{max-width:600px;margin:0 auto;padding:28px 14px 60px}
.org{font-size:18px;color:var(--muted)}
h1{font-size:30px;margin:6px 0 22px;line-height:1.35}
.card img{display:block;width:100%;height:auto;border-radius:12px}
.card{margin-bottom:28px}
.links{margin-top:10px;display:grid;gap:10px}
.art{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:16px 18px}
.art .t{font-weight:700;font-size:22px;line-height:1.45}
.no{display:inline-flex;width:30px;height:30px;border-radius:50%;background:var(--pine);color:var(--paper);
    font-size:17px;align-items:center;justify-content:center;margin-right:8px;vertical-align:3px}
.art a{display:block;margin-top:10px;padding:12px 14px;border-radius:10px;background:var(--mint);color:var(--pine);
       font-weight:700;font-size:21px;text-decoration:none}
.art a:hover,.art a:focus{text-decoration:underline}
.foot{margin-top:40px;font-size:18px;color:var(--muted)}
"""


def web_page(summary, pages_meta):
    """pages_meta: [(이미지 파일, 그 장에 실린 기사 목록)] — 기사 장 바로 아래에 원문 링크를 붙임"""
    d = parse_date(summary)
    body = ""
    for i, (f, items) in enumerate(pages_meta, 1):
        links = ""
        for it in items:
            btns = "".join(f'<a href="{esc(s["url"])}" target="_blank" rel="noopener">{esc(s["press"])} 원문 보기 →</a>'
                           for s in it.get("sources", []))
            links += f'<div class="art"><p class="t"><span class="no">{it["_no"]}</span>{esc(it.get("title"))}</p>{btns}</div>'
        links = f'<div class="links">{links}</div>' if links else ""
        body += f'<section class="card"><img src="{os.path.basename(f)}" alt="카드뉴스 {i}쪽" loading="lazy">{links}</section>'
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>{SERIES} {d.month}.{d.day:02d}</title>{FONT_LINK}<style>{WEB_CSS}</style></head>
<body><main class="wrap">
<p class="org">{ORG}</p><h1>{SERIES} {d.year}.{d.month:02d}.{d.day:02d}</h1>
{body}
<p class="foot">{ORG}</p>
</main></body></html>"""


def render(summary, outdir):
    os.makedirs(outdir, exist_ok=True)
    number_items(summary)
    files = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H})

        def load(h):
            page.set_content(h, wait_until="load", timeout=20000)
            page.evaluate("document.fonts.ready.then(() => true)")

        def fits(h):
            load(h)
            return page.evaluate(
                "() => { const c = document.querySelector('.card'); return c.scrollHeight <= c.clientHeight; }")

        # 한 장에 2건 → 안 들어가면 1건(크게 → 보통 → 축소 순으로 시도)
        plan = []
        for cat in summary.get("categories", []):
            items, i = cat["items"], 0
            while i < len(items):
                if i + 1 < len(items) and fits(item_page(cat["name"], items[i:i + 2], "")):
                    plan.append((cat["name"], items[i:i + 2], ""))
                    i += 2
                    continue
                one = items[i:i + 1]
                mode = next((m for m in ("solo", "") if fits(item_page(cat["name"], one, "", m))), "tight")
                plan.append((cat["name"], one, mode))
                i += 1

        total = len(plan) + 2
        pages = [cover(summary)]
        pages += [item_page(c, its, f"{n + 2} / {total}", m) for n, (c, its, m) in enumerate(plan)]
        pages.append(closing(summary))

        page_items = [[]] + [its for (_, its, _) in plan] + [[]]
        for n, h in enumerate(pages, 1):
            load(h)
            path = os.path.join(outdir, f"card_{n:02d}.png")
            page.locator(".card").screenshot(path=path)
            files.append(path)
        browser.close()
    with open(os.path.join(outdir, "links.txt"), "w", encoding="utf-8") as f:
        f.write(links_text(summary))
    with open(os.path.join(outdir, "index.html"), "w", encoding="utf-8") as f:
        f.write(web_page(summary, list(zip(files, page_items))))
    print(f"[카드뉴스] {len(files)}장 + 링크 모음 + 웹페이지 저장 → {outdir}")
    return files


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "sample_summary.json"
    with open(src, encoding="utf-8") as f:
        data = json.load(f)
    render(data, os.path.splitext(src)[0] + "_cards")
