import streamlit as st
import plotly.graph_objects as go
from datetime import datetime
import pandas as pd

import advisor

st.set_page_config(page_title="Heating Oil Advisor", layout="wide", page_icon="🛢️")

# Series colours (readable on both the light and the dark Streamlit theme)
BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
YELLOW = "#eda100"
MUTED = "#898781"
# Status colours, only used for the recommendation and the reserve line
GOOD = "#0ca30c"
WARNING = "#fab219"
CRITICAL = "#d03b3b"

CACHE_TTL_SECONDS = 3600
DEFAULT_ORDER_LITERS = 2000

st.markdown(
    """
    <style>
    .block-container {padding-top: 2.5rem; max-width: 1250px;}
    .verdict {border-left: 6px solid var(--tone); border-radius: 12px; padding: 1.1rem 1.4rem;
              background: color-mix(in srgb, var(--tone) 12%, transparent);}
    .verdict-label {font-size: 0.8rem; letter-spacing: 0.06em; text-transform: uppercase; opacity: 0.7;}
    .verdict-title {font-size: 2rem; font-weight: 700; line-height: 1.25; margin: 0.15rem 0 0.4rem 0;}
    .verdict-body {font-size: 1.05rem; line-height: 1.5;}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_data():
    return advisor.get_advisor_data()


def fmt_date(d):
    return f"{d:%a} {d.day} {d:%b}"


def fmt_liters(v):
    return f"{v:,.0f} L"


def fmt_price(v):
    return f"{v:.2f} €"


def shade_weekends(fig, start, end):
    for d in pd.date_range(start=start, end=end, freq='D'):
        if d.weekday() == 5:  # Saturday
            fig.add_vrect(x0=d.strftime('%Y-%m-%d'), x1=(d + pd.Timedelta(days=2)).strftime('%Y-%m-%d'),
                          fillcolor="rgba(150, 150, 150, 0.10)", layer="below", line_width=0)


def mark_date(fig, x, text, color=MUTED):
    fig.add_shape(type="line", x0=x, x1=x, y0=0, y1=1, yref="paper", line=dict(color=color, width=1, dash="dash"))
    fig.add_annotation(x=x, y=1, yref="paper", yanchor="bottom", text=text, showarrow=False, font=dict(size=12, color=color))


def style_chart(fig, height, y_title, y_suffix):
    fig.update_layout(
        height=height,
        hovermode="x unified",
        margin=dict(l=10, r=10, t=70, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.12, xanchor="left", x=0),
    )
    fig.update_yaxes(title_text=y_title, ticksuffix=y_suffix)
    fig.update_xaxes(showgrid=False)


title_col, refresh_col = st.columns([5, 1], vertical_alignment="bottom")
with title_col:
    st.title("🛢️ Heating Oil Advisor")
    st.caption("Tells you when to refill your tank: it watches your oil level, predicts how fast you will use it, "
               "and forecasts the price for the next 90 days.")
with refresh_col:
    if st.button("↻ Refresh data", width='stretch', help="The forecast is recalculated at most once per hour. Click to recalculate now."):
        load_data.clear()
        st.rerun()

with st.spinner("Loading your data and calculating the forecast... (this takes a few seconds)"):
    data = load_data()

if 'error' in data:
    st.error(f"**The dashboard could not load your data.** {data['error']}")
    st.info("Check that the InfluxDB connection settings are correct and that the daily data update has run at least once.")
    st.stop()

today = datetime.now().date()
status = data.get('status')
tank_level = data.get('current_tank_level', 0)
local_price = data.get('current_local_price', 0)
champion_name = data.get('champion_name')
eval_data = data.get('eval_data')
hist_df = data.get('historical_price')
offset = data.get('regional_offset', 0)
critical_date = data.get('critical_date')
is_critical_reached = data.get('is_critical_reached')

local_forecast = data.get('local_champion_forecast')
forecast_series = None
if local_forecast is not None and not local_forecast.empty:
    forecast_series = local_forecast[local_forecast.columns[0]]

if status == 'OK - Level High':
    best_date = forecast_series.idxmin() if forecast_series is not None else None
    best_price = forecast_series.min() if forecast_series is not None else None
    savings = 0.0
else:
    best_date = data.get('optimal_buy_date')
    best_price = data.get('optimal_buy_price')
    savings = data.get('expected_savings', 0)

days_to_reserve = (critical_date.date() - today).days if is_critical_reached else None

# --- Recommendation ---------------------------------------------------------

if status == 'OK - Level High':
    tone, headline = GOOD, "✅ No need to buy yet"
    body = (f"Your tank holds <b>{fmt_liters(tank_level)}</b>. The advisor only starts looking for a good price "
            f"once it drops below {fmt_liters(advisor.LOOK_THRESHOLD_LITERS)}.")
elif status == 'WAIT':
    tone, headline = WARNING, f"⏳ Wait – buy around {fmt_date(best_date)}"
    body = (f"The price is forecast to fall from {fmt_price(local_price)} to <b>{fmt_price(best_price)}</b> per 100 L "
            f"in {data.get('days_to_wait')} days. ")
    if is_critical_reached:
        body += f"You have time: your tank reaches its {fmt_liters(advisor.MINIMUM_TANK_LITERS)} reserve around {fmt_date(critical_date)}."
    else:
        body += f"You have time: your tank stays above its reserve for at least {advisor.FORECAST_DAYS} more days."
else:
    tone, headline = BLUE, "🛒 Buy now"
    body = f"Today's price of <b>{fmt_price(local_price)}</b> per 100 L is the best the forecast expects "
    if is_critical_reached:
        body += f"before your tank reaches its {fmt_liters(advisor.MINIMUM_TANK_LITERS)} reserve around {fmt_date(critical_date)}."
    else:
        body += f"in the next {advisor.FORECAST_DAYS} days."

verdict_col, order_col = st.columns([2.2, 1])

with verdict_col:
    st.markdown(
        f"""
        <div class="verdict" style="--tone: {tone};">
            <div class="verdict-label">Recommendation</div>
            <div class="verdict-title">{headline}</div>
            <div class="verdict-body">{body}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    note = data.get('llm_notification') or ''
    # Without a working Gemini key the advisor returns its raw prompt, which is not meant for readers
    if note and not note.startswith(('[LLM]', 'Error calling Gemini')):
        st.write("")
        st.markdown(f"**🤖 Advisor's note**  \n{note}")

with order_col:
    with st.container(border=True):
        order_liters = st.number_input("How much would you order? (litres)", min_value=500, max_value=20000,
                                       value=DEFAULT_ORDER_LITERS, step=500)
        st.metric("Cost at today's price", f"{local_price * order_liters / 100:,.0f} €")
        if status == 'WAIT' and savings > 0:
            st.metric(f"Saved by waiting until {fmt_date(best_date)}", f"{savings * order_liters / 100:,.0f} €",
                      help="Difference between today's price and the lowest forecast price, for the amount above. This is a forecast, not a guarantee.")

# --- Key numbers ------------------------------------------------------------

price_change = None
if hist_df is not None:
    price_col = 'local_heating_oil_eur_per_100l' if 'local_heating_oil_eur_per_100l' in hist_df.columns else 'heating_oil_eur_per_100l'
    price_hist = hist_df[price_col].dropna()
    if len(price_hist) > 7:
        price_change = price_hist.iloc[-1] - price_hist.iloc[-8]

k1, k2, k3, k4 = st.columns(4)
with k1:
    with st.container(border=True):
        st.metric("Oil in your tank", fmt_liters(tank_level), help="Latest reading from your tank sensor.")
        st.caption(f"Reserve: {fmt_liters(advisor.MINIMUM_TANK_LITERS)}")
with k2:
    with st.container(border=True):
        st.metric("Reserve reached in", f"{days_to_reserve} days" if is_critical_reached else f"{advisor.FORECAST_DAYS}+ days",
                  help=f"When your tank is expected to drop to the {fmt_liters(advisor.MINIMUM_TANK_LITERS)} safety reserve, "
                       "based on your past consumption and typical temperatures for the season.")
        st.caption(f"Around {fmt_date(critical_date)}" if is_critical_reached else "Not within the forecast period")
with k3:
    with st.container(border=True):
        st.metric("Price today (per 100 L)", fmt_price(local_price),
                  delta=f"{price_change:+.2f} € vs. a week ago" if price_change is not None else None, delta_color="inverse",
                  help="Latest heating oil price in your area.")
with k4:
    with st.container(border=True):
        st.metric("Lowest forecast price (per 100 L)", fmt_price(best_price) if best_price is not None else "–",
                  help="The cheapest day the forecast expects before your tank reaches its reserve." if is_critical_reached
                  else f"The cheapest day the forecast expects in the next {advisor.FORECAST_DAYS} days.")
        if best_date is not None:
            st.caption(f"Expected {fmt_date(best_date)}")

# --- Price ------------------------------------------------------------------

test_df = eval_data['test_df'] if eval_data else None
x_start = test_df.index[0] if test_df is not None else None
x_end = forecast_series.index[-1] if forecast_series is not None else None
today_x = test_df.index[-1] if test_df is not None else None

st.subheader("When is oil cheapest?")
st.caption("Solid lines are prices that were actually paid, the dashed line is the forecast. Grey bands are weekends, when prices are not updated.")

fig_price = go.Figure()
price_hover = "%{y:.2f} €<extra>%{fullData.name}</extra>"
last_actual_x, last_actual_y = None, None

if test_df is not None:
    estimate = test_df['heating_oil_eur_per_100l'] + offset
    last_actual_x, last_actual_y = estimate.index[-1], estimate.iloc[-1]
    fig_price.add_trace(go.Scatter(x=estimate.index, y=estimate, mode='lines', name='Wholesale market (adjusted to your area)',
                                   line=dict(width=1.5, dash='dot', color=MUTED), hovertemplate=price_hover))

    if 'local_heating_oil_eur_per_100l' in test_df.columns:
        actual_local = test_df['local_heating_oil_eur_per_100l'].dropna()
        if not actual_local.empty:
            last_actual_x, last_actual_y = actual_local.index[-1], actual_local.iloc[-1]
            fig_price.add_trace(go.Scatter(x=actual_local.index, y=actual_local, mode='lines', name='Price in your area',
                                           line=dict(width=2, color=BLUE), hovertemplate=price_hover))

    if 'steil_heating_oil_eur_per_100l' in test_df.columns:
        actual_steil = test_df['steil_heating_oil_eur_per_100l'].dropna()
        if not actual_steil.empty:
            fig_price.add_trace(go.Scatter(x=actual_steil.index, y=actual_steil, mode='lines', name='Steil Energie',
                                           line=dict(width=2, color=ORANGE), hovertemplate=price_hover))

if forecast_series is not None:
    fx, fy = list(forecast_series.index), list(forecast_series.values)
    if last_actual_x is not None:
        fx, fy = [last_actual_x] + fx, [last_actual_y] + fy
    fig_price.add_trace(go.Scatter(x=fx, y=fy, mode='lines', name='Forecast',
                                   line=dict(width=2, dash='dash', color=BLUE), hovertemplate=price_hover))

if status != 'OK - Level High' and best_date is not None:
    fig_price.add_trace(go.Scatter(x=[best_date], y=[best_price], mode='markers', name='Best day to buy',
                                   marker=dict(size=14, color=GOOD, symbol='star', line=dict(width=1, color='white')),
                                   hovertemplate=price_hover))
    fig_price.add_annotation(x=best_date, y=best_price, text=f"Best day to buy<br>{fmt_date(best_date)} · {fmt_price(best_price)}",
                             showarrow=True, arrowhead=0, arrowcolor=MUTED, ax=0, ay=45)

if today_x is not None:
    mark_date(fig_price, today_x, "Today")
if x_start is not None and x_end is not None:
    shade_weekends(fig_price, x_start, x_end)
    fig_price.update_xaxes(range=[x_start, x_end])

style_chart(fig_price, 400, "Price per 100 L", " €")
st.plotly_chart(fig_price, width='stretch')

# --- Tank -------------------------------------------------------------------

st.subheader("How long will your tank last?")
st.caption("The dashed line shows how your oil level is expected to fall, based on your past consumption and typical temperatures for the season.")

fig_tank = go.Figure()
tank_hover = "%{y:,.0f} L<extra>%{fullData.name}</extra>"
last_tank_x, last_tank_y = None, None

hist_tank = data.get('historical_tank_level')
if hist_tank is not None and not hist_tank.empty:
    recent_hist_tank = hist_tank[hist_tank.index >= x_start] if x_start is not None else hist_tank.tail(30)
    if not recent_hist_tank.empty:
        last_tank_x, last_tank_y = recent_hist_tank.index[-1], recent_hist_tank.iloc[-1]
        fig_tank.add_trace(go.Scatter(x=recent_hist_tank.index, y=recent_hist_tank.values, mode='lines', name='Measured level',
                                      line=dict(width=2, color=BLUE), hovertemplate=tank_hover))

cons_proj = data.get('consumption_proj')
tank_top = max(tank_level, advisor.LOOK_THRESHOLD_LITERS)
if cons_proj is not None and not cons_proj.empty:
    tx, ty = list(cons_proj.index), list(cons_proj['projected_tank_level'])
    if last_tank_x is not None:
        tx, ty = [last_tank_x] + tx, [last_tank_y] + ty
        tank_top = max(tank_top, recent_hist_tank.max())
    fig_tank.add_trace(go.Scatter(x=tx, y=ty, mode='lines', name='Expected level',
                                  line=dict(width=2, dash='dash', color=BLUE), hovertemplate=tank_hover))

fig_tank.add_hrect(y0=0, y1=advisor.MINIMUM_TANK_LITERS, fillcolor="rgba(208, 59, 59, 0.10)", layer="below", line_width=0)
fig_tank.add_hline(y=advisor.MINIMUM_TANK_LITERS, line=dict(color=CRITICAL, width=1.5, dash="dash"),
                   annotation_text=f"Safety reserve · {fmt_liters(advisor.MINIMUM_TANK_LITERS)}", annotation_position="top right",
                   annotation_font=dict(size=12, color=CRITICAL))
fig_tank.add_hline(y=advisor.LOOK_THRESHOLD_LITERS, line=dict(color=MUTED, width=1, dash="dot"),
                   annotation_text=f"Advisor starts watching prices · {fmt_liters(advisor.LOOK_THRESHOLD_LITERS)}", annotation_position="top right",
                   annotation_font=dict(size=12, color=MUTED))

if today_x is not None:
    mark_date(fig_tank, today_x, "Today")
if is_critical_reached:
    mark_date(fig_tank, critical_date, "Reserve reached", color=CRITICAL)
if x_start is not None and x_end is not None:
    fig_tank.update_xaxes(range=[x_start, x_end])

style_chart(fig_tank, 340, "Oil in tank", " L")
fig_tank.update_yaxes(range=[0, tank_top * 1.15], tickformat=",.0f")
st.plotly_chart(fig_tank, width='stretch')

# --- Details ----------------------------------------------------------------

st.divider()
st.subheader("Behind the forecast")
st.caption("Optional background for the curious – you do not need any of this to follow the recommendation above.")

tab_eval, tab_mood = st.tabs(["How reliable is the price forecast?", "How nervous is the oil market?"])

with tab_eval:
    if eval_data:
        maes = eval_data['maes']
        st.write(f"Every time the dashboard updates, three forecasting methods are tested against the last {advisor.EVAL_DAYS} days of real prices. "
                 f"The one with the smallest error makes the forecast – currently **{champion_name}**, "
                 f"which was off by **{maes[champion_name]:.2f} €** per 100 L on average.")

        mae_table = pd.DataFrame({'Method': list(maes.keys()), 'Average error (€ per 100 L)': list(maes.values())})
        mae_table = mae_table.sort_values('Average error (€ per 100 L)').reset_index(drop=True)
        mae_table['In use'] = mae_table['Method'].map(lambda name: "✓" if name == champion_name else "")
        st.dataframe(mae_table, hide_index=True, width='content',
                     column_config={'Average error (€ per 100 L)': st.column_config.NumberColumn(format="%.2f")})

        forecast = data.get('champion_forecast')
        if forecast is not None and not forecast.empty:
            st.caption(f"What each method predicted for the last {advisor.EVAL_DAYS} days, compared with the real wholesale price.")
            fig_global = go.Figure()
            actual = test_df['heating_oil_eur_per_100l']
            fig_global.add_trace(go.Scatter(x=actual.index, y=actual, mode='lines', name='Real price',
                                            line=dict(width=2.5, color=BLUE), hovertemplate=price_hover))
            for pred_key, pred_col, name, color in [
                ('uni_pred', 'prophet_univariate', 'Univariate Prophet', ORANGE),
                ('multi_pred', 'prophet_multivariate', 'Multivariate Prophet', AQUA),
                ('lr_pred', 'linear_regression', 'Linear Regression', YELLOW),
            ]:
                pred = eval_data[pred_key]
                fig_global.add_trace(go.Scatter(x=pred.index, y=pred[pred_col], mode='lines', name=name,
                                                line=dict(width=1.5, dash='dot', color=color), hovertemplate=price_hover))

            forecast_col = forecast.columns[0]
            fig_global.add_trace(go.Scatter(x=[actual.index[-1]] + list(forecast.index), y=[actual.iloc[-1]] + list(forecast[forecast_col]),
                                            mode='lines', name=f'Forecast ({champion_name})',
                                            line=dict(width=2, dash='dash', color=BLUE), hovertemplate=price_hover))

            mark_date(fig_global, actual.index[-1], "Today")
            shade_weekends(fig_global, actual.index[0], forecast.index[-1])
            style_chart(fig_global, 400, "Wholesale price per 100 L", " €")
            st.plotly_chart(fig_global, width='stretch')
    else:
        st.info("There is not enough price history yet to compare the forecasting methods.")

with tab_mood:
    ovx_data = hist_df['oil_market_mood_ovx'].dropna() if hist_df is not None and 'oil_market_mood_ovx' in hist_df.columns else None
    if ovx_data is not None and not ovx_data.empty:
        recent_ovx = ovx_data.tail(90)
        current_ovx = recent_ovx.iloc[-1]
        if current_ovx < 30:
            mood = "😌 Calm"
        elif current_ovx < 45:
            mood = "😬 Nervous"
        else:
            mood = "😱 Very nervous"

        mood_col, text_col = st.columns([1, 3], vertical_alignment="center")
        with mood_col:
            st.metric("Market mood today", mood)
            st.caption(f"Fear index: {current_ovx:.0f}")
        with text_col:
            st.write("The oil market's \"fear index\" (CBOE Crude Oil Volatility Index, OVX) measures how strongly traders expect prices to swing. "
                     "A high value means large price jumps are likely – in either direction – so forecasts are less dependable. "
                     "A low value means a calm market. Roughly: below 30 is calm, above 45 is very nervous.")

        fig_mood = go.Figure()
        fig_mood.add_trace(go.Scatter(x=recent_ovx.index, y=recent_ovx.values, mode='lines', name='Fear index', fill='tozeroy',
                                      line=dict(width=2, color=BLUE), fillcolor="rgba(42, 120, 214, 0.15)",
                                      hovertemplate="%{y:.1f}<extra>Fear index</extra>"))
        shade_weekends(fig_mood, recent_ovx.index.min(), recent_ovx.index.max())
        style_chart(fig_mood, 340, "Fear index (OVX), last 90 days", "")
        st.plotly_chart(fig_mood, width='stretch')
    else:
        st.info("No market mood data is available yet.")
