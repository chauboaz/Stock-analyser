"""Stock lists the signal scanner can search."""
import yfinance as yf
from yfinance import EquityQuery

from .data import ttl_cache

UNIVERSES = {
    "Watchlist": ["VOO", "NVDA", "COIN", "HIMS", "TSLA", "SMR", "MSFT"],
    "MAG7": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"],
    # Dow Jones Industrial Average members (since the Nov 2024 change: NVDA & SHW in, INTC & DOW out)
    "Dow 30": ["AAPL", "AMGN", "AMZN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS", "GS", "HD", "HON", "IBM",
               "JNJ", "JPM", "KO", "MCD", "MMM", "MRK", "MSFT", "NKE", "NVDA", "PG", "SHW", "TRV", "UNH", "V",
               "VZ", "WMT"],
    "US large caps": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "BRK-B", "JPM", "V", "MA",
                      "UNH", "XOM", "JNJ", "WMT", "PG", "HD", "COST", "ABBV", "LLY", "MRK", "KO", "PEP", "ORCL",
                      "CRM", "ADBE", "AMD", "NFLX", "INTC", "CSCO", "QCOM", "TXN", "BAC", "WFC", "GS", "DIS",
                      "MCD", "NKE", "BA", "CAT", "GE", "PLTR", "UBER", "SHOP", "PYPL", "MU", "ARM", "SNOW", "CVX"],
    "US growth & popular": ["COIN", "HIMS", "SMR", "PLTR", "SOFI", "RKLB", "IONQ", "OKLO", "HOOD", "MSTR",
                            "NET", "CRWD", "DDOG", "RBLX", "U", "AFRM", "UPST", "DKNG", "ROKU", "SQ"],
    "ETFs": ["VOO", "SPY", "QQQ", "VTI", "VT", "SCHD", "SMH", "ARKK", "IWM", "VNQ", "GLD", "TLT", "VAS.AX", "XOVR"],
    "NZX": ["FPH.NZ", "AIR.NZ", "SPK.NZ", "MEL.NZ", "CEN.NZ", "IFT.NZ", "AIA.NZ", "FBU.NZ", "MFT.NZ", "EBO.NZ",
            "CNU.NZ", "ATM.NZ", "GMT.NZ", "SUM.NZ", "RYM.NZ"],
    "ASX": ["BHP.AX", "CBA.AX", "CSL.AX", "NAB.AX", "WBC.AX", "ANZ.AX", "WES.AX", "MQG.AX", "FMG.AX", "WOW.AX",
            "TLS.AX", "RIO.AX", "WDS.AX", "XRO.AX", "PLS.AX"],
    "Crypto": ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "BNB-USD", "ADA-USD", "DOGE-USD", "AVAX-USD"],
}

# Home page market tiles: (label, Yahoo symbol)
MARKETS = [("S&P 500", "^GSPC"), ("Nasdaq", "^IXIC"), ("NZX 50", "^NZ50"), ("ASX 200", "^AXJO"),
           ("Bitcoin", "BTC-USD"), ("Ethereum", "ETH-USD"), ("Gold (USD/oz)", "GC=F"), ("NZD / USD", "NZDUSD=X")]

# Lists the Signals page scans by default ("My holdings" = securities in your portfolio)
RUSSELL = "Russell 2000 (top 100)"
DEFAULT_SCAN = ("My holdings", "Watchlist", "MAG7", "US large caps", "Dow 30", RUSSELL)


def tickers_for(groups, holdings: list[str]) -> list[str]:
    """Unique tickers for the chosen list names, in order."""
    out = []
    for g in groups:
        if g == "My holdings":
            out += holdings
        elif g == RUSSELL:
            out += russell_2000()
        else:
            out += UNIVERSES.get(g, [])
    return list(dict.fromkeys(out))


@ttl_cache(24 * 3600)
def russell_2000(n: int = 100) -> list[str]:
    """The n largest US-listed small caps ($300M-$5B, liquid) from Yahoo's screener - a close stand-in
    for the biggest Russell 2000 members (the official list isn't freely downloadable). It can include
    a few US-listed foreign companies that the real index excludes. [] if the screener is unavailable."""
    q = EquityQuery("and", [EquityQuery("eq", ["region", "us"]),
                            EquityQuery("is-in", ["exchange", "NMS", "NYQ", "NGM", "NCM", "ASE"]),
                            EquityQuery("btwn", ["intradaymarketcap", 300e6, 5e9]),
                            EquityQuery("gt", ["avgdailyvol3m", 300_000])])
    try:
        quotes = yf.screen(q, sortField="intradaymarketcap", sortAsc=False, size=n).get("quotes", [])
    except Exception:
        return []
    return [x["symbol"] for x in quotes if x.get("quoteType") == "EQUITY"]
