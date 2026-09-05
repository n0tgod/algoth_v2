#!/usr/bin/env python3
"""Замер раскладки плиток страницы DCA настоящим браузером.

Владелец сказал «криво выглядит» — и криво было по трём измеренным
причинам, а не по ощущению: подпись из двух строк опускала значение на
18 px ниже соседних, сетка `auto-fit` оставляла в последнем ряду дыру
336 px (на 1200 px — 822), а главные плитки ничем не отличались от
второстепенных. Ни одну из трёх харнесс страниц поймать не может: он
исполняет JS, но не считает CSS-раскладку.

Поэтому замер идёт браузером, и правила берутся ВЫРЕЗКОЙ из `web.py`,
а не копией: копия разошлась бы со страницей, и мерили бы мы не её.
В сюиту прогон не входит — Chromium в неё не тянем; из сюиты
проверяются правило выбора колонок (числами, харнесс) и несущие
правила CSS (источником).

    .venv/bin/python research/b1_book/layout_check.py          # таблица
    .venv/bin/python research/b1_book/layout_check.py --fail   # и вердикт

`--fail` роняет прогон, если у какого-то блока остался хвост в
последнем ряду или значения в ряду стоят не на одной высоте.
"""
import io, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
WIDTHS = (1600, 1400, 1200, 1000, 900, 700, 500)

# Плитки — те же, что строит `statBlock`: длинные подписи («среднее
# время в сделке») и есть предмет замера, короткий набор ничего бы не
# показал.
MAIN = [("стратегия заработала", "+95.56 $ <span style='font-size:.62em'>"
         "(+9.56 %)</span>"),
        ("открытый pnl", "+0.94 $"), ("открытых позиций", "22"),
        ("просадка депозита", "&minus;2.50 %"),
        ("просадка открытых", "&minus;86.43 $ <span "
         "style='font-size:.62em'>(&minus;8.64 %)</span>")]
CELLS = [("закрытых позиций", "388"), ("входов (с доливами)", "527"),
         ("из них бэктест", "388"), ("из них по котировке", "70"),
         ("имён", "284"), ("дней", "28"), ("прибыльных сделок", "69.8 %"),
         ("среднее время в сделке", "39.6 ч"), ("медиана дня", "+0.077 %"),
         ("худший день", "&minus;2.25 %"), ("зелёных дней", "0.61"),
         ("укус", "5.1"), ("$ без лучшего имени", "+91.41 $"),
         ("$ без 3 лучших дней", "&minus;1.28 $"),
         ("худшая открытая", "&minus;2.01 %"), ("оборвано записью", "11")]
BOOK = [("режим", "безопасная"), ("депозит", "$10,000"), ("мест", "400"),
        ("билет", "$25"), ("строк в журнале", "77 965"), ("правила", "v5")]


def _tiles(rows):
    return "".join("<div class=st><div class=k>%s</div>"
                   "<div class='v mono'>%s</div></div>" % r for r in rows)


def build(path):
    """Страница замера: CSS и раскладка — вырезкой из `web.py`."""
    import web
    page = web.DCAPAGE
    css = page[page.index("<style>") + 7:page.index("</style>")]
    a = page.index("function fitGrid(el){")
    b = page.index('addEventListener("resize", fitGrids);')
    fit = page[a:b]
    html = """<!doctype html><meta charset="utf-8"><style>%s</style>
<div class=wrap>
<div class=panel><div class=cap>счёт</div>
<div class='stats main' data-min=210 id=g1>%s</div>
<div class=stats id=g2>%s</div></div>
<div class=panel><div class=cap>книга</div>
<div class=stats id=g3>%s</div></div></div>
<pre id=out></pre>
<script>
%s
fitGrids();
function rows(id){
  const by = new Map();
  for (const e of document.getElementById(id).children){
    const r = e.getBoundingClientRect(), k = Math.round(r.top);
    if (!by.has(k)) by.set(k, []);
    by.get(k).push({w: Math.round(r.width),
      vy: Math.round(e.querySelector(".v").getBoundingClientRect().top)});
  }
  return [...by.entries()].sort((a,b)=>a[0]-b[0]).map(x=>x[1]);
}
function dump(name, id){
  const rs = rows(id), box = document.getElementById(id)
    .getBoundingClientRect();
  const last = rs[rs.length - 1];
  const used = last.reduce((a,c)=>a+c.w,0) + 10 * (last.length - 1);
  const off = Math.max(...rs.map(r =>
    Math.max(...r.map(c=>c.vy)) - Math.min(...r.map(c=>c.vy))));
  return name + " · рядов " + rs.length + " (" + rs.map(r=>r.length).join("+")
    + ") · хвост " + Math.max(0, Math.round(box.width - used))
    + " px · значения по высоте " + off + " px";
}
document.getElementById("out").textContent = [
  "ширина окна " + window.innerWidth,
  dump("главные", "g1"), dump("второстепенные", "g2"), dump("книга", "g3")
].join("\\n");
</script>""" % (css, _tiles(MAIN), _tiles(CELLS), _tiles(BOOK), fit)
    io.open(path, "w", encoding="utf-8").write(html)


def measure(path, width):
    r = subprocess.run(
        [CHROME, "--headless", "--no-sandbox", "--disable-gpu",
         "--window-size=%d,1600" % width, "--dump-dom", "file://" + path],
        capture_output=True, text=True, timeout=120)
    dom = r.stdout
    i = dom.find('<pre id="out">')
    if i < 0:
        raise SystemExit("браузер не отдал замер:\n" + (r.stderr[-400:]))
    out = dom[i + len('<pre id="out">'):dom.index("</pre>", i)]
    return out.replace("&amp;", "&").strip()


def main():
    if not os.path.exists(CHROME):
        raise SystemExit("Chromium не найден: " + CHROME +
                         " — замер раскладки требует браузера")
    d = tempfile.mkdtemp()
    path = os.path.join(d, "layout.html")
    build(path)
    bad = []
    for w in WIDTHS:
        txt = measure(path, w)
        print(txt)
        for ln in txt.split("\n")[1:]:
            # Допуск в 4 px — округление ширины колонок, а не дыра:
            # `1fr` делит остаток и оставляет доли пикселя на ряд.
            tail = int(re.search(r"хвост (\d+) px", ln).group(1))
            off = int(re.search(r"высоте (\d+) px", ln).group(1))
            if tail > 4 or off:
                bad.append(ln.strip())
        print()
    if bad:
        print("НЕ СОШЛОСЬ (%d):" % len(bad))
        for b in bad:
            print("  " + b)
    else:
        print("хвоста нет ни в одном блоке, значения на одной высоте")
    if "--fail" in sys.argv and bad:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
