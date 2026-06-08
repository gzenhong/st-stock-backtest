import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import glob
import re
import json

# ── 預設股票清單（從檔案讀取，若無則用內建清單）────────────────
_DEFAULTS_FILE = os.path.join(os.path.dirname(__file__), "default_stocks.json")
_BUILTIN_DEFAULTS = {
    "stocks": [
        "2330.TW", "0050.TW", "0056.TW", "00646.TW", "00647L.TW",
        "00662.TW", "00670L.TW", "00679B.TWO", "00757.TW", "00864B.TWO",
        "00878.TW", "00919.TW", "00981A.TW", "00631L.TW", "009811.TW",
        "009813.TW", "009815.TWO", "009816.TW",
    ],
    "start_date": "2026-01-01",
}

def _load_defaults() -> dict:
    if os.path.exists(_DEFAULTS_FILE):
        with open(_DEFAULTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 相容舊格式（純 list）
        if isinstance(data, list):
            data = {"stocks": data, "start_date": _BUILTIN_DEFAULTS["start_date"]}
        return data
    return _BUILTIN_DEFAULTS

def _save_defaults(data: dict):
    with open(_DEFAULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# 1. 網頁頁面配置
st.set_page_config(page_title="績效、最大回測及跌幅對照表", layout="wide")
st.title("📊 績效、最大回測及跌幅對照表")

# 2. 側邊欄設定
with st.sidebar:
    # 使用 form 包裝，解決需要按兩次按鈕的問題
    with st.form("settings_form"):
        st.header("1. 設定投資參數")
        _saved = _load_defaults()
        _default_start = datetime.strptime(_saved["start_date"], "%Y-%m-%d")
        start_date = st.date_input("理想開始日期", value=_default_start, min_value=datetime(1900, 1, 1), max_value=datetime.today())
        end_date = st.date_input("理想結束日期", value=datetime.today(), min_value=datetime(1900, 1, 1), max_value=datetime.today())
        initial_capital = 10000

        st.divider()
        st.header("2. 輸入股票代號")
        st.caption("支援: .TW, .GI (Goodinfo), .TR (報酬指數)｜最多 25 支，輸入完按 Enter 可新增列")
        input_df = pd.DataFrame(
            [{"代號": s} for s in _saved["stocks"]] + [{"代號": ""}, {"代號": ""}]
        )
        edited_df = st.data_editor(
            input_df,
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
        )
        # 限制最多 25 支
        if len(edited_df) > 25:
            st.warning("⚠️ 最多支援 25 支股票，超出的部分將被忽略。")
            edited_df = edited_df.head(25)

        col_run, col_save = st.columns(2)
        analyze_btn = col_run.form_submit_button("🚀 開始執行比較分析", use_container_width=True)
        save_btn    = col_save.form_submit_button("💾 儲存為預設",       use_container_width=True)

    symbols = [
        str(s["代號"]).strip().upper()
        for s in edited_df.to_dict('records')
        if s["代號"] is not None and str(s["代號"]).strip() != ""
    ]

    if save_btn:
        if symbols:
            _save_defaults({
                "stocks": symbols,
                "start_date": start_date.strftime("%Y-%m-%d"),
            })
            st.sidebar.success(f"✅ 已儲存：開始日期 {start_date}，{len(symbols)} 支股票")
        else:
            st.sidebar.warning("⚠️ 股票清單為空，未儲存")

# 3. 核心處理函數
def get_adjusted_data(symbol, start, end):
    buffer_start = start - timedelta(days=400)
    # ✨ 修正：給 Yahoo Finance 加上結尾緩衝，確保不會因為時區問題少抓最後一天
    buffer_end = end + timedelta(days=5) 
    upper_symbol = symbol.upper()

    # --- 處理本地 .TR (報酬指數) ---
    if upper_symbol.endswith('.TR'):
        prefix = upper_symbol.replace('.TR', '')
        file_name = f"{prefix}_TR.csv"
        col_name = f"{prefix}TR"
        if not os.path.exists(file_name):
            st.error(f"找不到本地檔案：{file_name} (請確認大小寫)")
            return None
        try:
            df = pd.read_csv(file_name)
            df['Date'] = pd.to_datetime(df['Date'])
            df.set_index('Date', inplace=True)
            def clean(col): return df[col].astype(str).str.replace(',', '').astype(float)
            close = clean(col_name).sort_index().ffill()
            high  = clean('High').sort_index().ffill()
            low   = clean('Low').sort_index().ffill()
            for s in (close, high, low):
                s.index = s.index.tz_localize(None)
            return {"close": close, "high": high, "low": low}
        except Exception as e:
            st.error(f"讀取 {file_name} 失敗：{e}")
            return None

    # --- 處理本地 .GI (Goodinfo) ---
    elif upper_symbol.endswith('.GI'):
        prefix = upper_symbol.replace('.GI', '')
        matches = glob.glob(f"{prefix}_*_gi.csv")
        if not matches:
            st.error(f"找不到本地檔案：{prefix}_*_gi.csv (請確認檔案是否上傳至正確位置)")
            return None

        # 從檔名解析日期範圍，選資料最長（跨度最大）的檔案
        # 檔名格式：{prefix}_{startYYYYMMDD}-{endYYYYMMDD}_gi.csv
        def parse_date_span(fname):
            base = os.path.basename(fname)
            m = re.search(r'_(\d{8})-(\d{8})_gi\.csv$', base, re.IGNORECASE)
            if m:
                try:
                    d_start = datetime.strptime(m.group(1), "%Y%m%d")
                    d_end   = datetime.strptime(m.group(2), "%Y%m%d")
                    return (d_end - d_start).days
                except Exception:
                    pass
            return 0  # 無法解析時給最低優先

        file_name = max(matches, key=parse_date_span)

        try:
            df = pd.read_csv(file_name)
            df['Date'] = pd.to_datetime(df['Date'])
            df.set_index('Date', inplace=True)
            def clean(col): return df[col].astype(str).str.replace(',', '').astype(float)
            target_col = 'Adj Close' if 'Adj Close' in df.columns else 'Close'
            close = clean(target_col).sort_index().ffill()
            high  = clean('High').sort_index().ffill()
            low   = clean('Low').sort_index().ffill()

            # 0050 拆股補正（2025-06-10 拆股 1:4）
            # Adj Close 已做除權息還原，拆股前後連續，不需補正
            # High / Low 是原始成交價，拆股後變小，需乘以 4 還原成舊尺度（用於 MDD 計算）
            if prefix == '0050':
                split_date = pd.Timestamp("2025-06-10")
                for s in (high, low):
                    s.loc[s.index > split_date] *= 4

            for s in (close, high, low):
                s.index = s.index.tz_localize(None)
            return {"close": close, "high": high, "low": low}
        except Exception as e:
            st.error(f"讀取 {file_name} 失敗：{e}")
            return None

    # --- Yahoo Finance ---
    else:
        ticker = yf.Ticker(symbol)

        # close：用 buffer_start + auto_adjust=True，確保除息還原正確、且有前一年底收盤價
        # high/low：用 start（非 buffer）+ auto_adjust=False，取真實成交原始價格
        #           不用 buffer 是為了避免 yfinance 把舊資料回溯調整放大，蓋過近期真實高點
        data_close = ticker.history(start=buffer_start, end=buffer_end, auto_adjust=True,  actions=False)
        data_hl    = ticker.history(start=start,        end=buffer_end, auto_adjust=False, actions=False)

        if data_close.empty or data_hl.empty:
            st.warning(f"Yahoo Finance 查無 {symbol} 數據。")
            return None

        data_close.index = data_close.index.tz_localize(None)
        data_hl.index    = data_hl.index.tz_localize(None)

        close = data_close["Close"].dropna().sort_index()
        high  = data_hl["High"].dropna().sort_index()
        low   = data_hl["Low"].dropna().sort_index()

        if upper_symbol == "0050.TW":
            close.loc[close.index < pd.Timestamp("2014-01-02")] /= 4
            high.loc[high.index   < pd.Timestamp("2014-01-02")] /= 4
            low.loc[low.index     < pd.Timestamp("2014-01-02")] /= 4
        elif upper_symbol == "0052.TW":
            close.loc[close.index < pd.Timestamp("2025-11-17")] /= 7
            high.loc[high.index   < pd.Timestamp("2025-11-17")] /= 7
            low.loc[low.index     < pd.Timestamp("2025-11-17")] /= 7
        elif upper_symbol == "00631L.TW":
            # 2026/03/23 拆股 1:22，拆股前的所有價格除以 22
            split_date = pd.Timestamp("2026-03-23")
            close.loc[close.index < split_date] /= 22
            high.loc[high.index   < split_date] /= 22
            low.loc[low.index     < split_date] /= 22

        return {"close": close, "high": high, "low": low}

# 4. 主要執行邏輯
if analyze_btn and symbols:
    
    # --- 單支股票自動加入對比基準 (2330.GI 與 SPY 雙向綁定) ---
    if len(symbols) == 1:
        target_sym = symbols[0].upper()
        tw_suffixes = ('.TW', '.TWO', '.GI', '.TR')
        
        if any(target_sym.endswith(sfx) for sfx in tw_suffixes):
            if target_sym.startswith('2330.'):
                symbols.append('SPY')
                st.info(f"💡 偵測到單一輸入為 {target_sym}，已自動加入基準：**SPY**")
            else:
                symbols.append('2330.GI')
                st.info("💡 偵測到單一台股，已自動加入基準：**2330.GI**")
        else:
            if target_sym == 'SPY':
                symbols.append('2330.GI')
                st.info("💡 偵測到單一輸入為 SPY，已自動加入基準：**2330.GI**")
            else:
                symbols.append('SPY')
                st.info("💡 偵測到單一美股，已自動加入基準：**SPY**")

    raw_series_dict = {}
    raw_high_dict   = {}
    raw_low_dict    = {}
    stock_start_info = {}

    with st.spinner('正在計算績效與 MDD 區間...'):
        for sym in symbols:
            res = get_adjusted_data(sym, start_date, end_date)
            if res is not None:
                close_s = res["close"]
                high_s  = res["high"]
                low_s   = res["low"]

                # 強制在 end_date 畫下一刀，用 end_date+1 確保當天資料不被截掉
                cutoff = pd.Timestamp(end_date) + pd.Timedelta(days=1)
                close_s = close_s[close_s.index < cutoff]
                high_s  = high_s[high_s.index   < cutoff]
                low_s   = low_s[low_s.index     < cutoff]

                actual_start_in_range = close_s[close_s.index >= pd.Timestamp(start_date)].index
                if not actual_start_in_range.empty:
                    raw_series_dict[sym] = close_s
                    raw_high_dict[sym]   = high_s
                    raw_low_dict[sym]    = low_s
                    stock_start_info[sym] = actual_start_in_range[0]
                else:
                    st.warning(f"{sym} 在指定的日期區間內沒有有效數據。")

    if raw_series_dict:
        st.success(f"📌 **各股票以自身實際資料範圍計算，不強制對齊起訖日期。**")

        all_assets_df = pd.DataFrame()
        all_roi_df = pd.DataFrame()
        summary_data = []
        drawdown_table_data = []

        for sym, series in raw_series_dict.items():
            # 各股票以自己的實際起始日為準（使用者設定的 start_date 或該股最早有資料的日期）
            actual_start = stock_start_info[sym]
            invest_series = series[series.index >= actual_start]

            # 計算 MDD：高點用 High，低點用 Low
            invest_high = raw_high_dict[sym][raw_high_dict[sym].index >= actual_start].sort_index()
            invest_low  = raw_low_dict[sym][raw_low_dict[sym].index   >= actual_start].sort_index()
            rolling_max  = invest_high.cummax()
            drawdowns    = (invest_low - rolling_max.reindex(invest_low.index).ffill()) / rolling_max.reindex(invest_low.index).ffill()
            max_drawdown = drawdowns.min()
            mdd_end_date   = drawdowns.idxmin()
            # 用嚴格小於，確保高點日期一定在低點之前
            high_before_end = invest_high[invest_high.index <= mdd_end_date]
            mdd_start_date = high_before_end.idxmax() if not high_before_end.empty else mdd_end_date
            mdd_period = f"{mdd_start_date.strftime('%Y-%m-%d')} ~ {mdd_end_date.strftime('%Y-%m-%d')}"

            # MDD 對應的實際高點 / 低點價格
            mdd_high_price = float(invest_high.loc[mdd_start_date])
            mdd_low_price  = float(invest_low.loc[mdd_end_date])

            # 全區間最高價（用於 Buy the Dip 跌幅對照表）
            period_high_val  = float(invest_high.max())
            period_high_date = invest_high.idxmax()

            # 年度計算
            years = sorted(list(set(invest_series.index.year)))
            current_assets = initial_capital
            s_price = float(invest_series.iloc[0])
            temp_assets, temp_rois = {}, {}

            for year in years:
                year_data = series[series.index.year == year]
                year_end_price = float(year_data.iloc[-1])
                prev_year_data = series[series.index.year < year]

                if not prev_year_data.empty:
                    base_price = float(prev_year_data.iloc[-1])
                    if year == years[0] and invest_series.index[0] > prev_year_data.index[-1]:
                        base_price = s_price
                else:
                    base_price = s_price

                year_roi = (year_end_price - base_price) / base_price
                current_assets *= (1 + year_roi)
                temp_assets[year] = round(current_assets, 0)
                temp_rois[year] = f"{year_roi * 100:.2f}%"

            all_assets_df[sym] = pd.Series(temp_assets)
            all_roi_df[sym] = pd.Series(temp_rois)

            days = (invest_series.index[-1] - invest_series.index[0]).days
            cagr = (current_assets / initial_capital) ** (365.25 / days) - 1 if days > 0 else 0
            actual_end = max(invest_series.index[-1], invest_high.index[-1])

            # 目前股價（取最後一筆收盤價）與目前跌幅（從區間全域最高點起算）
            current_price = float(invest_series.iloc[-1])
            current_price_date = invest_series.index[-1]
            current_drawdown = (current_price - period_high_val) / period_high_val if period_high_val != 0 else 0

            total_roi = (current_assets - initial_capital) / initial_capital
            summary_data.append({
                "股票代號": sym,
                "實際起始日": actual_start.strftime('%Y-%m-%d'),
                "實際結束日": actual_end.strftime('%Y-%m-%d'),
                "最終資產": f"${current_assets:,.0f}",
                "報酬率": total_roi * 100,           # 數值，供排序
                "最大跌幅(MDD)": max_drawdown * 100,  # 數值，供排序
                "最高點日期": mdd_start_date.strftime('%Y-%m-%d'),
                "最高點價格": mdd_high_price,
                "最低點日期": mdd_end_date.strftime('%Y-%m-%d'),
                "最低點價格": mdd_low_price,
                "區間高點日期": period_high_date.strftime('%Y-%m-%d'),
                "區間高點價格": period_high_val,
                "目前股價": current_price,
                "目前跌幅": current_drawdown * 100,   # 數值，供排序
            })

            # 以區間最高價為基準，計算各跌幅對應價格
            dd_high_val = period_high_val
            dd_row = {
                "股票": sym,
                "最高價": dd_high_val,
                "最高價日期": period_high_date.strftime('%Y-%m-%d'),
                "目前股價": current_price,
                "目前股價日期": current_price_date.strftime('%Y-%m-%d'),
                "目前跌幅": current_drawdown * 100,
            }
            for pct in range(-10, -85, -5):
                dd_row[f"{pct}%"] = dd_high_val * (1 + pct / 100)
            drawdown_table_data.append(dd_row)

        st.subheader("📋 績效與最大回測")
        st.write("💡 **MDD**：高點取當日 **High**，低點取當日 **Low**。最高點/最低點日期與價格為 MDD 實際對應的高低點，目前跌幅以最高點為基準。")
        summary_df = (
            pd.DataFrame(summary_data)
            .sort_values("最大跌幅(MDD)")      # 數值升冪 → 最負在上
            .set_index("股票代號")
        )
        pct_fmt = st.column_config.NumberColumn(format="%.2f%%")
        price_fmt = st.column_config.NumberColumn(format="%.2f")
        st.dataframe(
            summary_df,
            use_container_width=True,
            height=400,
            column_config={
                "報酬率":      pct_fmt,
                "最大跌幅(MDD)": pct_fmt,
                "最高點價格":  price_fmt,
                "最低點價格":  price_fmt,
                "區間高點價格": price_fmt,
                "目前股價":    price_fmt,
                "目前跌幅":    pct_fmt,
            },
        )
        csv_df = summary_df.copy()
        for col in ["報酬率", "最大跌幅(MDD)", "目前跌幅"]:
            csv_df[col] = csv_df[col].map(lambda x: f"{x:.2f}%")
        for col in ["最高點價格", "最低點價格", "區間高點價格", "目前股價"]:
            csv_df[col] = csv_df[col].map(lambda x: f"{x:,.2f}")
        st.download_button(
            label="⬇️ 下載績效總結 CSV",
            data=csv_df.to_csv(encoding="utf-8-sig"),
            file_name="績效與最大回測.csv",
            mime="text/csv",
        )

        st.divider()
        st.subheader("📉 從區間最高價起算的跌幅對照表 (Buy the Dip)")
        st.write("💡 以各股**區間最高價 (High)** 為基準，試算跌幅 -10% ~ -80% 時的對應價格。")
        dd_df = (
            pd.DataFrame(drawdown_table_data)
            .sort_values("目前跌幅")   # 數值升冪 → 跌最多在上
            .set_index("股票")
        )
        dd_price_fmt = st.column_config.NumberColumn(format="%.2f")
        dd_pct_fmt   = st.column_config.NumberColumn(format="%.2f%%")
        dd_col_cfg   = {"最高價": dd_price_fmt, "目前股價": dd_price_fmt, "目前跌幅": dd_pct_fmt}
        dd_col_cfg  |= {f"{p}%": dd_price_fmt for p in range(-10, -85, -5)}
        st.dataframe(dd_df, use_container_width=True, column_config=dd_col_cfg)
        # CSV：把數值轉回易讀字串
        dd_csv = dd_df.copy()
        dd_csv["目前跌幅"] = dd_csv["目前跌幅"].map(lambda x: f"{x:.2f}%")
        for col in ["最高價", "目前股價"] + [f"{p}%" for p in range(-10, -85, -5)]:
            dd_csv[col] = dd_csv[col].map(lambda x: f"{x:,.2f}")
        st.download_button(
            label="⬇️ 下載跌幅對照表 CSV",
            data=dd_csv.to_csv(encoding="utf-8-sig"),
            file_name="跌幅對照表.csv",
            mime="text/csv",
        )
    else:
        st.error("查無有效數據，請確認上方是否有顯示檔案找不到或資料缺少的紅色警告。")