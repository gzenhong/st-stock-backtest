import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# 1. 網頁頁面配置
st.set_page_config(page_title="多股績效與回撤區間分析", layout="wide")
st.title("⚖️ 多支股票投資對比 (含 MDD 與 波動度分析)")

# 2. 側邊欄設定
with st.sidebar:
    st.header("1. 設定投資參數")
    start_date = st.date_input("理想開始日期", value=datetime(2010, 1, 1), min_value=datetime(1900, 1, 1), max_value=datetime.today())
    end_date = st.date_input("理想結束日期", value=datetime.today(), min_value=datetime(1900, 1, 1), max_value=datetime.today())
    initial_capital = 10000 

    st.divider()
    st.header("2. 輸入股票代號")
    input_df = pd.DataFrame([
        {"代號": "0050.TW"}, {"代號": "0052.TW"}, {"代號": "QQQ"}, 
        {"代號": ""}, {"代號": ""}, {"代號": ""}, 
        {"代號": ""}, {"代號": ""}, {"代號": ""}
    ])
    edited_df = st.data_editor(input_df, num_rows="fixed", hide_index=True)

    symbols = [
        str(s["代號"]).strip().upper() 
        for s in edited_df.to_dict('records') 
        if s["代號"] is not None and str(s["代號"]).strip() != ""
    ]

    analyze_btn = st.button("🚀 開始執行比較分析")

# 3. 核心處理函數 (保持原始修正邏輯)
def get_adjusted_data(symbol, start, end):
    buffer_start = start - timedelta(days=400)
    data = yf.download(symbol, start=buffer_start, end=end, auto_adjust=False, progress=False)
    if data.empty: return None

    if isinstance(data.columns, pd.MultiIndex):
        series = data["Adj Close"][symbol] if "Adj Close" in data.columns.get_level_values(0) else data["Close"][symbol]
    else:
        series = data["Adj Close"] if "Adj Close" in data.columns else data["Close"]

    series = series.dropna().copy()
    
    # 原始修正邏輯
    if symbol == "0050.TW":
        series.loc[series.index < pd.Timestamp("2014-01-02")] /= 4
    elif symbol == "0052.TW":
        series.loc[series.index < pd.Timestamp("2025-11-17")] /= 7
    return series

# 4. 主要執行邏輯
if analyze_btn and symbols:
    try:
        raw_series_dict = {}
        stock_start_info = {}

        with st.spinner('正在抓取數據並計算指標...'):
            for sym in symbols:
                res = get_adjusted_data(sym, start_date, end_date)
                if res is not None:
                    actual_start_in_range = res[res.index >= pd.Timestamp(start_date)].index
                    if not actual_start_in_range.empty:
                        raw_series_dict[sym] = res
                        stock_start_info[sym] = actual_start_in_range[0]

        if raw_series_dict:
            latest_start_date = max(stock_start_info.values())
            reference_stock = [s for s, d in stock_start_info.items() if d == latest_start_date][0]
            common_end_date = min([s.index[-1] for s in raw_series_dict.values()])

            st.success(f"📌 **同步計算基準：** 已取最短共同區間進行對比。")
            st.info(f"📅 **實際回測期間：** `{latest_start_date.strftime('%Y-%m-%d')}` 至 `{common_end_date.strftime('%Y-%m-%d')}` (基準：`{reference_stock}`)")

            all_assets_df = pd.DataFrame()
            all_roi_df = pd.DataFrame()
            summary_data = []

            for sym, series in raw_series_dict.items():
                invest_series = series[series.index >= latest_start_date]

                # --- 計算最大回撤 (MDD) ---
                rolling_max = invest_series.cummax()
                drawdowns = (invest_series - rolling_max) / rolling_max
                max_drawdown = drawdowns.min()

                mdd_end_date = drawdowns.idxmin()
                mdd_start_date = invest_series[:mdd_end_date].idxmax()
                mdd_period = f"{mdd_start_date.strftime('%Y-%m-%d')} ~ {mdd_end_date.strftime('%Y-%m-%d')}"

                # --- 計算年化波動度 ---
                daily_returns = invest_series.pct_change().dropna()
                annual_volatility = daily_returns.std() * np.sqrt(252)

                # --- 年度報酬與資產計算 ---
                years = sorted(list(set(invest_series.index.year)))
                current_assets = initial_capital
                s_price = float(invest_series.iloc[0])
                temp_assets, temp_rois = {}, {}

                for year in years:
                    year_end_price = float(series[series.index.year == year].iloc[-1])
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

                # 計算總體指標
                total_roi = (current_assets - initial_capital) / initial_capital
                days = (invest_series.index[-1] - invest_series.index[0]).days
                cagr = (current_assets / initial_capital) ** (365.25 / days) - 1 if days > 0 else 0

                # --- 調整字典順序：總報酬率移到年化報酬率之前 ---
                summary_data.append({
                    "股票代號": sym,
                    "最終資產": round(current_assets, 0),
                    "總報酬率 %": round(total_roi * 100, 2),
                    "年化(CAGR) %": round(cagr * 100, 2),
                    "年化波動度 %": round(annual_volatility * 100, 2),
                    "最大回撤(MDD) %": round(max_drawdown * 100, 2),
                    "MDD 發生期間 (高點 → 低點)": mdd_period
                })

            # 整理與排序表格 (預設依總報酬率排序)
            summary_df = pd.DataFrame(summary_data)
            summary_df = summary_df.sort_values(by="總報酬率 %", ascending=False)

            st.subheader(f"📊 多股累積資產成長圖 (起始資產 ${initial_capital:,.0f})")
            st.line_chart(all_assets_df)

            st.subheader("📋 績效與風險總結 (對齊區間)")
            st.info("💡 提示：點擊下方表格標題即可依照該項指標重新排序。")
            
            st.dataframe(
                summary_df.set_index("股票代號"), 
                use_container_width=True,
                column_config={
                    "最終資產": st.column_config.NumberColumn(format="$%d"),
                    "總報酬率 %": st.column_config.NumberColumn(format="%.2f%%"),
                    "年化(CAGR) %": st.column_config.NumberColumn(format="%.2f%%"),
                    "年化波動度 %": st.column_config.NumberColumn(format="%.2f%%"),
                    "最大回撤(MDD) %": st.column_config.NumberColumn(format="%.2f%%"),
                }
            )

            st.divider()
            st.subheader("📅 年度報酬率明細 (%)")
            st.dataframe(all_roi_df.T, use_container_width=True)
        else:
            st.error("查無數據。")

    except Exception as e:
        st.error(f"發生錯誤: {e}")