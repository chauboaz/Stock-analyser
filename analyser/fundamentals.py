"""Pick and format the useful fundamentals out of Yahoo's info dict."""

METRIC_GROUPS = {
    "Valuation": [
        ("Market cap", "marketCap", "money"),
        ("Trailing P/E", "trailingPE", "num"),
        ("Forward P/E", "forwardPE", "num"),
        ("PEG ratio", "trailingPegRatio", "num"),
        ("Price / Book", "priceToBook", "num"),
        ("Price / Sales", "priceToSalesTrailing12Months", "num"),
        ("EV / EBITDA", "enterpriseToEbitda", "num"),
    ],
    "Profitability": [
        ("Profit margin", "profitMargins", "pct"),
        ("Operating margin", "operatingMargins", "pct"),
        ("Return on equity", "returnOnEquity", "pct"),
        ("Return on assets", "returnOnAssets", "pct"),
    ],
    "Growth": [
        ("Revenue growth (YoY)", "revenueGrowth", "pct"),
        ("Earnings growth (YoY)", "earningsGrowth", "pct"),
        ("Trailing EPS", "trailingEps", "num"),
        ("Forward EPS", "forwardEps", "num"),
    ],
    "Financial health": [
        ("Total cash", "totalCash", "money"),
        ("Total debt", "totalDebt", "money"),
        ("Debt / Equity", "debtToEquity", "num"),
        ("Current ratio", "currentRatio", "num"),
        ("Free cash flow", "freeCashflow", "money"),
    ],
    "Dividends & risk": [
        ("Dividend yield", "dividendYield", "divpct"),
        ("Payout ratio", "payoutRatio", "pct"),
        ("Beta", "beta", "num"),
        ("52-week high", "fiftyTwoWeekHigh", "num"),
        ("52-week low", "fiftyTwoWeekLow", "num"),
    ],
    "Analysts": [
        ("Recommendation", "recommendationKey", "text"),
        ("Target price (mean)", "targetMeanPrice", "num"),
        ("Number of analysts", "numberOfAnalystOpinions", "int"),
    ],
}


def fmt(value, kind: str) -> str:
    if value is None or value == "" or (isinstance(value, float) and value != value):
        return "—"
    try:
        if kind == "money":
            for div, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
                if abs(value) >= div:
                    return f"{value / div:,.2f}{unit}"
            return f"{value:,.0f}"
        if kind == "pct":
            return f"{value * 100:.1f}%"
        if kind == "divpct":   # Yahoo now reports dividendYield already in percent
            return f"{value:.2f}%"
        if kind == "int":
            return f"{int(value)}"
        if kind == "num":
            return f"{value:,.2f}"
    except (TypeError, ValueError):
        pass
    return str(value).replace("_", " ").title()


def grouped(info: dict) -> dict[str, list[tuple[str, str]]]:
    return {g: [(label, fmt(info.get(key), kind)) for label, key, kind in items]
            for g, items in METRIC_GROUPS.items()}
