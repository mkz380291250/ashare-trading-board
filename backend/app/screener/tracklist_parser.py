"""把同花顺自选页粘贴的文本解析为 [(code, name)]。

策略:逐行扫描,用正则找出独立的 6 位数字作为 A 股代码(避免匹配 4075.10 这类带
小数的数字);名称取代码所在行的中文词,若该行没有中文,则回退到上一行的中文词
(同花顺常把名称放在代码上一行)。去重,保留首次出现顺序。
"""
import re

_CODE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_NAME = re.compile(r"[一-鿿]{2,8}")
# 页面噪声词,不是股票名
_STOP = {"同花顺", "同花顺App", "自选", "上证指数", "最新", "涨幅", "现手",
         "资金", "资讯", "资产", "分析", "全部", "沪深京", "港股", "美股",
         "期货", "基金", "首页", "行情", "交易", "理财"}


def normalize_code(code: str) -> str:
    """裸 6 位码 → 带交易所后缀的 tushare ts_code(与 DailyQuote.code 一致)。
    已带后缀的原样返回。沪市 60/68/90 → .SH;北交所 4x/8x/92 → .BJ;其余深市 → .SZ。"""
    if "." in code:
        return code
    if code.startswith(("60", "68", "90")):
        return code + ".SH"
    if code.startswith(("4", "8", "92")):
        return code + ".BJ"
    return code + ".SZ"


def _pick_name(text: str) -> str | None:
    for w in _NAME.findall(text):
        if w not in _STOP:
            return w
    return None


def parse_tracklist(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for i, line in enumerate(lines):
        for code in _CODE.findall(line):
            if code in seen:
                continue
            name = _pick_name(line)
            if name is None and i > 0:
                name = _pick_name(lines[i - 1])
            seen.add(code)
            out.append((code, name or ""))
    return out
