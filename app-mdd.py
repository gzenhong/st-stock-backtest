import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os

# 1. 網頁頁面配置
st.set_page_config(page_title="績效、最大回測及跌幅對照表", layout="wide")
st.title("📊 績效、最大回測及跌幅對照表")

# 2. 側邊欄設定
with st.sidebar:
    # 使用 form 包裝，解決需要按兩次按鈕的問題
    with st.form("settings_form"):
        st.header("1. 設定投資參數")
        start_date = st.date_input("理想開始日期", value=datetime(2026, 1, 1), min_value=datetime(1900, 1, 1), max_value=datetime.today())
        end_date = st.date_input("理想結束日期", value=datetime.today(), min_value=datetime(1900, 1, 1), max_value=datetime.today())
        initial_capital = 10000 

        st.divider()
        st.header("2. 輸入股票代號")
        st.caption("支援: .TW, .GI (Goodinfo), .TR (報酬指數)｜最多 25 支，輸入完按 Enter 可新增列")
        input_df = pd.DataFrame([
            {"代號": "2330.TW"},
            {"代號": "0050.TW"},
            {"代號": "0056.TW"},
            {"代號": "00646.TW"},
            {"代號": "00647L.TW"},
            {"代號": "00662.TW"},
            {"代號": "00670L.TW"},
            {"代號": "00679B.TWO"},
            {"代號": "00757.TW"},
            {"代號": "00864B.TWO"},
            {"代號": "00878.TW"},
            {"代號": "00919.TW"},
            {"代號": "00981A.TW"},
            {"代號": "00631L.TW"},
            {"代號": "009811.TW"},
            {"代號": "009813.TW"},
            {"代號": "009815.TWO"},
            {"代號": "009816.TW"},
            {"代號": ""},
            {"代號": ""},
            {"代號": ""},
            {"代號": ""},
        ])
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

        analyze_btn = st.form_submit_button("🚀 開始執行比較分析")

    symbols = [
        str(s["代號"]).strip().upper() 
        for s in edited_df.to_dict('records') 
        if s["代號"] is not None and str(s["代號"]).strip() != ""
    ]

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
        file_name = f"{prefix}_goodinfo.csv"
        if not os.path.exists(file_name):
            st.error(f"找不到本地檔案：{file_name} (請確認檔案是否上傳至正確位置)")
            return None
        try:
            df = pd.read_csv(file_name)
            df['Date'] = pd.to_datetime(df['Date'])
            df.set_index('Date', inplace=True)
            def clean(col): return df[col].astype(str).str.replace(',', '').astype(float)
            target_col = 'Adj Close' if 'Adj Close' in df.columns else 'Close'
            close = clean(target_col).sort_index().ffill()
            high  = clean('High').sort_index().ffill()
            low   = clean('Low').sort_index().ffill()
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

        close = data_close["Close"].dropna().copy()
        high  = data_hl["High"].dropna().copy()
        low   = data_hl["Low"].dropna().copy()

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
            invest_high = raw_high_dict[sym][raw_high_dict[sym].index >= actual_start]
            invest_low  = raw_low_dict[sym][raw_low_dict[sym].index   >= actual_start]
            rolling_max  = invest_high.cummax()
            drawdowns    = (invest_low - rolling_max.reindex(invest_low.index).ffill()) / rolling_max.reindex(invest_low.index).ffill()
            max_drawdown = drawdowns.min()
            mdd_end_date   = drawdowns.idxmin()
            mdd_start_date = invest_high[:mdd_end_date].idxmax()
            mdd_period = f"{mdd_start_date.strftime('%Y-%m-%d')} ~ {mdd_end_date.strftime('%Y-%m-%d')}"

            # 區間最高價 / 最低價（最低價必須在最高價日期之後）
            period_high_val  = float(invest_high.max())
            period_high_date = invest_high.idxmax()
            low_after_high   = invest_low[invest_low.index > period_high_date]
            if low_after_high.empty:
                low_after_high = invest_low[invest_low.index >= period_high_date]
            period_low_val   = float(low_after_high.min())
            period_low_date  = low_after_high.idxmin()

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

            total_roi = (current_assets - initial_capital) / initial_capital
            summary_data.append({
                "股票代號": sym,
                "實際起始日": actual_start.strftime('%Y-%m-%d'),
                "實際結束日": actual_end.strftime('%Y-%m-%d'),
                "最終資產": f"${current_assets:,.0f}",
                "報酬率": f"{total_roi * 100:.2f}%",
                "最大回撤(MDD)": f"{max_drawdown * 100:.2f}%",
                "區間最高價": f"{period_high_val:,.2f}",
                "最高價日期": period_high_date.strftime('%Y-%m-%d'),
                "區間最低價": f"{period_low_val:,.2f}",
                "最低價日期": period_low_date.strftime('%Y-%m-%d'),
            })

            # 以區間最高價為基準，計算各跌幅對應價格
            dd_high_val = period_high_val
            dd_row = {
                "股票": sym,
                "High": f"{dd_high_val:,.2f}",
                "date": period_high_date.strftime('%Y-%m-%d'),
            }
            for pct in range(-10, -85, -5):
                dd_row[f"{pct}%"] = f"{dd_high_val * (1 + pct / 100):,.2f}"
            drawdown_table_data.append(dd_row)

        st.subheader("📋 績效與最大回測")
        st.write("💡 **MDD 發生期間**：高點取當日**最高價 (High)**，低點取當日**最低價 (Low)**，標示從「最高價日期」跌至「最低價日期」的區間。各股以自身實際資料範圍計算。")
        summary_df = pd.DataFrame(summary_data).set_index("股票代號")
        st.dataframe(summary_df, use_container_width=True, height=400)
        st.download_button(
            label="⬇️ 下載績效總結 CSV",
            data=summary_df.to_csv(encoding="utf-8-sig"),
            file_name="績效與最大回測.csv",
            mime="text/csv",
        )

        st.divider()
        st.subheader("📉 從區間最高價起算的跌幅對照表 (Buy the Dip)")
        st.write("💡 以各股**區間最高價 (High)** 為基準，試算跌幅 -10% ~ -80% 時的對應價格。")
        dd_df = pd.DataFrame(drawdown_table_data).set_index("股票")
        st.dataframe(dd_df, use_container_width=True)
        st.download_button(
            label="⬇️ 下載跌幅對照表 CSV",
            data=dd_df.to_csv(encoding="utf-8-sig"),
            file_name="跌幅對照表.csv",
            mime="text/csv",
        )
    else:
        st.error("查無有效數據，請確認上方是否有顯示檔案找不到或資料缺少的紅色警告。")