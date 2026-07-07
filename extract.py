# -*- coding: utf-8 -*-
"""
悦检 v2 · HRA 文本/表格提取器
===========================
把用户「复制粘贴」或「上传」的 HRA 报告，解析成：
  - profile: 会员信息（姓名/性别/身高cm/体重Kg/BMI）
  - regions: {区域名: 检测值(int)}  仅匹配知识库中已知区域，保证准确率

支持三种输入来源（已用真实惠斯安普 HRA 电子数据校验）：
  1) Excel / WPS 复制：制表符分隔(TSV)，首行为表头、次行为数据
     —— 例如从 Data.xls 选中某人的区域列复制，得到 "气管附近<TAB>4<TAB>支气管区域<TAB>4..."
  2) PDF / 网页复制：竖线分隔，常见 "区域名|区域名|检测值" 或 "区域名|检测值"
  3) 手写/混排： "区域名：检测值"、"区域名 检测值"

真实数据模型：每个身体区域一个检测值，正常值 -20~+20，越偏离0（尤其负值）风险越大。
注：绝不允许正则跨行，否则表头会错位到下一行数据（早期版本的真实 bug，已修复）。
"""

import re
from hra_knowledge import REGIONS, NORMAL_RANGE

# 表头列里可用于抽取会员信息的列名（含真实导出里的写法）
_PROFILE_COLS = {
    "姓名": "姓名",
    "性别": "性别",
    "身高 (cm)": "身高",
    "身高(cm)": "身高",
    "体重 (kg)": "体重",
    "体重(kg)": "体重",
}

# 区域名 → 系统 已在 hra_knowledge 中；这里只做解析。
# 长名优先，避免「甲状腺区域」误匹配「甲状腺右叶区域」内部，或「Th1」误吞「Th10」。
_REGION_NAMES = sorted(REGIONS.keys(), key=len, reverse=True)


def extract_profile(text):
    """从「竖线/冒号」格式文本解析会员信息。"""
    profile = {}
    m = re.search(r"性别[|：:\s]*(男|女)", text)
    if m:
        profile["性别"] = m.group(1)
    m = re.search(r"身高\s*[（(]?\s*cm\s*[）)]?\s*[|：:\s]*(\d{2,3})", text, re.I)
    if m:
        profile["身高"] = int(m.group(1))
    m = re.search(r"体重\s*[（(]?\s*Kg\s*[）)]?\s*[|：:\s]*(\d{2,3})", text, re.I)
    if m:
        profile["体重"] = int(m.group(1))
    m = re.search(r"姓名[|：:\s]*([\u4e00-\u9fa5A-Za-z0-9_]{1,8})", text)
    if m:
        profile["姓名"] = m.group(1)
    return profile


def extract_regions(text):
    """从单列/竖线/冒号格式文本解析各区域检测值，返回 {区域名: int}。"""
    regions = {}
    for name in _REGION_NAMES:
        # 关键修复：
        #  (1) (?![0-9]) 负向预查，避免「Th1」把「Th10」的「0」误当成自己的值；
        #  (2) 分隔符集合显式排除换行，杜绝跨行错位（这是早期版本只识别 1/120 的根因）；
        #  (3) 支持 "名|名|值" / "名|值" / "名：值" / "名 值" 四种常见写法。
        pat = (re.escape(name)
               + r"(?![0-9])"
               + r"(?:[|｜\t][^|\t\r\n-]{0,15})?"   # 可选的重复区域名（"名|名|值"）
               + r"[ \t：:＝=\|｜]+"                  # 至少一个分隔符（不含换行）
               + r"(-?\d{1,3})")
        m = re.search(pat, text)
        if m:
            regions[name] = int(m.group(1))
    return regions


def _split_rows(text):
    """把 TSV 文本拆成「逻辑行」。

    真实 Excel/WPS 复制时：单元格内的手动换行(Alt+Enter)会变成 \\n，
    从而把一行数据从中间切断。这里用「表头列数」作为标尺，把被切断的
    片段重新拼回完整行（按制表符数量对齐），彻底避免列错位。
    """
    raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    raw = [ln for ln in raw]  # 保留空行以便合并
    if not raw:
        return []
    header = [c.strip() for c in raw[0].split("\t")]
    header_str = "\t".join(header)
    ncol = len(header)
    rows, buf = [], []
    for ln in raw[1:]:
        buf.append(ln)
        merged = "\t".join(buf)
        if merged.count("\t") >= ncol - 1:   # 列数够了 = 一整行
            rows.append(merged)
            buf = []
    if buf:
        rows.append("\t".join(buf))
    return [header_str] + rows


def _extract_tsv(text):
    """按行解析 TSV（Excel/WPS 复制）：首行表头，后续每行数据，列对齐。"""
    table = _split_rows(text)
    if len(table) < 2:
        return extract_profile(text), extract_regions(text)

    header = [c.strip() for c in table[0].split("\t")]
    profile, regions = {}, {}
    for ri in range(1, len(table)):
        cells = [c.strip() for c in table[ri].split("\t")]
        if len(cells) < len(header):
            cells += [""] * (len(header) - len(cells))
        row = dict(zip(header, cells))
        # 区域检测值
        row_hit = 0
        for h, v in row.items():
            if h in REGIONS and v not in ("", None):
                if re.fullmatch(r"-?\d+", v):
                    regions[h] = int(v)
                    row_hit += 1
        if row_hit == 0:
            continue  # 空行或非数据行
        # 会员信息（取第一个有效数据行的表头列）
        if not profile:
            for col, key in _PROFILE_COLS.items():
                if col in row and row[col] not in ("", None):
                    val = row[col].strip()
                    if key in ("身高", "体重"):
                        mm = re.search(r"\d{2,3}", val)
                        if mm:
                            profile[key] = int(mm.group(0))
                    else:
                        profile[key] = val
            # 尝试从「人体成分分析及建议」解析 BMI
            for col, val in row.items():
                if "BMI" in col or "人体成分" in col:
                    mm = re.search(r"BMI[（(]?[^:：]*[:：]?\s*(\d{1,2}(?:\.\d+)?)", val)
                    if mm:
                        profile["BMI"] = float(mm.group(1))
                        break
        break  # 只取第一个有效数据行（最常见：单个人）
    if not regions:
        return extract_profile(text), extract_regions(text)
    return profile, regions


def _extract_lines(text):
    """PDF/Word 等文档提取文本后，区域名与值常分两行（"名\\n值" 或 "名：\\n值"）。
    扫描相邻行，把『已知区域名 + 下一行纯整数』配对，提升文档类导入的识别率。"""
    regions = {}
    lines = text.split("\n")
    for i, line in enumerate(lines):
        name = line.strip()
        if name in REGIONS:
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if re.fullmatch(r"-?\d{1,3}", nxt):
                regions[name] = int(nxt)
    return regions


def extract_all(text):
    """一站式：返回 (profile, regions)。自动判断 TSV / 竖线 / 混排 / 文档分行。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\t" in text and "\n" in text:
        return _extract_tsv(text)
    profile = extract_profile(text)
    regions = extract_regions(text)
    # 文档类补充：区域名与值分两行的情况
    for k, v in _extract_lines(text).items():
        regions.setdefault(k, v)
    return profile, regions


if __name__ == "__main__":
    # 真实格式自检：TSV（表头+数据）
    tsv = ("姓名\t性别\t身高 (cm)\t体重 (kg)\t气管附近\t支气管区域\t肝右页\t冠状动脉\tTh2\tCo1\n"
           "示例\t女\t165\t60\t-66\t-66\t-65\t54\t-67\t50\n")
    p, r = extract_all(tsv)
    print("TSV profile:", p)
    print("TSV regions count:", len(r), "->", {k: r[k] for k in list(r)[:6]})

    # 竖线格式自检
    pipe = ("|姓名|示例|性别:|女|身高(cm)|165|体重(Kg)|60|\n"
            "|气管附近|气管附近|-66|支气管区域|支气管区域|-66|肝右页|肝右页|-65|"
            "冠状动脉|冠状动脉|54|Th2|-67|Co1|50|")
    p2, r2 = extract_all(pipe)
    print("PIPE regions count:", len(r2), "->", {k: r2[k] for k in list(r2)[:6]})

    # Th1/Th10 误吞自检
    t = "Th1|12|Th10|-21|Th2|-67"
    rr = extract_regions(t)
    print("Th check -> Th1:", rr.get("Th1"), "Th10:", rr.get("Th10"), "Th2:", rr.get("Th2"))
