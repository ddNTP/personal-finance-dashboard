#!/usr/bin/env python3
"""解析微信、支付宝和招商银行流水，生成不包含原始明细的聚合分析 JSON。"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

try:
    import pdfplumber
except ImportError:  # pragma: no cover - only used when bank PDF is present
    pdfplumber = None

DIRECTION_MAP = {"收入": "income", "支出": "expense", "/": "neutral", "不计收支": "neutral"}
WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
REFUND_RE = re.compile(r"[¥￥]\s*([0-9][0-9,]*(?:\.[0-9]+)?)")
DATE_LINE_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})\s+CNY\s+(?P<amount>[+-]?[0-9][0-9,]*\.[0-9]{2})\s+(?P<balance>[+-]?[0-9][0-9,]*\.[0-9]{2})(?:\s+(?P<tail>.*))?$"
)
CMB_TYPES = (
    "数字人民币兑出",
    "数字人民币兑入",
    "银联快捷支付",
    "快捷退款",
    "快捷支付",
    "银联代付",
    "代发工资",
    "账户结息",
    "网联收款",
    "现金存入",
    "现金支取",
    "批量代付",
    "跨行转账",
    "转账",
)
ALIPAY_CATEGORY_MAP = {
    "餐饮美食": "餐饮",
    "交通出行": "交通",
    "医疗健康": "医疗健康",
    "住房物业": "住房生活",
    "生活服务": "住房生活",
    "充值缴费": "通讯数码",
    "数码电器": "通讯数码",
    "文化休闲": "娱乐内容",
    "酒店旅游": "娱乐内容",
    "教育培训": "教育服务",
    "服饰装扮": "购物",
    "日用百货": "购物",
    "家居家装": "购物",
    "美容美发": "生活服务",
    "母婴亲子": "购物",
    "运动户外": "购物",
    "商业服务": "其他消费",
    "转账红包": "转账/红包",
    "账户存取": "资金调拨",
    "投资理财": "投资理财",
    "信用借还": "信用借还",
    "退款": "退款",
}
CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("餐饮", ("餐", "饭店", "餐厅", "火锅", "烧烤", "奶茶", "咖啡", "饮品", "小吃", "美团", "饿了么", "肯德基", "麦当劳", "瑞幸", "星巴克", "朴朴")),
    ("交通", ("滴滴", "顺风车", "打车", "出租", "地铁", "公交", "火车", "铁路", "高铁", "机票", "机场", "加油", "高速", "出行")),
    ("医疗健康", ("医院", "医疗", "药", "药房", "诊所", "挂号", "体检", "牙科", "健康", "心理")),
    ("住房生活", ("物业", "水费", "电费", "燃气", "宽带", "话费", "房租", "家政", "维修", "生活缴费")),
    ("教育服务", ("学校", "大学", "教育", "课程", "培训", "考试", "学费", "咨询")),
    ("娱乐内容", ("电影", "影院", "游戏", "直播", "视频", "音乐", "会员", "书店", "旅游", "酒店", "景区", "娱乐")),
    ("通讯数码", ("手机", "电脑", "数码", "相机", "耳机", "电子", "充值")),
    ("购物", ("京东", "淘宝", "天猫", "拼多多", "唯品会", "商城", "商户", "旗舰店", "服饰", "女装", "男装", "童装", "内衣", "鞋", "家居", "百货", "优选", "小店", "商品", "购物")),
]


def _clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip().replace("\t", "")


def _round2(value: Any) -> float:
    return round(float(value or 0) + 1e-9, 2)


def _find_excel_header(raw: pd.DataFrame) -> int:
    for index, row in raw.iterrows():
        values = {_clean_text(value) for value in row.tolist()}
        if {"交易时间", "收/支", "金额(元)"}.issubset(values):
            return int(index)
    raise ValueError("未找到包含交易时间、收/支和金额(元)的微信账单表头")


def _parse_refund_amount(status: str, amount: float, direction: str, is_refund: bool) -> float:
    if not is_refund:
        return 0.0
    if direction == "income":
        return amount
    if "全额退款" in status or "对方已退还" in status:
        return amount
    matches = [float(item.replace(",", "")) for item in REFUND_RE.findall(status)]
    return min(amount, max(matches)) if matches else amount


def _payment_channel(value: str) -> str:
    text = _clean_text(value)
    if text in {"", "/", "nan", "None"}:
        return "未标注"
    if text in {"零钱", "零钱通", "余额宝", "花呗", "借呗"}:
        return text
    if "储蓄卡" in text or "信用卡" in text or "银行卡" in text or "银行" in text:
        return "银行卡"
    return "其他"


def _is_transfer_like(transaction_type: str) -> bool:
    return bool(re.search(r"转账|红包|提现|充值账户|零钱通|信用卡还款|资金调拨", _clean_text(transaction_type)))


def _is_non_consumption_text(text: str) -> bool:
    return bool(re.search(r"基金|余额宝|理财|投资|证券|信用借还|还款|零钱充值|账户存取|数字人民币兑|资金调拨", text))


def _category_for_expense(text: str, transaction_type: str, source: str) -> str:
    raw_type = _clean_text(transaction_type)
    if source == "alipay" and raw_type in ALIPAY_CATEGORY_MAP:
        return ALIPAY_CATEGORY_MAP[raw_type]
    if _is_transfer_like(raw_type):
        return "转账/红包"
    for category, keywords in CATEGORY_RULES:
        if any(keyword in text for keyword in keywords):
            return category
    return "其他消费"


def _income_source(transaction_type: str, is_refund: bool) -> str:
    if is_refund:
        return "退款"
    text = _clean_text(transaction_type)
    if "转账" in text or "代发" in text or "代付" in text:
        return "转账收入"
    if "二维码" in text or "收款" in text or "网联收款" in text:
        return "二维码收款"
    if "红包" in text:
        return "红包收入"
    if "工资" in text:
        return "工资"
    return "其他收入"


def _prepare_transactions(data: pd.DataFrame, source: str) -> tuple[pd.DataFrame, dict[str, int]]:
    if data.empty:
        return data.copy(), {"records_before_dedup": 0, "records_after_dedup": 0, "duplicate_records_removed": 0, "unparseable_dates": 0, "unparseable_amounts": 0, "unknown_directions": 0}
    data = data.copy()
    data["__source"] = source
    data["__date"] = pd.to_datetime(data["交易时间"], errors="coerce")
    data["__amount"] = pd.to_numeric(data["金额(元)"].map(_clean_text).str.replace(",", "", regex=False), errors="coerce").abs()
    data["__direction"] = data["收/支"].map(DIRECTION_MAP)
    quality = {
        "records_before_dedup": int(len(data)),
        "unparseable_dates": int(data["__date"].isna().sum()),
        "unparseable_amounts": int(data["__amount"].isna().sum()),
        "unknown_directions": int(data["__direction"].isna().sum()),
    }
    valid_id = data["交易单号"].map(_clean_text).isin({"", "/", "nan", "None"})
    duplicate_mask = (~valid_id) & data.duplicated(["__source", "__account_key", "交易单号"], keep="last")
    quality["duplicate_records_removed"] = int(duplicate_mask.sum())
    data = data.loc[~duplicate_mask].copy()
    data = data.loc[data["__date"].notna() & data["__amount"].notna() & data["__direction"].notna()].copy()
    data["__transaction_type"] = data["交易类型"].map(_clean_text)
    data["__status"] = data["当前状态"].map(_clean_text)
    data["__text"] = (
        data["交易类型"].map(_clean_text) + " " + data["交易对方"].map(_clean_text) + " " + data["商品"].map(_clean_text)
    ).str.lower()
    data["__is_refund"] = data["__transaction_type"].str.contains("退款", na=False) | data["__status"].str.contains("退款|退还", regex=True, na=False)
    data["__refund_amount"] = [_parse_refund_amount(status, float(amount), direction, bool(is_refund)) for status, amount, direction, is_refund in zip(data["__status"], data["__amount"], data["__direction"], data["__is_refund"])]
    data["__is_transfer_like"] = data["__transaction_type"].map(_is_transfer_like)
    data["__is_non_consumption_text"] = data["__text"].map(_is_non_consumption_text)
    data["__is_refund_flow"] = data["__is_refund"] & ((data["__direction"] == "income") | ((source == "alipay") & (data["__direction"] == "neutral")))
    data["__is_consumption"] = (data["__direction"] == "expense") & ~data["__is_transfer_like"] & ~data["__is_non_consumption_text"]
    data["__category"] = [
        _category_for_expense(text, transaction_type, source) if direction == "expense" else ("退款" if bool(is_refund) and direction == "income" else "转账/红包" if transfer_like else "中性交易")
        for text, transaction_type, direction, is_refund, transfer_like in zip(data["__text"], data["__transaction_type"], data["__direction"], data["__is_refund"], data["__is_transfer_like"])
    ]
    data["__income_source"] = [_income_source(transaction_type, bool(is_refund)) if direction == "income" else "" for transaction_type, is_refund, direction in zip(data["__transaction_type"], data["__is_refund"], data["__direction"])]
    data["__payment_channel"] = data["支付方式"].map(lambda value: _payment_channel(_clean_text(value)))
    data["__effective_consumption"] = 0.0
    consumption_mask = data["__is_consumption"]
    data.loc[consumption_mask, "__effective_consumption"] = (data.loc[consumption_mask, "__amount"] - data.loc[consumption_mask, "__refund_amount"]).clip(lower=0)
    neutral_refund_mask = (source == "alipay") & (data["__direction"] == "neutral") & data["__is_refund"]
    data.loc[neutral_refund_mask, "__effective_consumption"] = -data.loc[neutral_refund_mask, "__refund_amount"]
    data["__month"] = data["__date"].dt.to_period("M").astype(str)
    data["__year"] = data["__date"].dt.year.astype(int)
    data["__weekday"] = data["__date"].dt.weekday.astype(int)
    quality["records_after_dedup"] = int(len(data))
    return data, quality


def _read_wechat_one(path: Path, input_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    raw = pd.read_excel(path, header=None)
    header_row = _find_excel_header(raw)
    frame = pd.read_excel(path, header=header_row).dropna(how="all")
    frame.columns = [_clean_text(column) for column in frame.columns]
    required = {"交易时间", "交易类型", "交易对方", "商品", "收/支", "金额(元)", "支付方式", "当前状态", "交易单号"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{path.name} 缺少字段: {', '.join(missing)}")
    relative = path.relative_to(input_dir)
    frame = frame.copy()
    frame["__account_key"] = relative.parts[0] if len(relative.parts) > 1 else "未分组"
    frame["__source_file"] = relative.as_posix()
    return frame, {"source": "wechat", "account_key": frame["__account_key"].iloc[0], "path": relative.as_posix(), "records": int(len(frame))}


def _load_wechat_transactions(input_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    files = sorted(input_dir.rglob("*.xlsx"))
    frames: list[pd.DataFrame] = []
    file_info: list[dict[str, Any]] = []
    for path in files:
        frame, info = _read_wechat_one(path, input_dir)
        frames.append(frame)
        file_info.append(info)
    if not frames:
        return pd.DataFrame(), {"source_files": 0, "file_records": [], "records_before_dedup": 0, "records_after_dedup": 0, "duplicate_records_removed": 0, "unparseable_dates": 0, "unparseable_amounts": 0, "unknown_directions": 0}
    data, quality = _prepare_transactions(pd.concat(frames, ignore_index=True), "wechat")
    return data, {"source_files": len(files), "file_records": file_info, **quality}


def _read_alipay_one(path: Path, input_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    with path.open("r", encoding="gb18030", newline="") as handle:
        rows = list(csv.reader(handle))
    header_row = next((index for index, row in enumerate(rows) if {"交易时间", "收/支", "金额"}.issubset({_clean_text(value) for value in row})), None)
    if header_row is None:
        raise ValueError(f"{path.name} 未找到支付宝账单表头")
    header = [_clean_text(value) for value in rows[header_row]]
    records = []
    for row in rows[header_row + 1 :]:
        if not any(_clean_text(value) for value in row):
            continue
        padded = row + [""] * max(0, len(header) - len(row))
        records.append(dict(zip(header, padded)))
    frame = pd.DataFrame(records)
    rename = {"交易分类": "交易类型", "商品说明": "商品", "金额": "金额(元)", "收/付款方式": "支付方式", "交易状态": "当前状态", "交易订单号": "交易单号", "商家订单号": "商户单号"}
    frame = frame.rename(columns=rename)
    frame["收/支"] = frame["收/支"].map(lambda value: "/" if _clean_text(value) == "不计收支" else _clean_text(value))
    for column in ["交易时间", "交易类型", "交易对方", "商品", "收/支", "金额(元)", "支付方式", "当前状态", "交易单号", "商户单号", "备注"]:
        if column not in frame:
            frame[column] = ""
    relative = path.relative_to(input_dir)
    frame["__account_key"] = relative.parts[0] if len(relative.parts) > 1 else "未分组"
    frame["__source_file"] = relative.as_posix()
    return frame, {"source": "alipay", "account_key": frame["__account_key"].iloc[0] if len(frame) else "未分组", "path": relative.as_posix(), "records": int(len(frame))}


def _load_alipay_transactions(input_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    files = sorted(input_dir.rglob("*.csv"))
    frames: list[pd.DataFrame] = []
    file_info: list[dict[str, Any]] = []
    for path in files:
        frame, info = _read_alipay_one(path, input_dir)
        frames.append(frame)
        file_info.append(info)
    if not frames:
        return pd.DataFrame(), {"source_files": 0, "file_records": [], "records_before_dedup": 0, "records_after_dedup": 0, "duplicate_records_removed": 0, "unparseable_dates": 0, "unparseable_amounts": 0, "unknown_directions": 0}
    data, quality = _prepare_transactions(pd.concat(frames, ignore_index=True), "alipay")
    return data, {"source_files": len(files), "file_records": file_info, **quality}


def _extract_cmb_type(text: str) -> str:
    return next((transaction_type for transaction_type in CMB_TYPES if transaction_type in text), "银行交易")


def parse_cmb_text(text: str, source_file: str, page_number: int = 1) -> pd.DataFrame:
    lines = [line.strip() for line in text.splitlines()]
    starts = [index for index, line in enumerate(lines) if DATE_LINE_RE.match(line)]
    rows: list[dict[str, Any]] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        block = " ".join(line for line in lines[start:end] if line)
        match = DATE_LINE_RE.match(lines[start])
        if not match:
            continue
        amount = float(match.group("amount").replace(",", ""))
        transaction_type = _extract_cmb_type(block)
        date_text = match.group("date")
        rows.append({
            "交易时间": date_text,
            "交易类型": transaction_type,
            "交易对方": "银行流水",
            "商品": block,
            "收/支": "收入" if amount >= 0 else "支出",
            "金额(元)": abs(amount),
            "支付方式": "银行卡",
            "当前状态": transaction_type,
            "交易单号": f"{source_file}:{page_number}:{position}",
            "商户单号": "/",
            "备注": "",
        })
    return pd.DataFrame(rows)


def _load_cmb_transactions(input_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    files = sorted(input_dir.rglob("*.pdf"))
    if not files:
        return pd.DataFrame(), {"source_files": 0, "file_records": [], "records_before_dedup": 0, "records_after_dedup": 0, "duplicate_records_removed": 0, "unparseable_dates": 0, "unparseable_amounts": 0, "unknown_directions": 0, "pages": 0}
    if pdfplumber is None:
        raise RuntimeError("发现招商银行 PDF，但当前环境缺少 pdfplumber")
    frames: list[pd.DataFrame] = []
    file_info: list[dict[str, Any]] = []
    total_pages = 0
    for path in files:
        page_frames: list[pd.DataFrame] = []
        with pdfplumber.open(path) as pdf:
            total_pages += len(pdf.pages)
            for page_number, page in enumerate(pdf.pages, start=1):
                text = page.extract_text(layout=True) or page.extract_text() or ""
                parsed = parse_cmb_text(text, path.name, page_number)
                if not parsed.empty:
                    page_frames.append(parsed)
        if page_frames:
            frame = pd.concat(page_frames, ignore_index=True)
        else:
            frame = pd.DataFrame(columns=["交易时间", "交易类型", "交易对方", "商品", "收/支", "金额(元)", "支付方式", "当前状态", "交易单号", "商户单号", "备注"])
        frame["__account_key"] = path.relative_to(input_dir).parts[0] if len(path.relative_to(input_dir).parts) > 1 else "未分组"
        frame["__source_file"] = path.relative_to(input_dir).as_posix()
        frames.append(frame)
        file_info.append({"source": "cmb", "account_key": frame["__account_key"].iloc[0] if len(frame) else "未分组", "path": path.relative_to(input_dir).as_posix(), "records": int(len(frame))})
    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    data, quality = _prepare_transactions(raw, "cmb")
    return data, {"source_files": len(files), "file_records": file_info, "pages": total_pages, **quality}


def _load_transactions(input_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """兼容旧调用：仅读取微信账单。"""
    return _load_wechat_transactions(input_dir)


def _aggregate(frame: pd.DataFrame, group_col: str, amount_col: str = "__amount") -> list[dict[str, Any]]:
    if frame.empty:
        return []
    grouped = frame.groupby(group_col, dropna=False).agg(amount=(amount_col, "sum"), count=(amount_col, "size")).reset_index().rename(columns={group_col: "label"})
    total = float(grouped["amount"].sum())
    grouped["share"] = grouped["amount"].map(lambda value: float(value) / total if total else 0.0)
    grouped = grouped.sort_values(["amount", "label"], ascending=[False, True])
    return [{"label": _clean_text(row["label"]), "amount": _round2(row["amount"]), "count": int(row["count"]), "share": round(float(row["share"]), 6)} for _, row in grouped.iterrows()]


def _monthly(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    start, end = frame["__date"].min().to_period("M"), frame["__date"].max().to_period("M")
    rows: list[dict[str, Any]] = []
    for period in pd.period_range(start, end, freq="M"):
        part = frame.loc[frame["__month"] == str(period)]
        income = part.loc[part["__direction"] == "income", "__amount"].sum()
        expense = part.loc[part["__direction"] == "expense", "__amount"].sum()
        neutral = part.loc[part["__direction"] == "neutral", "__amount"].sum()
        refund = part.loc[part["__is_refund_flow"], "__refund_amount"].sum()
        consumption = part["__effective_consumption"].sum()
        rows.append({"month": str(period), "income": _round2(income), "income_ex_refunds": _round2(income - refund), "expense": _round2(expense), "neutral": _round2(neutral), "refunds": _round2(refund), "consumption": _round2(consumption), "consumption_count": int(part["__is_consumption"].sum()), "net_cashflow": _round2(income - expense)})
    return rows


def _yearly(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    max_date = frame["__date"].max()
    rows: list[dict[str, Any]] = []
    for year in sorted(frame["__year"].unique()):
        part = frame.loc[frame["__year"] == year]
        income = part.loc[part["__direction"] == "income", "__amount"].sum()
        expense = part.loc[part["__direction"] == "expense", "__amount"].sum()
        consumption = part["__effective_consumption"].sum()
        refund = part.loc[part["__is_refund_flow"], "__refund_amount"].sum()
        complete = not (int(year) == int(max_date.year) and (max_date.month, max_date.day) != (12, 31))
        rows.append({"year": int(year), "label": str(year) if complete else f"{year}（截至{max_date.month:02d}-{max_date.day:02d}）", "complete": complete, "income": _round2(income), "expense": _round2(expense), "consumption": _round2(consumption), "refunds": _round2(refund), "net_cashflow": _round2(income - expense), "consumption_count": int(part["__is_consumption"].sum())})
    return rows


def _money(value: Any) -> str:
    return f"¥{float(value):,.2f}"


def _insights(frame: pd.DataFrame, monthly: list[dict[str, Any]], categories: list[dict[str, Any]]) -> list[dict[str, str]]:
    if frame.empty:
        return []
    insights: list[dict[str, str]] = []
    consumption_total = float(frame["__effective_consumption"].sum())
    if monthly and consumption_total:
        peak = max(monthly, key=lambda row: row["consumption"])
        insights.append({"title": "消费峰值", "value": peak["month"], "detail": f"该月有效消费 {_money(peak['consumption'])}，占当前统计期有效消费的 {peak['consumption'] / consumption_total:.1%}。"})
    if categories:
        top = categories[0]
        insights.append({"title": "主要消费类别", "value": top["label"], "detail": f"累计 {_money(top['amount'])}，占有效消费 {top['share']:.1%}，共 {top['count']} 笔。"})
    weekday_amounts = frame.loc[frame["__is_consumption"]].groupby("__weekday")["__effective_consumption"].sum().reindex(range(7), fill_value=0)
    if float(weekday_amounts.sum()):
        weekday = int(weekday_amounts.idxmax())
        insights.append({"title": "高消费日", "value": WEEKDAY_LABELS[weekday], "detail": f"按星期汇总的有效消费最高，金额 {_money(weekday_amounts.loc[weekday])}。"})
    gross_income = float(frame.loc[frame["__direction"] == "income", "__amount"].sum())
    gross_expense = float(frame.loc[frame["__direction"] == "expense", "__amount"].sum())
    refund = float(frame.loc[frame["__is_refund_flow"], "__refund_amount"].sum())
    if gross_expense:
        insights.append({"title": "退款回流", "value": _money(refund), "detail": f"退款收入约占账单总支出的 {refund / gross_expense:.1%}；消费结构已按退款状态扣除有效金额。"})
    insights.append({"title": "方向性净额", "value": _money(gross_income - gross_expense), "detail": "收入减支出的方向性净额；跨支付平台和银行流水不会在合计视图中重复相加。"})
    return insights


def _build_view(frame: pd.DataFrame, view_id: str, label: str, file_count: int, source_label: str = "") -> dict[str, Any]:
    income = frame.loc[frame["__direction"] == "income", "__amount"]
    expense = frame.loc[frame["__direction"] == "expense", "__amount"]
    neutral = frame.loc[frame["__direction"] == "neutral", "__amount"]
    consumption = frame["__effective_consumption"]
    refund_flow = frame.loc[frame["__is_refund_flow"], "__refund_amount"]
    refund_income = frame.loc[(frame["__direction"] == "income") & frame["__is_refund"], "__amount"]
    categories = _aggregate(frame.loc[frame["__is_consumption"]], "__category", "__effective_consumption")
    income_sources = _aggregate(frame.loc[frame["__direction"] == "income"], "__income_source")
    payment_channels = _aggregate(frame.loc[frame["__is_consumption"]], "__payment_channel", "__effective_consumption")
    weekdays = _aggregate(frame.loc[frame["__is_consumption"]].assign(__weekday_label=lambda data: data["__weekday"].map(lambda value: WEEKDAY_LABELS[int(value)])), "__weekday_label", "__effective_consumption")
    weekday_order = {label: index for index, label in enumerate(WEEKDAY_LABELS)}
    weekdays.sort(key=lambda row: weekday_order.get(row["label"], 99))
    monthly, yearly = _monthly(frame), _yearly(frame)
    return {
        "id": view_id,
        "label": label,
        "source_label": source_label,
        "file_count": int(file_count),
        "date_start": frame["__date"].min().strftime("%Y-%m-%d") if not frame.empty else None,
        "date_end": frame["__date"].max().strftime("%Y-%m-%d") if not frame.empty else None,
        "metrics": {
            "records": int(len(frame)),
            "gross_income": _round2(income.sum()),
            "gross_expense": _round2(expense.sum()),
            "gross_neutral": _round2(neutral.sum()),
            "net_cashflow": _round2(income.sum() - expense.sum()),
            "consumption": _round2(consumption.sum()),
            "consumption_count": int(frame["__is_consumption"].sum()),
            "refunds": _round2(refund_flow.sum()),
            "income_ex_refunds": _round2(income.sum() - refund_income.sum()),
            "transfer_like_expense": _round2(frame.loc[(frame["__direction"] == "expense") & frame["__is_transfer_like"], "__amount"].sum()),
        },
        "monthly": monthly,
        "yearly": yearly,
        "categories": categories,
        "income_sources": income_sources,
        "payment_channels": payment_channels,
        "weekdays": weekdays,
        "insights": _insights(frame, monthly, categories),
    }


def _source_quality(quality: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in quality.items() if key != "file_records"}


def build_summary(input_dir: Path) -> dict[str, Any]:
    wechat, wechat_quality = _load_wechat_transactions(input_dir)
    alipay, alipay_quality = _load_alipay_transactions(input_dir)
    bank, bank_quality = _load_cmb_transactions(input_dir)
    platform_frames = [frame for frame in [wechat, alipay] if not frame.empty]
    platform = pd.concat(platform_frames, ignore_index=True) if platform_frames else pd.DataFrame()
    account_keys = sorted(platform["__account_key"].dropna().unique().tolist()) if not platform.empty else []
    account_ids = {key: f"account-{index + 1}" for index, key in enumerate(account_keys)}
    account_labels = {key: f"账户 {chr(ord('A') + index)}" for index, key in enumerate(account_keys)}
    file_records = wechat_quality["file_records"] + alipay_quality["file_records"]
    account_file_counts = pd.DataFrame(file_records).groupby("account_key").size().to_dict() if file_records else {}
    views: dict[str, dict[str, Any]] = {}
    views["combined"] = _build_view(platform, "combined", "支付平台合计", len(file_records), "微信支付 + 支付宝")
    for key in account_keys:
        views[account_ids[key]] = _build_view(platform.loc[platform["__account_key"] == key], account_ids[key], account_labels[key], int(account_file_counts.get(key, 0)), "微信支付 + 支付宝（按账户）")
    if not wechat.empty:
        views["wechat"] = _build_view(wechat, "wechat", "微信支付", wechat_quality["source_files"], "微信支付")
    if not alipay.empty:
        views["alipay"] = _build_view(alipay, "alipay", "支付宝", alipay_quality["source_files"], "支付宝")
    if not bank.empty:
        views["bank"] = _build_view(bank, "bank", "招商银行", bank_quality["source_files"], "招商银行流水（与支付平台分开）")
    max_date = platform["__date"].max() if not platform.empty else bank["__date"].max()
    min_date = platform["__date"].min() if not platform.empty else bank["__date"].min()
    view_options = [{"id": "combined", "label": "支付平台合计", "description": "微信支付 + 支付宝"}]
    view_options.extend({"id": account_ids[key], "label": account_labels[key], "description": "按账户合并支付平台"} for key in account_keys)
    view_options.extend(option for option in [{"id": "wechat", "label": "微信支付", "description": "仅微信账单"}, {"id": "alipay", "label": "支付宝", "description": "仅支付宝账单"}, {"id": "bank", "label": "招商银行", "description": "银行流水，独立展示"}] if option["id"] in views)
    return {
        "schema_version": 2,
        "generated_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        "meta": {
            "title": "个人收支分析仪表盘",
            "source": "微信支付、支付宝和招商银行流水（分层展示，仅发布聚合结果）",
            "date_start": min_date.strftime("%Y-%m-%d"),
            "date_end": max_date.strftime("%Y-%m-%d"),
            "partial_year": int(max_date.year),
            "account_count": len(account_keys),
            "source_file_count": int(wechat_quality["source_files"] + alipay_quality["source_files"] + bank_quality["source_files"]),
            "record_count": int(len(platform)),
            "platform_record_count": int(len(platform)),
            "bank_record_count": int(len(bank)),
            "bank_date_start": bank["__date"].min().strftime("%Y-%m-%d") if not bank.empty else None,
            "bank_date_end": bank["__date"].max().strftime("%Y-%m-%d") if not bank.empty else None,
            "privacy": "网页只发布按来源、月份、年度、类别和渠道聚合后的数据，不包含原始交易明细。",
            "anti_double_counting": "招商银行流水与微信/支付宝支付平台分开展示，不纳入支付平台合计，避免快捷支付重复记账。",
            "accounts": [{"id": account_ids[key], "label": account_labels[key], "file_count": int(account_file_counts.get(key, 0))} for key in account_keys],
            "view_options": view_options,
        },
        "quality": {"wechat": _source_quality(wechat_quality), "alipay": _source_quality(alipay_quality), "cmb": _source_quality(bank_quality)},
        "views": views,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path(__file__).resolve().parents[1], help="包含账单目录的输入目录，默认是仓库根目录")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "site" / "data" / "summary.json", help="聚合 JSON 输出路径")
    args = parser.parse_args()
    summary = build_summary(args.input_dir.expanduser().resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已生成 {args.output}：{summary['meta']['record_count']} 条支付平台记录，{summary['meta']['bank_record_count']} 条银行流水，覆盖 {summary['meta']['date_start']} 至 {summary['meta']['date_end']}")


if __name__ == "__main__":
    main()
