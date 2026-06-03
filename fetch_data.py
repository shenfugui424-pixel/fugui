# -*- coding: utf-8 -*-
"""
抓取 A 股指数估值（蛋卷/雪球，PE/PB 历史分位，与且慢、有知有行同源口径），
再为每个指数在「场外跟踪基金」中按「规模大 > 费率低 > 跟踪误差小」择优：
  1) 以蛋卷给的基金为锚，读取其"跟踪标的"得到精确指数名；
  2) 东财搜索候选基金，用每只基金的"跟踪标的"精确指数名做校验（避免搭错近似指数）；
  3) 在确属同一指数的场外基金里按规模/费率/误差择优。
输出 public/data.json。纯 requests，Python 3.8+ 与 GitHub Actions 均可运行。
"""
import json
import re
import time
import datetime as dt
import os

import requests

HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}
TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "8"))  # 单请求超时(秒)，境外抓国内接口宜短
OUT = os.path.join(os.path.dirname(__file__), "public", "data.json")
MAX_CANDIDATES = 20   # 每个指数最多校验的候选基金数（控制请求量）
TEST_LIMIT = int(os.environ.get("TEST_LIMIT", "0"))  # >0 时只处理前 N 个，便于本机调试
# 抓「基金细节」的总时间预算(秒)：超时即停止补全基金，已抓到的照常出页面，保证任务一定收尾。
# 境外 runner 抓国内接口约 ~40s/板块，46 个全抓约需 30min；Public 仓库 Actions 免费，放宽到 40min 兜底。
FUND_BUDGET = float(os.environ.get("FUND_BUDGET_SEC", "2400"))
_START = None  # main() 启动时间戳


def get(url, referer=None, retries=2):
    h = dict(HDR)
    if referer:
        h["Referer"] = referer
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=h, timeout=TIMEOUT)
            r.encoding = "utf-8"
            if r.status_code == 200:
                return r
            last = "HTTP %s" % r.status_code
        except Exception as e:  # noqa
            last = str(e)
        time.sleep(0.8 * (i + 1))
    raise RuntimeError("GET failed %s : %s" % (url, last))


def _over_budget():
    """基金细节抓取是否已超总时间预算。"""
    return _START is not None and (time.time() - _START) > FUND_BUDGET


# 海外 / 港股 / QDII 指数关键词——本站只看 A 股板块，遇到即剔除
OVERSEAS_KW = [
    "标普", "纳指", "纳斯达克", "道琼斯", "德国", "DAX", "法国", "日经", "东证",
    "MSCI", "恒生", "香港", "H股", "国企指数", "AH", "中概", "中国互联", "互联50",
    "印度", "美国", "海外", "全球", "QDII",
]


def is_overseas(name):
    return any(k in (name or "") for k in OVERSEAS_KW)


def fetch_valuations():
    """蛋卷指数估值列表（截止上一交易日收盘）。返回 list[dict]。"""
    r = get("https://danjuanfunds.com/djapi/index_eva/dj",
            referer="https://danjuanfunds.com/")
    items = r.json().get("data", {}).get("items", [])
    out = []
    for it in items:
        if is_overseas(it.get("name")):
            continue
        pe = it.get("pe") or 0
        pb = it.get("pb") or 0
        pe_pct = it.get("pe_percentile")
        pb_pct = it.get("pb_percentile")
        pcts = []
        # PE 为 0 或负（亏损/周期底部）时不计入 PE 分位，仅用 PB
        if pe and pe > 0 and pe_pct is not None:
            pcts.append(pe_pct)
        if pb and pb > 0 and pb_pct is not None:
            pcts.append(pb_pct)
        if not pcts:
            continue
        temp = round(sum(pcts) / len(pcts) * 100, 1)  # 估值温度 0-100
        fund_code = None
        m = re.search(r"/funding/(\d+)", it.get("url", "") or "")
        if m:
            fund_code = m.group(1)
        out.append({
            "index_code": it.get("index_code"),
            "name": it.get("name"),
            "pe": round(pe, 2) if pe else None,
            "pb": round(pb, 4) if pb else None,
            "pe_pct": round(pe_pct * 100, 1) if pe_pct is not None else None,
            "pb_pct": round(pb_pct * 100, 1) if pb_pct is not None else None,
            "roe": round((it.get("roe") or 0) * 100, 2),
            "div_yield": round((it.get("yeild") or 0) * 100, 2),
            "temp": temp,
            "eva_type": it.get("eva_type"),  # low / normal / high
            "anchor_fund": fund_code,
            "as_of_ts": it.get("ts"),
        })
    return out


# ---------- 基金信息（带缓存） ----------
_JBGK = {}    # code -> {name, fee_mgmt, fee_cust, fee_total, bench_key}
_SCALE = {}   # code -> 规模(亿)
_ERR = {}     # code -> 跟踪误差(%)


def _bench_key(txt):
    """从文本里取精确指数名：优先"跟踪标的"，否则"业绩比较基准"里第一个 ××指数。"""
    m = re.search(r"跟踪标的\s*([一-龥A-Za-z0-9]{2,16}指数)", txt)
    if m:
        return m.group(1)
    m = re.search(r"业绩比较基准\s*([^\n]{4,160})", txt)
    if m:
        mk = re.search(r"([一-龥A-Za-z0-9]{2,16}指数)", m.group(1))
        if mk:
            return mk.group(1)
    return None


def jbgk(code):
    """基本概况：管理费率+托管费率（%/年）+ 精确跟踪指数名。带缓存。"""
    if code in _JBGK:
        return _JBGK[code]
    info = {"name": None, "fee_mgmt": None, "fee_cust": None, "fee_sales": None,
            "fee_total": None, "bench_key": None}
    try:
        r = get("https://fundf10.eastmoney.com/jbgk_%s.html" % code,
                referer="https://fundf10.eastmoney.com/")
        txt = re.sub(r"<[^>]+>", " ", r.text)
        m = re.search(r"管理费率[^%\d]*([\d.]+)\s*%", txt)
        if m:
            info["fee_mgmt"] = float(m.group(1))
        m = re.search(r"托管费率[^%\d]*([\d.]+)\s*%", txt)
        if m:
            info["fee_cust"] = float(m.group(1))
        m = re.search(r"销售服务费率[^%\d]*([\d.]+)\s*%", txt)
        if m:
            info["fee_sales"] = float(m.group(1))
        if any(info[k] is not None for k in ("fee_mgmt", "fee_cust", "fee_sales")):
            # 年持有成本 = 管理费 + 托管费 + 销售服务费（C 类才有，长持更贵）
            info["fee_total"] = round((info["fee_mgmt"] or 0) + (info["fee_cust"] or 0)
                                      + (info["fee_sales"] or 0), 3)
        info["bench_key"] = _bench_key(txt)
    except Exception as e:  # noqa
        print("    jbgk失败", code, e)
    _JBGK[code] = info
    return info


def fund_scale_name(code):
    """pingzhongdata：最新规模(亿) + 基金简称。带缓存。"""
    if code in _SCALE:
        return _SCALE[code]
    name, scale = None, None
    try:
        t = get("https://fund.eastmoney.com/pingzhongdata/%s.js" % code,
                referer="https://fund.eastmoney.com/").text
        m = re.search(r'fS_name\s*=\s*"(.*?)"', t)
        if m:
            name = m.group(1)
        ms = re.search(r"Data_fluctuationScale\s*=\s*(\{.*?\});", t)
        if ms:
            series = json.loads(ms.group(1)).get("series", [])
            if series:
                scale = series[-1].get("y")
    except Exception as e:  # noqa
        print("    规模失败", code, e)
    _SCALE[code] = (name, scale)
    return name, scale


def fund_track_err(code):
    """特色数据页：年化跟踪误差（%）。best-effort，带缓存。"""
    if code in _ERR:
        return _ERR[code]
    val = None
    try:
        r = get("https://fundf10.eastmoney.com/tsdata_%s.html" % code,
                referer="https://fundf10.eastmoney.com/")
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r.text, re.S)
        cells = [re.sub(r"<[^>]+>", "", c).replace("&nbsp;", "").strip() for c in cells]
        for i, c in enumerate(cells):
            if "跟踪误差" in c:
                for nxt in cells[i + 1:i + 4]:
                    mm = re.search(r"([\d.]+)\s*%", nxt)
                    if mm:
                        val = float(mm.group(1))
                        break
            if val is not None:
                break
    except Exception:  # noqa
        pass
    _ERR[code] = val
    return val


def search_candidates(*keys):
    """东财搜索：返回候选场外指数基金 [(code, name)]，排除场内 ETF。"""
    found = {}
    for key in keys:
        if not key:
            continue
        try:
            r = get("https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx"
                    "?m=1&key=" + requests.utils.quote(key),
                    referer="https://fund.eastmoney.com/")
            datas = r.json().get("Datas", []) or []
        except Exception:  # noqa
            continue
        for d in datas:
            if d.get("CATEGORY") != 700:  # 700 = 基金
                continue
            fb = d.get("FundBaseInfo") or {}
            ftype = fb.get("FTYPE") or ""
            nm = (fb.get("NAME") or d.get("NAME") or "").strip()
            code = d.get("CODE")
            if "指数" not in ftype or not code:
                continue
            # 场内 ETF（需券商账户）：名字含 ETF 但不含"联接"。场外联接(ETF联接)/LOF 保留。
            if "ETF" in nm and "联接" not in nm:
                continue
            found.setdefault(code, nm)
    return list(found.items())


def _share_base(name):
    """去掉份额类别后缀，用于 A/C 同基金去重。"""
    return re.sub(r"[ABCDEIO]$", "", (name or "").strip())


def select_fund(row):
    """为指数择优一只场外基金。返回 fund dict。"""
    name = row.get("name") or ""
    anchor = row.get("anchor_fund")

    # 1) 确定锚定的精确指数名 bench_key
    target = None
    if anchor:
        target = jbgk(anchor).get("bench_key")
    cand = search_candidates(name, name.replace("指数", "") + "联接",
                             name.replace("指数", "") + "ETF联接")
    if not target:
        # 蛋卷没给锚：用搜索到的第一只场外基金做锚
        for code, _ in cand:
            bk = jbgk(code).get("bench_key")
            if bk:
                target = bk
                anchor = code
                break
    if not target:
        return {"code": None}

    # 用精确指数名再补一轮候选（核心词搜索更准）
    core = target.replace("指数", "")
    cand += search_candidates(core + "联接", core + "ETF联接")
    seen = {}
    if anchor:
        seen[anchor] = jbgk(anchor)  # 锚也是候选
    for code, _ in cand:
        if code not in seen:
            seen[code] = None
        if len(seen) >= MAX_CANDIDATES:
            break

    # 2) 校验同指数 + 补全规模/误差
    pool = []
    for code in seen:
        info = jbgk(code)
        if info.get("bench_key") != target:
            continue
        nm, scale = fund_scale_name(code)
        err = fund_track_err(code)
        pool.append({
            "code": code, "name": nm,
            "fee_mgmt": info["fee_mgmt"], "fee_cust": info["fee_cust"],
            "fee_sales": info["fee_sales"], "fee_total": info["fee_total"],
            "scale": scale, "track_err": err,
        })
        time.sleep(0.25)

    if not pool:
        return {"code": None}

    # A/C 同基金去重：长期持有优先 A 类（无销售服务费），无 A 类才取规模最大的份额
    dedup = {}
    for f in pool:
        b = _share_base(f["name"])
        cur = dedup.get(b)
        if cur is None:
            dedup[b] = f
            continue
        f_a = (f["name"] or "").endswith("A")
        cur_a = (cur["name"] or "").endswith("A")
        if f_a and not cur_a:
            dedup[b] = f
        elif f_a == cur_a and (f["scale"] or 0) > (cur["scale"] or 0):
            dedup[b] = f
    pool = list(dedup.values())

    # 3) 择优：规模大为前提（≥2亿或≥最大规模的一半），再选费率低、误差小
    maxs = max((f["scale"] or 0) for f in pool)
    big = [f for f in pool if (f["scale"] or 0) >= max(2.0, maxs * 0.5)] or pool
    big.sort(key=lambda f: (
        f["fee_total"] if f["fee_total"] is not None else 9,
        f["track_err"] if f["track_err"] is not None else 9,
        -(f["scale"] or 0),
        0 if (f["name"] or "").endswith("A") else 1,
    ))
    best = big[0]
    best["bench_key"] = target
    best["alt_count"] = len(pool)
    return best


def main():
    global _START
    _START = time.time()
    print("抓取指数估值 ...")
    vals = fetch_valuations()
    print("  指数数量:", len(vals))
    if TEST_LIMIT:
        vals = sorted(vals, key=lambda x: x["temp"])[:TEST_LIMIT]
        print("  [调试] 仅处理前", TEST_LIMIT, "个最低估指数")
    # 先按温度排序，优先为最低估（最值得看）的板块补全基金；万一超时，靠前的都有数据
    vals.sort(key=lambda x: x["temp"])

    skipped = 0
    for idx, row in enumerate(vals, 1):
        if _over_budget():
            row["fund"] = {"code": None}
            row.pop("anchor_fund", None)
            skipped += 1
            continue
        try:
            fund = select_fund(row)
        except Exception as e:  # noqa
            print("  选基异常", row.get("name"), e)
            fund = {"code": None}
        row["fund"] = fund
        row.pop("anchor_fund", None)
        print("  [%d/%d] %-8s 温度=%-5s 基金=%s %s 规模=%s 费率=%s 误差=%s 可选%s" % (
            idx, len(vals), row["name"], row["temp"], fund.get("code"),
            fund.get("name"), fund.get("scale"), fund.get("fee_total"),
            fund.get("track_err"), fund.get("alt_count")))

    if skipped:
        print("  [预算] 超过 %ds，%d 个板块未补全基金（标为待补充），估值数据完整" % (FUND_BUDGET, skipped))
    vals.sort(key=lambda x: x["temp"])  # 估值从低到高

    ts = vals[0].get("as_of_ts") if vals else None
    for v in vals:
        v.pop("as_of_ts", None)
    as_of = dt.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d") if ts else None
    payload = {
        "as_of": as_of,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "count": len(vals),
        "items": vals,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("已写出", OUT)


if __name__ == "__main__":
    main()
