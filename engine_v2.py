# -*- coding: utf-8 -*-
"""
悦检 v2 · 分析引擎
==================
输入：regions{区域:值}, profile, questionnaire
输出：结构化结果（逐系统分析 + 主要矛盾/主要方面 + 六维统一综合建议 + 就医/用药/趋势预警/宣教）

核心方法（对应岗位要求的"专业纵深 + AI 工作流 + 产品化"）：
- 系统聚合：每系统统计异常区域数、最大偏离、风险评分
- 风险分级：正常 / 低风险 / 中风险 / 高风险
- 矛盾论综合研判：从所有系统中揪出「主要矛盾」（最突出的系统），
  在该系统指出「主要方面」（最关键异常区域）与「次要方面」
- 六维统一综合建议：饮食/运动/睡眠/用药/情绪管理/生活方式
  —— 按「主要矛盾系统优先」合成统一建议，不在报告里逐系统罗列让用户不知所措
- 就医/用药/趋势预警/健康宣教：把"下一步该做什么"说清楚
"""

import re

# 系统联动链（查理·芒格：多元思维 / lollapalooza——单点异常常牵动一串）
SYSTEM_LINKS = [
    ("神经 ↔ 内分泌 ↔ 心血管",
     "神经（睡眠/压力）失调会扰动内分泌激素，进而推高心血管负荷——这是『压力型慢病』主干链，优先稳住睡眠与情绪。"),
    ("消化 ↔ 免疫",
     "肠道是最大免疫器官，消化偏差常伴随免疫失衡；调肠（饮食/益生菌/规律三餐）往往同步改善免疫。"),
    ("呼吸 ↔ 心血管",
     "长期缺氧（呼吸偏差）迫使心血管加倍做功；呼吸训练与有氧能同时为两者减负。"),
    ("内分泌 ↔ 骨骼肌肉",
     "激素（尤其性激素/甲状腺）参与骨代谢，内分泌偏差不及时纠，骨量易流失。"),
    ("神经 ↔ 免疫",
     "长期高压抑制免疫监视；减压（正念/睡眠）是低成本提升免疫的方式。"),
]

from hra_knowledge import (SYSTEM_OF, SYSTEM_ORDER, SYSTEM_META, SYSTEM_FINDINGS,
                           DIM_ADVICE, GENERAL, SYSTEM_DIET, SYSTEM_MEDICAL,
                           SYSTEM_MEDICATION, SYSTEM_TREND, SYSTEM_EDU, NORMAL_RANGE)


def _status(v):
    if abs(v) <= NORMAL_RANGE:
        return "正常"
    if v < -NORMAL_RANGE:
        return "功能偏低·风险"
    return "功能偏高·活跃"


def _risk_level(items):
    """items: [(区域,值)] -> (risk, score0-100, maxabs, abn_list, raw_累计偏离)

    - raw：所有区域绝对偏离值累加（原始强度，可能 >100，如骨骼系统可达 1441）
    - score：归一化风险指数 0-100（异常区域占比 60% + 最大偏离 40%），便于普通人横向对比
    """
    vals = [v for _, v in items]
    abn = [(r, v) for r, v in items if abs(v) > NORMAL_RANGE]
    raw = sum(abs(v) for v in vals)          # 原始累计偏离强度
    maxabs = max(abs(v) for v in vals) if vals else 0
    n = len(items)
    prop = len(abn) / n if n else 0
    # 归一化风险指数 0-100：异常占比(60%) + 最大偏离(40%) 折算
    score = min(100, round((prop * 0.6 + min(maxabs, 100) / 100 * 0.4) * 100))
    if not abn:
        return "正常", score, maxabs, abn, raw
    if maxabs >= 50 or prop >= 0.5:
        risk = "高风险"
    elif maxabs >= 35 or prop >= 0.3:
        risk = "中风险"
    else:
        risk = "低风险"
    return risk, score, maxabs, abn, raw


def analyze(regions, profile=None, q=None):
    profile = profile or {}
    q = q or {}

    # 1) 按系统分组
    sys_items = {}
    for r, v in regions.items():
        s = SYSTEM_OF.get(r, "其他系统")
        sys_items.setdefault(s, []).append((r, v))

    # 2) 逐系统分析
    systems = []
    for s in SYSTEM_ORDER:
        items = sys_items.get(s)
        if not items:
            continue
        risk, score, maxabs, abn, raw = _risk_level(items)
        systems.append({
            "system": s,
            "meta": SYSTEM_META.get(s, {}),
            "items": sorted(items, key=lambda x: -abs(x[1])),
            "abn": abn,
            "score": score,
            "raw": raw,
            "maxabs": maxabs,
            "risk": risk,
            "findings": SYSTEM_FINDINGS.get(s, ""),
            "n_total": len(items),
            "n_abn": len(abn),
        })
    # 按原始累计偏离强度排序（主要矛盾在最前，保留严重程度区分度）
    systems.sort(key=lambda x: -x["raw"])

    # 3) 主要矛盾 / 主要方面 / 次要方面
    principal = systems[0] if systems else None
    primary = None
    secondary = []
    if principal:
        ranked = sorted(principal["items"], key=lambda x: -abs(x[1]))
        primary = ranked[0]
        secondary = ranked[1:3]

    # 4) 六维统一综合建议 + 各新增章节
    six = _build_six_dim(systems, q, principal)
    diet_detail = _build_diet_detail(systems)
    medical = _build_medical(systems)
    medication = _build_medication(systems)
    trend = _build_trend(systems)
    edu = _build_edu(systems)
    top3 = _build_top3(principal)
    health_index = _health_index(systems, profile)
    retest = _retest_cycle(principal)
    assets = _asset_liability(systems)
    goal_note = _goal_focus(q, principal)
    bio_age = _bio_age({**profile, "age": q.get("age")}, health_index)
    okr = _build_okr(q.get("goal", ""), top3, health_index)
    tipping = _tipping_points(systems)
    invert = _invert_list(six, diet_detail)
    links = _build_links(systems)

    # 5) 概览文案
    n_sys = len(systems)
    n_abn_sys = sum(1 for s in systems if s["risk"] != "正常")
    overview = (f"共分析 {n_sys} 个身体系统，其中 {n_abn_sys} 个系统存在功能偏差。"
                f"下文先逐系统局部解读，再用矛盾论框架做综合研判，并给出统一综合干预方案。")

    return {
        "systems": systems,
        "principal": principal,
        "primary": primary,
        "secondary": secondary,
        "six": six,
        "diet_detail": diet_detail,
        "medical": medical,
        "medication": medication,
        "trend": trend,
        "edu": edu,
        "top3": top3,
        "health_index": health_index,
        "retest": retest,
        "assets": assets,
        "goal": q.get("goal", ""),
        "goal_note": goal_note,
        "bio_age": bio_age,
        "okr": okr,
        "tipping": tipping,
        "invert": invert,
        "links": links,
        "overview": overview,
        "profile": profile,
        "q": q,
    }


def _build_six_dim(systems, q, principal):
    """六维统一综合建议：主要矛盾系统优先，去重合成，最多 3 条/维，防信息过载。"""
    dims = ["饮食", "运动", "睡眠", "用药", "情绪管理", "生活方式"]
    raw = {d: [] for d in dims}
    for s in systems:
        if s["risk"] == "正常":
            continue
        adv = DIM_ADVICE.get(s["system"], {})
        is_p = (s is principal)
        for d in dims:
            if adv.get(d):
                raw[d].append((is_p, adv[d]))

    out = {}
    for d in dims:
        seen, items = set(), []
        for is_p, line in raw[d]:
            if line not in seen:
                seen.add(line)
                items.append((is_p, line))
        items.sort(key=lambda x: (0 if x[0] else 1))  # principal 在前
        lines = []
        marks = ["① 最优先（针对你的主要矛盾）", "② 优先", "③ 协同改善"]
        for i, (is_p, line) in enumerate(items[:3]):
            lines.append(f"{marks[i]}：{line}")
        if not lines:
            lines = [f"① {GENERAL.get(d, '')}"]
        out[d] = lines

    # 问卷个性化强调（统一措辞，追加为 ⚠️ 提示，避免与 ① 冲突）
    if q.get("exercise_freq") in ("几乎不运动", "1–2 次"):
        out["运动"].append("⚠️ 你的运动频率偏低，从每天快走 20 分钟起步，逐步增至 5 次/周。")
    if q.get("diet") in ("偏油腻", "偏甜/零食多", "不规律"):
        out["饮食"].append("⚠️ 你的饮食偏油腻/不规律，优先控油控糖、规律三餐，是性价比最高的改善点。")
    if q.get("sleep_quality") in ("一般", "差（易醒/难入睡）") or q.get("sleep_hours") in ("<6h",):
        out["睡眠"].append("⚠️ 你的睡眠时长/质量不足，先固定作息，比补运动更急迫。")
    if q.get("stress") == "高":
        out["情绪管理"].append("⚠️ 高压力会放大神经/内分泌偏差，每日 10 分钟正念或散步减压。")
    if q.get("smoke") in ("偶尔", "经常"):
        out["生活方式"].append("⚠️ 吸烟显著加重心血管与呼吸系统风险，建议尽快戒烟。")
    if q.get("sit") == ">8h":
        out["生活方式"].append("⚠️ 你久坐>8h，每小时起身 2 分钟，缓解骨骼与循环偏差。")
    if q.get("alcohol") in ("偶尔", "经常"):
        out["生活方式"].append("⚠️ 饮酒加重肝/心血管负担，建议限酒或戒酒。")
    return out


def _build_diet_detail(systems):
    """饮食明细：从主要矛盾系统 + 至多 2 个次系统，合并推荐食物/茶饮/禁忌/习惯。"""
    top = systems[:3]
    foods, teas, taboos, habits = [], [], [], []
    seen = set()
    for s in top:
        d = SYSTEM_DIET.get(s["system"])
        if not d:
            continue
        for it in d.get("推荐食物", []):
            if it not in seen:
                seen.add(it); foods.append(it)
        for it in d.get("推荐茶饮", []):
            if it not in seen:
                seen.add(it); teas.append(it)
        for it in d.get("禁忌", []):
            if it not in seen:
                seen.add(it); taboos.append(it)
        for it in d.get("用餐习惯", []):
            if it not in seen:
                seen.add(it); habits.append(it)
    return {"食物": foods[:6], "茶饮": teas[:4], "禁忌": taboos[:5], "习惯": habits[:4]}


def _build_medical(systems):
    out = []
    for s in systems:
        if s["risk"] == "正常":
            continue
        m = SYSTEM_MEDICAL.get(s["system"])
        if m:
            out.append((s["system"], m["科室"], m["检查"]))
    return out


def _build_medication(systems):
    out = []
    for s in systems:
        if s["risk"] == "正常":
            continue
        txt = SYSTEM_MEDICATION.get(s["system"])
        if txt:
            out.append((s["system"], txt))
    return out


def _build_trend(systems):
    out = []
    for s in systems:
        if s["risk"] == "正常":
            continue
        txt = SYSTEM_TREND.get(s["system"])
        if txt:
            out.append((s["system"], txt))
    return out


def _build_edu(systems):
    out = []
    for s in systems:
        if s["risk"] == "正常":
            continue
        txt = SYSTEM_EDU.get(s["system"])
        if txt:
            out.append((s["system"], txt))
    return out


def _build_top3(principal):
    """跨维度 Top3 行动优先级：直接告诉用户最该做哪 3 件事。"""
    if not principal:
        return []
    adv = DIM_ADVICE.get(principal["system"], {})
    picks = []
    for dim in ("运动", "饮食", "睡眠"):
        if adv.get(dim):
            picks.append((dim, adv[dim]))
    if len(picks) < 3 and adv.get("生活方式"):
        picks.append(("生活方式", adv["生活方式"]))
    return picks[:3]


def _health_index(systems, profile):
    """综合健康指数 0-100：异常区域占比(55%) + 最大功能偏离(45%) 折算损耗。
    作为整份报告的『北极星指标』，让用户一眼决策（对标生物年龄/InnerAge）。"""
    if not systems:
        return {"score": 100, "grade": "优秀", "color": "#2ecc71",
                "desc": "暂无系统数据，无法评估。"}
    total = sum(s["n_total"] for s in systems)
    abn = sum(s["n_abn"] for s in systems)
    abn_ratio = (abn / total) if total else 0
    worst = max((s["maxabs"] for s in systems), default=0)
    loss = abn_ratio * 55 + min(worst, 100) / 100 * 45
    score = max(0, min(100, round(100 - loss)))
    if score >= 85:
        grade, color, desc = "健康", "#2ecc71", "各系统功能协调，保持良好习惯就是最好的健康投资。"
    elif score >= 70:
        grade, color, desc = "良好", "#3498db", "整体尚可，少数系统有苗头，趁早干预收益最大。"
    elif score >= 55:
        grade, color, desc = "亚健康", "#f1c40f", "已有系统亮黄灯，现在干预还来得及，别等变红灯。"
    else:
        grade, color, desc = "警戒", "#e74c3c", "多个系统功能偏差明显，建议尽快就医并携带本报告。"
    return {"score": score, "grade": grade, "color": color, "desc": desc}


def _retest_cycle(principal):
    """基于主要矛盾风险给出复测周期（对应趋势追踪 / 健康储蓄账户）。"""
    if not principal:
        return "当前无明显矛盾，保持年度体检节奏即可。"
    r = principal["risk"]
    if r == "高风险":
        return "主要矛盾为高风险，建议 **1–3 个月内**复查 HRA，并尽快到对应科室就诊，对比干预效果。"
    if r == "中风险":
        return "主要矛盾为中风险，建议 **3–6 个月内**复查 HRA，与本次基线对比看趋势。"
    if r == "低风险":
        return "主要矛盾为低风险，建议 **6–12 个月内**随年度体检复查即可。"
    return "保持年度体检节奏。"


def _asset_liability(systems):
    """健康资产 / 负债视图（清崎资产思维）：正常系统=资产(保护)，异常=负债(偿还)。"""
    assets = [s["system"] for s in systems if s["risk"] == "正常"]
    liabilities = [(s["system"], s["risk"]) for s in systems if s["risk"] != "正常"]
    return {"assets": assets, "liabilities": liabilities}


def _goal_focus(q, principal):
    """目标导向连线（纳瓦尔 / InsideTracker goal-based）。"""
    goal = q.get("goal")
    if not goal:
        return ""
    if principal and (goal in principal["system"] or goal[:2] in principal["system"]):
        return (f"你的首要目标「{goal}」与当前主要矛盾系统高度一致——"
                f"集中火力攻坚它，目标达成最快。")
    return (f"你的首要目标「{goal}」已纳入建议考量；"
            f"当前最紧迫是先稳住主要矛盾系统，再向目标推进。")


def _bio_age(profile, hi):
    """生理年龄估算（库兹韦尔：量化自我 / 生物学年龄）。
    综合健康指数越低，生理年龄越『老』；反之可能比实际年轻——把指数翻译成人人都懂的『岁数』。"""
    raw = profile.get("年龄") or profile.get("age")
    if not raw:
        return None
    nums = re.findall(r"\d+", str(raw))
    if not nums:
        return None
    age = sum(int(x) for x in nums) / len(nums)
    offset = round((85 - hi["score"]) / 5.0)  # 每 5 分 ≈ 1 岁
    bio = int(round(age + offset))
    tag = "年轻" if offset < 0 else ("老" if offset > 0 else "相当")
    return {"age": int(round(age)), "bio": bio, "offset": offset, "tag": tag}


def _build_okr(goal, top3, hi):
    """健康 OKR（格鲁夫：量化目标管理）。O=首要目标，KR=可量化关键结果。"""
    o = goal or "提升整体健康水位"
    target = min(100, hi["score"] + 14)  # 3 个月指数目标：+14 分（可达且具挑战）
    krs = [f"3 个月后综合健康指数由 {hi['score']} 提升至 ≥ {target}"]
    if top3:
        krs.append(f"本周起落实 Top3 行动（{top3[0][0]} 优先）并养成习惯")
    krs.append("建立每日『成功日记』，连续打卡 ≥ 21 天")
    return {"o": o, "krs": krs}


def _tipping_points(systems):
    """战略临界点 / 治未病窗口（格鲁夫·战略转折点 + 老子·治未病）。
    找出『接近高风险阈值但尚未突破』的系统——这是质变前最后的低成本干预窗口。"""
    out = []
    for s in systems:
        if s["risk"] in ("中风险", "低风险") and s["maxabs"] >= 35:
            out.append((s["system"], s["maxabs"], s["risk"]))
    out.sort(key=lambda x: -x[1])
    return out


def _invert_list(six, diet_detail):
    """逆向清单（查理·芒格：避免愚蠢 > 追求聪明）。
    汇总『别做这些事』——把禁忌与反向提示集中成一张防错清单。"""
    items = []
    for it in diet_detail.get("禁忌", []):
        items.append(f"🚫 饮食：{it}")
    for d, lines in six.items():
        for ln in lines:
            if "⚠️" in ln:
                items.append(f"⚠️ {d}：{ln.replace('⚠️', '').strip()}")
    items.append("🚫 别因『现在没感觉』就忽视功能偏差——慢性风险常无症状")
    items.append("🚫 别自行购药 / 随意加减量 / 停药（用药必须遵医嘱）")
    items.append("🚫 别用『明天再开始』拖延——健康复利靠今天的微小行动")
    seen, uniq = set(), []
    for it in items:
        if it not in seen:
            seen.add(it)
            uniq.append(it)
    return uniq[:10]


def _build_links(systems):
    """系统联动提示（查理·芒格：多元思维 / lollapalooza）。
    当一条连锁链上 ≥2 个系统同时异常，提示它们彼此牵动，需整体而非孤立处理。"""
    bad = {s["system"] for s in systems if s["risk"] != "正常"}
    out = []
    for chain, txt in SYSTEM_LINKS:
        members = [m.strip() for m in chain.replace("↔", " ").split() if m.strip()]
        hit = [m for m in members if any(m in s for s in bad)]
        if len(hit) >= 2:
            out.append((chain, txt))
    return out


def to_markdown(res):
    """把分析结果渲染为 Markdown 报告（供下载/展示）。"""
    L = []
    L.append("# 悦检 · HRA 健康风险评估综合解读报告\n")
    p = res["profile"]
    if p:
        meta = " ｜ ".join(f"{k}：{v}" for k, v in p.items())
        L.append(f"> 会员信息：{meta}\n")
    L.append(f"## 一、总体概览\n{res['overview']}\n")

    # 逐系统（紧凑局部解读）
    L.append("## 二、逐系统局部解读\n")
    for s in res["systems"]:
        icon = s["meta"].get("icon", "")
        L.append(f"### {icon} {s['system']} —— 风险等级：**{s['risk']}**"
                 f"（异常区域 {s['n_abn']}/{s['n_total']}，最大偏离 {s['maxabs']}）\n")
        L.append(f"- 当前状态：{s['findings']}\n")
        if s["abn"]:
            top = "、".join(f"{r}（{v}）" for r, v in s["items"][:3])
            L.append(f"- 主要偏差区域：{top}\n")
        else:
            L.append("- 该系统的区域基本处于正常区间。\n")

    # 综合研判（矛盾论）
    L.append("## 三、综合研判：主要矛盾与主要方面\n")
    pr = res["principal"]
    if pr:
        L.append(f"- **主要矛盾**：**{pr['system']}**（风险等级 {pr['risk']}，"
                 f"最大偏离 {pr['maxabs']}，是各系统中功能偏差最突出的系统）——应作为干预重心。\n")
        if res["primary"]:
            r, v = res["primary"]
            L.append(f"- **主要方面**：该系统内最关键的区域是 **{r}**（检测值 {v}，"
                     f"{_status(v)}）——这是矛盾的主要方面，优先干预。\n")
        if res["secondary"]:
            sec = "、".join(f"{r}（{v}）" for r, v in res["secondary"])
            L.append(f"- **次要方面**：同系统内的 {sec} 等为次要方面，随主要方面一并改善。\n")
        others = [s for s in res["systems"] if s is not pr and s["risk"] != "正常"][:2]
        if others:
            ot = "、".join(f"{s['system']}（{s['risk']}）" for s in others)
            L.append(f"- **次要矛盾**：{ot} 等为次要矛盾，建议作为第二阶段管理重点。\n")

    # 行动优先级 Top3
    L.append("## 四、🎯 行动优先级 Top 3（先做好这三件）\n")
    if res["top3"]:
        for i, (dim, line) in enumerate(res["top3"], 1):
            L.append(f"{i}. **[{dim}]** {line}\n")
        L.append("\n> 以上三项针对你的主要矛盾系统，性价比最高，建议本周就开始执行。\n")
    else:
        L.append("- 暂无突出矛盾，保持现有良好生活习惯即可。\n")

    # 六维综合干预建议（统一）
    L.append("## 五、六维综合干预建议（统一方案）\n")
    dim_icon = {"饮食": "🥗", "运动": "🏃", "睡眠": "🌙", "用药": "💊",
                "情绪管理": "🧘", "生活方式": "💡"}
    for d in ["饮食", "运动", "睡眠", "用药", "情绪管理", "生活方式"]:
        L.append(f"### {dim_icon.get(d, '')} {d}\n")
        for line in res["six"][d]:
            L.append(f"- {line}")
        # 饮食维度补充明细
        if d == "饮食":
            dd = res["diet_detail"]
            if dd.get("食物"):
                L.append("\n  **🍽️ 推荐食物（及作用）**：")
                for it in dd["食物"]:
                    L.append(f"  - {it}")
            if dd.get("茶饮"):
                L.append("\n  **🍵 推荐茶饮**：")
                for it in dd["茶饮"]:
                    L.append(f"  - {it}")
            if dd.get("禁忌"):
                L.append("\n  **🚫 饮食禁忌**：")
                for it in dd["禁忌"]:
                    L.append(f"  - {it}")
            if dd.get("习惯"):
                L.append("\n  **⏰ 用餐习惯**：")
                for it in dd["习惯"]:
                    L.append(f"  - {it}")
        L.append("")

    # 就医建议
    L.append("## 六、🏥 就医建议（必要时及时就诊）\n")
    if res["medical"]:
        L.append("| 系统 | 建议科室 | 推荐检查项目 |")
        L.append("|------|----------|--------------|")
        for sysname, dept, exam in res["medical"]:
            L.append(f"| {sysname} | {dept} | {exam} |")
        L.append("")
    else:
        L.append("- 当前无系统显著异常，常规年度体检即可。\n")

    # 用药建议
    L.append("## 七、💊 用药建议（务必遵医嘱）\n")
    L.append("> ⚠️ **重要提醒**：以下仅为科普参考。**任何药物都必须在执业医师明确诊断后、"
             "遵医嘱使用；不可自行购药、不可随意加量/减量/停药，以免病情反弹或出现戒断、耐药等风险。**\n")
    if res["medication"]:
        for sysname, txt in res["medication"]:
            L.append(f"- **{sysname}**：{txt}")
    else:
        L.append("- 当前无明确用药指征，请勿自行服药。\n")

    # 趋势预警
    L.append("\n## 八、⚠️ 身体状态趋势预警（若不干预）\n")
    if res["trend"]:
        for sysname, txt in res["trend"]:
            L.append(f"- **{sysname}**：{txt}")
    else:
        L.append("- 当前风险尚低，保持即可。\n")

    # 健康宣教
    L.append("\n## 九、📖 健康宣教科普\n")
    if res["edu"]:
        for sysname, txt in res["edu"]:
            L.append(f"- **{sysname}**：{txt}")
    else:
        L.append("- 保持良好生活方式是最好的预防。\n")

    L.append("\n## 十、免责声明\n"
             "⚠️ 本报告由 AI 辅助生成，仅作健康科普与自我管理参考，不构成诊断或治疗建议。"
             "异常指标、用药与就医决策请务必咨询执业医师。\n")
    return "\n".join(L)


if __name__ == "__main__":
    from extract import extract_all
    sample = ("|姓名|示例|性别:|女|身高(cm)|165|体重(Kg)|60|\n"
              "|气管附近|气管附近|-66|支气管区域|支气管区域|-66|右肺下叶区域|右肺下叶区域|-50|\n"
              "|胃区域|胃区域|-55|十二指肠区域|十二指肠区域|-51|肝右页|肝右页|-65|胆囊区域|胆囊区域|-59|\n"
              "|左颈动脉|左颈动脉|-53|右颈动脉|右颈动脉|-47|冠状血管|冠状血管|54|心脏区域|心脏区域|-56|\n"
              "|甲状腺区域|甲状腺区域|-47|左杏仁体|左杏仁体|30|C5|-45|Th2|-67|Co1|50|")
    p, r = extract_all(sample)
    res = analyze(r, p, {"exercise_freq": "几乎不运动", "sleep_quality": "差（易醒/难入睡）",
                         "diet": "偏油腻", "stress": "高", "smoke": "偶尔", "sit": ">8h"})
    print(to_markdown(res))
