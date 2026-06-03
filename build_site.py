# -*- coding: utf-8 -*-
"""读取 public/data.json，生成自包含的 public/index.html（数据内嵌，离线可看）。"""
import json
import os
import html

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "public", "data.json")
OUT = os.path.join(HERE, "public", "index.html")


def temp_color(t):
    # 绿(低估) -> 黄 -> 红(高估)
    if t < 20:
        return "#0aa45a"
    if t < 30:
        return "#52b13a"
    if t < 50:
        return "#c9a227"
    if t < 70:
        return "#e08a1e"
    if t < 85:
        return "#e2632a"
    return "#d92d2d"


def eva_label(e, t):
    if e == "low" or t < 30:
        return "低估", "#0aa45a"
    if e == "high" or t >= 70:
        return "高估", "#d92d2d"
    return "适中", "#e08a1e"


def fmt(v, suffix="", dash="—"):
    if v is None or v == "":
        return dash
    return "%s%s" % (v, suffix)


def card(i, row):
    t = row["temp"]
    col = temp_color(t)
    lab, labcol = eva_label(row.get("eva_type"), t)
    name = html.escape(row["name"] or "")
    code = html.escape(row.get("index_code") or "")
    pe = fmt(row.get("pe"))
    pb = fmt(row.get("pb"))
    pe_pct = fmt(row.get("pe_pct"), "%")
    pb_pct = fmt(row.get("pb_pct"), "%")
    dvd = fmt(row.get("div_yield"), "%")
    roe = fmt(row.get("roe"), "%")

    f = row.get("fund") or {}
    if f.get("code"):
        alt = f.get("alt_count") or 0
        alt_html = ('<span class="alt">%d只中择优</span>' % alt) if alt > 1 else ""
        parts = []
        if f.get("fee_mgmt") is not None:
            parts.append("管理%.2f" % f["fee_mgmt"])
        if f.get("fee_cust") is not None:
            parts.append("托管%.2f" % f["fee_cust"])
        if f.get("fee_sales"):
            parts.append("销售%.2f" % f["fee_sales"])
        fee_detail = ("+".join(parts) + "%") if parts else ""
        fund_html = """
        <div class="fund">
          <div class="fund-h">场外跟踪基金 · {fcode} {alt}</div>
          <div class="fund-name">{fname}</div>
          <div class="fund-metrics">
            <div><span>规模</span><b>{scale}</b></div>
            <div><span>费率/年</span><b>{fee}</b><em>{fee_detail}</em></div>
            <div><span>跟踪误差</span><b>{terr}</b></div>
          </div>
        </div>""".format(
            fcode=html.escape(f.get("code") or ""),
            alt=alt_html,
            fname=html.escape(f.get("name") or "—"),
            scale=fmt(f.get("scale"), " 亿"),
            fee=fmt(f.get("fee_total"), "%"),
            fee_detail=fee_detail,
            terr=fmt(f.get("track_err"), "%"),
        )
    else:
        fund_html = '<div class="fund nofund">场外基金待补充</div>'

    return """
    <div class="card">
      <div class="top">
        <div class="rank">#{i}</div>
        <div class="title">
          <div class="nm">{name}</div>
          <div class="ic">{code}</div>
        </div>
        <div class="temp" style="color:{col}">
          <div class="tnum">{t}</div>
          <div class="tlab" style="background:{labcol}">{lab}</div>
        </div>
      </div>
      <div class="bar"><i style="width:{t}%;background:{col}"></i></div>
      <div class="grid">
        <div><span>PE</span><b>{pe}</b><em>分位 {pe_pct}</em></div>
        <div><span>PB</span><b>{pb}</b><em>分位 {pb_pct}</em></div>
        <div><span>股息率</span><b>{dvd}</b></div>
        <div><span>ROE</span><b>{roe}</b></div>
      </div>
      {fund_html}
    </div>""".format(i=i, name=name, code=code, col=col, t=t, lab=lab,
                     labcol=labcol, pe=pe, pe_pct=pe_pct, pb=pb, pb_pct=pb_pct,
                     dvd=dvd, roe=roe, fund_html=fund_html)


def main():
    with open(DATA, encoding="utf-8") as fp:
        data = json.load(fp)
    items = data.get("items", [])
    cards = "\n".join(card(i, r) for i, r in enumerate(items, 1))

    page = TEMPLATE.format(
        as_of=html.escape(data.get("as_of") or "—"),
        generated_at=html.escape(data.get("generated_at") or "—"),
        count=len(items),
        cards=cards,
    )
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write(page)
    print("已生成", OUT, "板块数", len(items))


TEMPLATE = u"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>A股板块估值温度榜</title>
<style>
:root{{--bg:#f5f6f8;--card:#fff;--ink:#1c1f23;--sub:#8a9099;--line:#eceef1}}
*{{box-sizing:border-box;-webkit-tap-highlight-color:transparent}}
body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--ink)}}
.wrap{{max-width:760px;margin:0 auto;padding:16px 12px 40px}}
header{{padding:6px 4px 14px}}
h1{{font-size:21px;margin:0 0 6px;font-weight:700}}
.meta{{font-size:13px;color:var(--sub);line-height:1.6}}
.note{{font-size:12px;color:var(--sub);background:#fff;border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:12px 0;line-height:1.7}}
.legend{{display:flex;gap:10px;flex-wrap:wrap;font-size:12px;color:var(--sub);margin:6px 2px 0}}
.legend i{{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:4px;vertical-align:middle}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin:11px 0;box-shadow:0 1px 2px rgba(0,0,0,.03)}}
.top{{display:flex;align-items:center;gap:10px}}
.rank{{font-size:13px;color:var(--sub);font-weight:600;min-width:30px}}
.title{{flex:1;min-width:0}}
.nm{{font-size:17px;font-weight:700}}
.ic{{font-size:12px;color:var(--sub);margin-top:1px}}
.temp{{text-align:right}}
.tnum{{font-size:26px;font-weight:800;line-height:1}}
.tlab{{display:inline-block;color:#fff;font-size:11px;padding:1px 7px;border-radius:8px;margin-top:4px}}
.bar{{height:7px;background:#eef0f2;border-radius:6px;overflow:hidden;margin:11px 0 12px}}
.bar i{{display:block;height:100%;border-radius:6px}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}}
.grid>div{{background:#fafbfc;border:1px solid var(--line);border-radius:9px;padding:7px 8px;text-align:center}}
.grid span{{display:block;font-size:11px;color:var(--sub)}}
.grid b{{display:block;font-size:15px;margin-top:2px}}
.grid em{{display:block;font-style:normal;font-size:10px;color:var(--sub);margin-top:1px}}
.fund{{margin-top:11px;border-top:1px dashed var(--line);padding-top:11px}}
.fund-h{{font-size:12px;color:var(--sub)}}
.fund-name{{font-size:14px;font-weight:600;margin:3px 0 8px}}
.fund-metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}
.fund-metrics>div{{background:#f3f8ff;border-radius:9px;padding:7px;text-align:center}}
.fund-metrics span{{display:block;font-size:11px;color:var(--sub)}}
.fund-metrics b{{display:block;font-size:14px;margin-top:2px}}
.fund-metrics em{{display:block;font-style:normal;font-size:10px;color:var(--sub);margin-top:1px}}
.alt{{display:inline-block;background:#eaf3ff;color:#2b6fd6;font-size:10px;padding:1px 6px;border-radius:7px;margin-left:4px}}
.nofund{{color:var(--sub);font-size:13px;text-align:center}}
footer{{text-align:center;color:var(--sub);font-size:11px;margin-top:26px;line-height:1.7}}
@media(max-width:480px){{.grid{{grid-template-columns:repeat(2,1fr)}}}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>A股板块估值温度榜</h1>
  <div class="meta">截止 <b>{as_of}</b> 收盘 · 共 {count} 个板块 · 按估值温度从低到高排序<br>数据更新于 {generated_at}（每日 08:00 自动刷新）</div>
  <div class="legend">
    <span><i style="background:#0aa45a"></i>低估 &lt;30</span>
    <span><i style="background:#e08a1e"></i>适中 30-70</span>
    <span><i style="background:#d92d2d"></i>高估 &gt;70</span>
  </div>
  <div class="note">估值温度 = 该板块当前 PE、PB 在近 10 年历史中的百分位综合值（0-100，越低越被低估），口径参考「且慢」「有知有行」。温度越低代表估值越处历史低位、未来均值回归上行空间越大。<b>低估不等于一定上涨，本页仅供参考，不构成投资建议。</b>场外基金在同指数的多只基金中按「规模大 &gt; 费率低 &gt; 跟踪误差小」择优，长期持有优先 A 类，费率为年持有成本（管理+托管+销售服务费）。</div>
</header>
{cards}
<footer>数据来源：蛋卷基金（估值）/ 天天基金（基金规模·费率·跟踪误差）<br>本页为个人研究工具，不构成任何投资建议，据此操作风险自负。</footer>
</div>
</body>
</html>
"""


if __name__ == "__main__":
    main()
