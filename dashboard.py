import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import pandas as pd

import advisor

st.set_page_config(page_title="Heating Oil Advisor", layout="wide", page_icon="🛢️")

st.title("🛢️ Heating Oil Tank Advisor")

with st.spinner("Fetching data and running ML models... (This takes a few seconds)"):
    data = advisor.get_advisor_data()

if 'error' in data:
    st.error(data['error'])
    st.stop()

st.header("Overview")
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("Current Tank Level", f"{data.get('current_tank_level', 0):.0f} L")
with col2:
    st.metric("Current Oil Price Global", f"{data.get('current_global_price', 0):.2f} €/100L")
with col3:
    st.metric("Current Oil Price Local", f"{data.get('current_local_price', 0):.2f} €/100L")
with col4:
    if data.get('status') == 'OK - Level High':
        st.metric("Optimal Buy Date", "No need to buy yet!")
    else:
        st.metric("Optimal Buy Date", f"{data.get('optimal_buy_date').strftime('%Y-%m-%d')}")
with col5:
    if data.get('status') == 'OK - Level High':
        st.metric("Expected Savings", "0.00 €")
    else:
        st.metric("Expected Savings", f"{data.get('expected_savings', 0):.2f} €/100L")

st.subheader("🤖 AI Advisor Summary")
st.info(data.get('llm_notification', 'No summary available.'))

st.divider()

st.subheader("Master Overview: Price vs Consumption")
st.write("This stacked view tracks the price forecast and your tank depletion on the same timeline, without crossing messy lines.")

fig_master = make_subplots(
    rows=2, cols=1, 
    shared_xaxes=True, 
    vertical_spacing=0.12,
    row_heights=[0.6, 0.4]
)

offset = data.get('regional_offset', 0)
eval_data = data.get('eval_data')
test_df_local = eval_data['test_df'].copy() if eval_data else None

last_hist_price_date = None
last_hist_price_val = None

if test_df_local is not None:
    past_prices = test_df_local['heating_oil_eur_per_100l'] + offset
    last_hist_price_date = test_df_local.index[-1]
    last_hist_price_val = past_prices.iloc[-1]
    
    fig_master.add_trace(
        go.Scatter(x=test_df_local.index, y=past_prices, 
                   mode='lines', name='Past Price (Est.)', line=dict(width=2, dash='dot')),
        row=1, col=1
    )
    
    if 'local_heating_oil_eur_per_100l' in test_df_local.columns:
        actual_local = test_df_local['local_heating_oil_eur_per_100l'].dropna()
        if not actual_local.empty:
            fig_master.add_trace(
                go.Scatter(x=actual_local.index, y=actual_local, mode='lines+markers', name='Past Price (Actual)', line=dict(width=2)),
                row=1, col=1
            )

local_forecast = data.get('local_champion_forecast')
if local_forecast is not None and not local_forecast.empty:
    forecast_col = local_forecast.columns[0]
    
    fx = local_forecast.index
    fy = local_forecast[forecast_col]
        
    fig_master.add_trace(
        go.Scatter(x=fx, y=fy, mode='lines', name='Forecasted Price', line=dict(width=3)),
        row=1, col=1
    )

if data.get('status') != 'OK - Level High':
    opt_date = data.get('optimal_buy_date')
    opt_price = data.get('optimal_buy_price')
    if opt_date:
        fig_master.add_trace(
            go.Scatter(x=[opt_date], y=[opt_price], mode='markers', marker=dict(size=14, color='red', symbol='star'), name='Optimal Buy Point'),
            row=1, col=1
        )

hist_tank = data.get('historical_tank_level')
last_hist_tank_date = None
last_hist_tank_val = None

if hist_tank is not None and not hist_tank.empty:
    if test_df_local is not None:
        start_date = test_df_local.index[0]
        recent_hist_tank = hist_tank[hist_tank.index >= start_date]
    else:
        recent_hist_tank = hist_tank.tail(30)
        
    if not recent_hist_tank.empty:
        last_hist_tank_date = recent_hist_tank.index[-1]
        last_hist_tank_val = recent_hist_tank.iloc[-1]
        
        fig_master.add_trace(
            go.Scatter(x=recent_hist_tank.index, y=recent_hist_tank.values, mode='lines', name='Past Tank Level', line=dict(width=2, dash='dot', color='#3498db')),
            row=2, col=1
        )

cons_proj = data.get('consumption_proj')
if cons_proj is not None and not cons_proj.empty:
    if last_hist_tank_date is not None:
        tx = [last_hist_tank_date] + list(cons_proj.index)
        ty = [last_hist_tank_val] + list(cons_proj['projected_tank_level'])
    else:
        tx = cons_proj.index
        ty = cons_proj['projected_tank_level']
        
    fig_master.add_trace(
        go.Scatter(x=tx, y=ty, mode='lines', name='Projected Tank Level', line=dict(width=3, color='#3498db')),
        row=2, col=1
    )
    
    dates = [tx[0], tx[-1]]
    fig_master.add_trace(
        go.Scatter(x=dates, y=[advisor.MINIMUM_TANK_LITERS]*2, mode='lines', name='Safety Min', line=dict(color='red', width=2, dash='dash'), hoverinfo='skip'),
        row=2, col=1
    )
    fig_master.add_trace(
        go.Scatter(x=dates, y=[advisor.LOOK_THRESHOLD_LITERS]*2, mode='lines', name='Look Threshold', line=dict(color='green', width=1, dash='dash'), hoverinfo='skip'),
        row=2, col=1
    )

    if data.get('is_critical_reached') and data.get('critical_date'):
         fig_master.add_vline(x=data.get('critical_date'), line_dash="dot", line_color="orange", annotation_text="Empty Date", row=2, col=1)

    if last_hist_price_date is not None:
         fig_master.add_vline(x=last_hist_price_date, line_width=1, line_dash="dash", line_color="gray", annotation_text="Today", row='all', col=1)

    all_dates = []
    if test_df_local is not None: all_dates.extend(test_df_local.index)
    if local_forecast is not None: all_dates.extend(local_forecast.index)
    
    if all_dates:
        min_date = min(all_dates)
        max_date = max(all_dates)
        date_range = pd.date_range(start=min_date, end=max_date, freq='D')
        for d in date_range:
            if d.weekday() == 5:  # Saturday
                start_str = d.strftime('%Y-%m-%d')
                end_str = (d + pd.Timedelta(days=2)).strftime('%Y-%m-%d')
                fig_master.add_vrect(x0=start_str, x1=end_str, fillcolor="rgba(150, 150, 150, 0.15)", layer="below", line_width=0, row=1, col=1)

    y_max = 0
    y_min = float('inf')
    if test_df_local is not None:
        y_max = max(y_max, past_prices.max())
        y_min = min(y_min, past_prices.min())
        if 'local_heating_oil_eur_per_100l' in test_df_local.columns:
            actual_local = test_df_local['local_heating_oil_eur_per_100l'].dropna()
            if not actual_local.empty:
                y_max = max(y_max, actual_local.max())
                y_min = min(y_min, actual_local.min())
    if local_forecast is not None and not local_forecast.empty:
        y_max = max(y_max, local_forecast[forecast_col].max())
        y_min = min(y_min, local_forecast[forecast_col].min())
        
    y_range = y_max - y_min if y_max > y_min else 10
    padded_max = y_max + (y_range * 0.15)
    padded_min = y_min

    tank_y_max = 0
    tank_y_min = float('inf')
    if 'recent_hist_tank' in locals() and not recent_hist_tank.empty:
        tank_y_max = max(tank_y_max, recent_hist_tank.max())
        tank_y_min = min(tank_y_min, recent_hist_tank.min())
    if cons_proj is not None and not cons_proj.empty:
        tank_y_max = max(tank_y_max, cons_proj['projected_tank_level'].max())
        tank_y_min = min(tank_y_min, cons_proj['projected_tank_level'].min())
        
    tank_y_max = max(tank_y_max, advisor.LOOK_THRESHOLD_LITERS)
    tank_y_min = min(tank_y_min, advisor.MINIMUM_TANK_LITERS)
        
    tank_y_range = tank_y_max - tank_y_min if tank_y_max > tank_y_min else 100
    tank_padded_max = tank_y_max + (tank_y_range * 0.15)
    tank_padded_min = tank_y_min

fig_master.update_layout(
    height=600,
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    plot_bgcolor="rgba(0,0,0,0)"
)
fig_master.update_yaxes(title_text="Price (EUR / 100L)", range=[padded_min, padded_max], showgrid=False, showline=True, linewidth=1, linecolor='gray', row=1, col=1)
fig_master.update_yaxes(title_text="Tank Level (Liters)", range=[tank_padded_min, tank_padded_max], showgrid=False, showline=True, linewidth=1, linecolor='gray', row=2, col=1)
fig_master.update_xaxes(showline=True, linewidth=1, linecolor='gray', row=1, col=1)
fig_master.update_xaxes(title_text="Date", showline=True, linewidth=1, linecolor='gray', row=2, col=1)

st.plotly_chart(fig_master, width='stretch')

st.divider()

st.subheader("Deep Dive Analysis")
tab_tracker, tab_mood, tab_eval = st.tabs(["Global ML Tracker", "Market Mood (Fear Index)", "Model Evaluation Data"])

with tab_tracker:
    forecast = data.get('champion_forecast')
    champ_name_global = data.get('champion_name')
    if eval_data and forecast is not None and not forecast.empty:
        fig_global = go.Figure()
        test_df = eval_data['test_df']
        uni = eval_data['uni_pred']
        multi = eval_data['multi_pred']
        lr = eval_data['lr_pred']
        
        fig_global.add_trace(go.Scatter(x=test_df.index, y=test_df['heating_oil_eur_per_100l'], mode='lines', name='Actual Global', line=dict(width=3)))
        fig_global.add_trace(go.Scatter(x=uni.index, y=uni['prophet_univariate'], mode='lines', name='Univariate Prophet', line=dict(dash='dash')))
        fig_global.add_trace(go.Scatter(x=multi.index, y=multi['prophet_multivariate'], mode='lines', name='Multivariate Prophet', line=dict(dash='dash')))
        fig_global.add_trace(go.Scatter(x=lr.index, y=lr['linear_regression'], mode='lines', name='Linear Regression', line=dict(dash='dash')))
        
        forecast_col = forecast.columns[0]
        fig_global.add_trace(go.Scatter(x=forecast.index, y=forecast[forecast_col], mode='lines', name=f'Global Future ({champ_name_global})', line=dict(width=3)))
        
        all_global_dates = list(test_df.index) + list(forecast.index)
        min_date = min(all_global_dates)
        max_date = max(all_global_dates)
        date_range = pd.date_range(start=min_date, end=max_date, freq='D')
        for d in date_range:
            if d.weekday() == 5:
                start_str = d.strftime('%Y-%m-%d')
                end_str = (d + pd.Timedelta(days=2)).strftime('%Y-%m-%d')
                fig_global.add_vrect(x0=start_str, x1=end_str, fillcolor="rgba(150, 150, 150, 0.15)", layer="below", line_width=0)
        
        fig_global.update_layout(title="Raw ML Algorithm Tracking (Global Market)", yaxis_title="EUR / 100L", xaxis_title="Date")
        st.plotly_chart(fig_global, width='stretch')

with tab_mood:
    st.write("The CBOE Crude Oil Volatility Index (OVX) acts as a 'Fear Index' for the oil market. High values indicate uncertainty and expected price swings. Low values indicate a calm market.")
    hist_df = data.get('historical_price')
    if hist_df is not None and 'oil_market_mood_ovx' in hist_df.columns:
        ovx_data = hist_df['oil_market_mood_ovx'].dropna()
        if not ovx_data.empty:
            recent_ovx = ovx_data.tail(90)
            fig_mood = px.area(recent_ovx, x=recent_ovx.index, y=recent_ovx.values, title="90-Day Oil Market Mood (OVX)")
            
            min_date = recent_ovx.index.min()
            max_date = recent_ovx.index.max()
            date_range = pd.date_range(start=min_date, end=max_date, freq='D')
            for d in date_range:
                if d.weekday() == 5:
                    start_str = d.strftime('%Y-%m-%d')
                    end_str = (d + pd.Timedelta(days=2)).strftime('%Y-%m-%d')
                    fig_mood.add_vrect(x0=start_str, x1=end_str, fillcolor="rgba(150, 150, 150, 0.15)", layer="below", line_width=0)
            
            fig_mood.update_layout(yaxis_title="OVX Value (Fear Index)", xaxis_title="Date")
            st.plotly_chart(fig_mood, width='stretch')

with tab_eval:
    st.write(f"The Advisor continuously evaluates algorithms against the last {advisor.EVAL_DAYS} days of actual prices to select the Champion.")
    if eval_data:
        maes = eval_data['maes']
        st.write(f"**Mean Absolute Errors (EUR/100L):**")
        for name, mae in maes.items():
            st.write(f"- **{name}:** {mae:.2f}")
