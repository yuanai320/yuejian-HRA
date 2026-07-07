# -*- coding: utf-8 -*-
"""
悦检 · 核心引擎
================
输入：用户填写的指标值（dict: key->数值）+ 个人档案（性别/年龄）
输出：一份结构化的 Markdown 解读报告（总体概览 + 逐项解读 + 综合干预 + 免责声明）

设计原则（对应岗位 JD）：
- 风险分级：每个指标自动落入「正常/临界/异常」档
- 个性化干预组装：按严重程度从知识库抽取运动/营养/生活/就医建议
- 可复用：解读逻辑全在 knowledge_base.py，改数据不改代码
"""

from datetime import date
from knowledge_base import INDICATORS, DISCLAIMER, PROJECT_NAME, VERSION

# 建立 key->指标 的快速索引
_BY_KEY = {ind["key"]: ind for ind in INDICATORS}


def _find_level(ind, value, profile=None):
    """返回 value 落入的档位；尿酸按性别覆盖阈值。"""
    if ind["key"] == "ua" and profile and profile.get("gender") in ind.get("gender_threshold", {}):
        thr = ind["gender_threshold"][profile["gender"]]
        # 尿酸：<thr 正常；thr~thr+60 高尿酸；>=thr+60 明显升高
        if value < thr:
            for lv in ind["levels"]:
                if lv["level"].startswith("正常"):
                    return lv
        elif value < thr + 60:
            for lv in ind["levels"]:
                if lv["level"] == "高尿酸血症":
                    return lv
        else:
            for lv in ind["levels"]:
                if lv["level"].startswith("明显升高"):
                    return lv
    for lv in ind["levels"]:
        lo = lv.get("min", float("-inf"))
        hi = lv.get("max", float("inf"))
        if lo <= value < hi:
            return lv
    return ind["levels"][-1]


def _severity_rank(level_name):
    """给档位打分，用于排序与总体判断。"""
    s = level_name
    if "正常" in s and "高值" not in s and "偏高" not in s and "偏低" not in s:
        return 0
    if "高值" in s or "受损" in s or "临界" in s or "边缘" in s or "偏高" in s or "偏低" in s:
        return 1
    if "升高" in s or "高" in s and "尿酸" in s or "异常" in s or "高血压" in s or "糖尿病" in s or "肥胖" in s:
        return 2
    if "明显" in s or "疑似" in s or "血症" in s:
        return 2
    return 1


def generate_report(inputs, profile=None):
    """生成 Markdown 报告。inputs: {key: value}；profile: {'gender':,'age':}"""
    profile = profile or {}
    rows = []
    abnormal = []
    for key, val in inputs.items():
        ind = _BY_KEY.get(key)
        if not ind:
            continue
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        lv = _find_level(ind, v, profile)
        rank = _severity_rank(lv["level"])
        rows.append({
            "label": ind["label"], "unit": ind["unit"], "group": ind["group"],
            "value": v, "level": lv["level"], "note": lv["note"],
            "actions": lv["actions"], "why": ind.get("why", ""), "rank": rank,
        })
        if rank >= 1:
            abnormal.append(rows[-1])

    # ---- 总体概览 ----
    total = len(rows)
    n_abn = len(abnormal)
    lines = []
    lines.append(f"# {PROJECT_NAME} · 我的解读报告")
    lines.append(f"> 生成日期：{date.today().isoformat()} ｜ 版本 {VERSION}")
    if profile.get("gender") or profile.get("age"):
        meta = []
        if profile.get("gender"):
            meta.append(f"性别：{profile['gender']}")
        if profile.get("age"):
            meta.append(f"年龄：{profile['age']}")
        lines.append(f"> 个人档案：{' ｜ '.join(meta)}")
    lines.append("")
    if total == 0:
        lines.append("未在上方填写任何指标数值，请返回填写后重新生成。")
        lines.append("")
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    if n_abn == 0:
        overview = f"✅ 本次评估 **{total}** 项指标均处于正常范围，继续保持健康习惯即可。"
    else:
        top = sorted(abnormal, key=lambda r: -r["rank"])[:3]
        top_txt = "、".join([f"**{r['label']}（{r['level']}）**" for r in top])
        overview = (f"本次评估 **{total}** 项，其中 **{n_abn}** 项需关注：{top_txt}。"
                    f"下面给出逐项解读与个性化干预建议。")
    lines.append("## 一、总体概览")
    lines.append(overview)
    lines.append("")

    # ---- 逐项解读 ----
    lines.append("## 二、逐项解读与干预建议")
    lines.append("")
    # 按系统分组输出
    groups = {}
    for r in rows:
        groups.setdefault(r["group"], []).append(r)
    for g, items in groups.items():
        lines.append(f"### ▍{g}")
        for r in items:
            lines.append(f"**{r['label']}**：{r['value']} {r['unit']} —— "
                         f"分级 **{r['level']}**")
            lines.append(f"- 含义：{r['note']}")
            a = r["actions"]
            if a.get("运动"):
                lines.append(f"- 🏃 运动：{'；'.join(a['运动'])}")
            if a.get("营养"):
                lines.append(f"- 🥗 营养：{'；'.join(a['营养'])}")
            if a.get("生活"):
                lines.append(f"- 💡 生活：{'；'.join(a['生活'])}")
            if a.get("就医"):
                lines.append(f"- 🏥 就医：{'；'.join(a['就医'])}")
            lines.append("")
        lines.append("")

    # ---- 综合干预（去重汇总高频建议）----
    lines.append("## 三、综合干预方案（高频行动）")
    lines.append("- 运动：以每周≥150分钟中等强度有氧为底座，异常项叠加针对性训练")
    lines.append("- 营养：控盐(<5g/天)、控糖（限精制碳水与果糖饮料）、增蔬果全谷与优质蛋白")
    lines.append("- 生活：睡眠7小时+、减重（若有超重）、戒烟限酒、多饮水、管理情绪与压力")
    lines.append("- 监测：异常指标按建议周期复查，建立自己的健康数据日记")
    lines.append("")
    lines.append("> 💡 你为什么能信任这份解读？每项分层逻辑都来自公开临床指南，"
                 "并由健康服务与管理专业学生（持社会体育指导员证、备考公共营养师）"
                 "在腾讯混元 Hy3 辅助下构建与校验——AI 生产内容，人把关准确性。")
    lines.append("")
    lines.append("## 四、免责声明")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


if __name__ == "__main__":
    # 自检：用一组示例数据跑一遍
    demo = {"sbp": 138, "dbp": 88, "glu": 6.3, "ldl": 3.8,
            "hdl": 1.2, "tg": 2.1, "bmi": 26.5, "ua": 460,
            "alt": 55, "hcy": 13}
    print(generate_report(demo, profile={"gender": "男", "age": 22}))
