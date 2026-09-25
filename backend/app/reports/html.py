from html import escape as e

_CSS = """body{font:14px/1.5 system-ui,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#111}
table{border-collapse:collapse;width:100%;margin:6px 0}td,th{border:1px solid #ccc;padding:4px 8px;text-align:left;
vertical-align:top;word-break:break-word}section{border-top:2px solid #333;margin-top:24px}
.warn{background:#fff3cd;padding:8px;border:1px solid #e0c060}.note{background:#eef;padding:8px}
small{display:block}"""


def _item(it) -> str:
    if isinstance(it, str):
        return f"<li>{e(it)}</li>"
    links = "".join(f'<small><a href="{e(l["url"])}">{e(l["label"])}</a></small>' for l in it.get("links", []))
    return f"<li>{e(it['text'])}{links}</li>"


def _block(b: dict) -> str:
    if "p" in b:
        return f"<p>{e(b['p'])}</p>"
    if "list" in b:
        return f"<ul>{''.join(_item(i) for i in b['list'])}</ul>"
    t = b["table"]
    head = "".join(f"<th>{e(h)}</th>" for h in t["headers"]) if any(t["headers"]) else ""
    rows = "".join("<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in r) + "</tr>" for r in t["rows"])
    return f"<table>{f'<tr>{head}</tr>' if head else ''}{rows or '<tr><td>None</td></tr>'}</table>"


def render(doc: dict) -> str:
    warn = f'<p class="warn">{e(doc["warning"])}</p>' if doc.get("warning") else ""
    body = "".join(f"<section><h2>{e(s['title'])}</h2>{''.join(_block(b) for b in s['blocks'])}</section>"
                   for s in doc["sections"])
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>{e(doc["title"])}</title>'
            f"<style>{_CSS}</style></head><body><h1>{e(doc['title'])}</h1>{warn}"
            f'<p class="note">{e(doc["notice"])}</p>{body}</body></html>')
