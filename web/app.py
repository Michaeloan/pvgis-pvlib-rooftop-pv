"""Local Streamlit UI for explicit PVGIS, pvlib and rooftop inputs."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from urban_rooftop_pv.core import InputError
from web.workspace import execute, template


st.set_page_config(page_title="屋顶光伏计算台", page_icon="☀", layout="wide")
st.markdown("""
<style>
html, body, [class*="css"] { font-family: "Noto Sans SC", "Microsoft YaHei", "Segoe UI", sans-serif; }
.block-container { max-width: 1320px; padding-top: 1.8rem; }
.solar-hero { background: #173B53; color: #F5F9FA; padding: 2.1rem 2.5rem; border-radius: 10px;
  display: flex; align-items: center; justify-content: space-between; gap: 2rem; border-left: 7px solid #D29A2B; }
.solar-hero h1 { font-size: clamp(2rem, 4vw, 3.2rem); line-height: 1.18; margin: .35rem 0 .65rem; letter-spacing: -.04em; }
.solar-hero p { max-width: 48rem; color: #DCE8ED; margin: 0; line-height: 1.7; }
.sun-disc { width: 112px; height: 112px; border-radius: 50%; border: 11px solid #D9A13A;
  box-shadow: 0 0 0 8px rgba(217,161,58,.16); flex: none; }
.solar-note { color: #416276; font-size: .9rem; margin-top: .7rem; }
@media (max-width: 700px) { .solar-hero { padding: 1.4rem; } .sun-disc { width: 56px; height: 56px; border-width: 7px; } }
</style>
<div class="solar-hero">
  <div><h1>屋顶光伏计算台</h1><p>先确定气象和系统，再看每 kWp 出力。需要城市尺度结果时，接入建筑清单，按评价范围独立汇总。</p></div>
  <div class="sun-disc" aria-hidden="true"></div>
</div>
""", unsafe_allow_html=True)
st.markdown('<p class="solar-note">所有影响结果的输入都写入本次配置快照；运行结果保存在本机，可下载复算。</p>', unsafe_allow_html=True)

task = st.radio("计算目标", ["比产额", "逐栋发电量"], horizontal=True, key="task")
building_mode = task == "逐栋发电量"
sources = ["PVGIS TMY", "本地气象"] + (["已有年比产额"] if building_mode else [])
source_label = st.selectbox("气象或比产额来源", sources, key="source_label")
source_key = {"PVGIS TMY": "pvgis", "本地气象": "weather", "已有年比产额": "annual"}[source_label]
kind = source_key + ("_buildings" if building_mode else "_yield")
cfg = template(kind)
spec = cfg["yields"]["reference"] if building_mode else cfg

if source_key != "annual":
    model_choice = st.selectbox("组件温度模型", ["faiman", "pvsyst"], key=f"{kind}:temperature_choice")
else:
    model_choice = None

with st.form(f"inputs_{kind}"):
    st.subheader("气象与研究范围" if source_key != "annual" else "已知年比产额")
    if source_key != "annual":
        loc = spec["location"]
        row = st.columns(4)
        lat = row[0].number_input("纬度 °N", min_value=-90.0, max_value=90.0, value=float(loc["latitude"]), format="%.4f", key=f"{kind}:lat")
        lon = row[1].number_input("经度 °E", min_value=-180.0, max_value=180.0, value=float(loc["longitude"]), format="%.4f", key=f"{kind}:lon")
        altitude = row[2].number_input("海拔 m", min_value=-500.0, max_value=10000.0, value=float(loc["altitude_m"]), key=f"{kind}:altitude")
        site_tz = row[3].text_input("地点时区", value=loc["timezone"], key=f"{kind}:site_tz")
        spec["location"] = {"latitude": lat, "longitude": lon, "altitude_m": altitude, "timezone": site_tz}
        t = spec["time"]
        with st.expander("时间轴与数据来源", expanded=True):
            row = st.columns(4)
            year = row[0].number_input("计算参考年", min_value=1900, max_value=2200, value=int(t["year"]), step=1, key=f"{kind}:year")
            interval = row[1].number_input("间隔 分钟", min_value=1, max_value=60, value=int(t["interval_minutes"]), step=1, key=f"{kind}:interval")
            position = row[2].selectbox("时间标签位置", ["start", "center", "end"], index=["start", "center", "end"].index(t["timestamp_position"]), key=f"{kind}:position")
            time_tz = row[3].text_input("序列时区", value=t["timezone"], key=f"{kind}:time_tz")
            spec["time"] = {"year": int(year), "interval_minutes": int(interval), "timestamp_position": position, "timezone": time_tz}
            spec["source"] = st.text_input("来源说明", value=spec["source"], key=f"{kind}:source")
            if source_key == "pvgis":
                p = spec["pvgis"]
                row = st.columns(3)
                p["start_year"] = int(row[0].number_input("PVGIS起始年", min_value=1900, max_value=2200, value=int(p["start_year"]), step=1, key=f"{kind}:start_year"))
                p["end_year"] = int(row[1].number_input("PVGIS结束年", min_value=1900, max_value=2200, value=int(p["end_year"]), step=1, key=f"{kind}:end_year"))
                p["timeout_seconds"] = int(row[2].number_input("请求超时 秒", min_value=1, max_value=300, value=int(p["timeout_seconds"]), step=1, key=f"{kind}:timeout"))
                row = st.columns(2)
                p["api_url"] = row[0].text_input("PVGIS接口地址（含版本）", value=p["api_url"], key=f"{kind}:api_url")
                expected = row[1].text_input("核查返回数据库（留空则接受实际选择）", value=p["expected_radiation_database"] or "", key=f"{kind}:expected_db")
                p["expected_radiation_database"] = expected.strip() or None
                row = st.columns(2)
                p["use_horizon"] = row[0].checkbox("加入PVGIS地形地平线", value=bool(p["use_horizon"]), key=f"{kind}:horizon")
                horizon_text = row[1].text_input("自定义地平线角度 °（逗号分隔，空为自动）", value="", key=f"{kind}:horizon_angles")
                if horizon_text.strip():
                    try:
                        p["user_horizon_deg"] = [float(x.strip()) for x in horizon_text.split(",")]
                    except ValueError:
                        p["user_horizon_deg"] = horizon_text
                p["cache_policy"] = st.selectbox("缓存策略", ["fetch_if_missing", "cache_only", "refresh"], key=f"{kind}:cache_policy")
                st.caption("TMY接口以JSON返回；本计算链使用UTC时间、60分钟间隔、0小时滚动。它们在配置快照中显式保留。")
                cache_path = st.text_input("PVGIS共享缓存目录", value=str(ROOT / "local" / "web_cache"), key=f"{kind}:cache_path")
            else:
                st.caption("气象列：time, ghi, dni, dhi, temp_air, wind_speed；时间需带UTC偏移，覆盖完整参考年。")
                weather_upload = st.file_uploader("上传气象CSV", type="csv", key=f"{kind}:weather_upload")
                weather_path = st.text_input("或填写本机气象CSV绝对路径", key=f"{kind}:weather_path")
                use_demo_weather = st.checkbox("使用合成气象示例", value=False, key=f"{kind}:demo_weather")
    else:
        spec["source"] = st.text_input("比产额来源", value=spec["source"], key=f"{kind}:source")
        spec["kwh_per_kwp"] = st.number_input("年交流比产额 kWh/kWp", min_value=0.0, value=float(spec["kwh_per_kwp"]), key=f"{kind}:yield_value")
        effects_text = st.text_input("已包含的效应ID（逗号分隔）", value=", ".join(spec["included_effects"]), key=f"{kind}:effects")
        spec["included_effects"] = [x.strip() for x in effects_text.split(",") if x.strip()]

    if source_key != "annual":
        with st.expander("光伏系统参数", expanded=True):
            s = spec["system"]
            row = st.columns(4)
            s["tilt_deg"] = row[0].number_input("倾角 °", min_value=0.0, max_value=90.0, value=float(s["tilt_deg"]), key=f"{kind}:tilt")
            s["azimuth_deg"] = row[1].number_input("方位角 °（北0，南180）", min_value=0.0, max_value=360.0, value=float(s["azimuth_deg"]), key=f"{kind}:azimuth")
            s["dc_ac_ratio"] = row[2].number_input("DC/AC容量比", min_value=0.01, value=float(s["dc_ac_ratio"]), step=0.05, key=f"{kind}:ratio")
            s["albedo"] = row[3].number_input("反照率", min_value=0.0, max_value=1.0, value=float(s["albedo"]), step=0.01, key=f"{kind}:albedo")
            row = st.columns(3)
            s["gamma_pdc"] = row[0].number_input("组件温度系数 1/°C", min_value=-0.02, max_value=0.02, value=float(s["gamma_pdc"]), step=0.0001, format="%.4f", key=f"{kind}:gamma")
            s["system_loss_pct"] = row[1].number_input("非遮挡系统损耗 %", min_value=0.0, max_value=100.0, value=float(s["system_loss_pct"]), key=f"{kind}:loss")
            s["inverter_efficiency"] = row[2].number_input("逆变器额定效率", min_value=0.001, max_value=1.0, value=float(s["inverter_efficiency"]), step=0.01, key=f"{kind}:inverter")
            row = st.columns(2)
            s["transposition"] = row[0].selectbox("辐照转置模型", ["haydavies", "isotropic", "perez"], index=["haydavies", "isotropic", "perez"].index(s["transposition"]), key=f"{kind}:transposition")
            s["aoi"] = row[1].selectbox("入射角损失", ["physical", "no_loss"], index=["physical", "no_loss"].index(s["aoi"]), key=f"{kind}:aoi")
            s["temperature_model"] = model_choice
            if model_choice == "faiman":
                params = {"u0": 25.0, "u1": 6.84}
            else:
                params = {"u_c": 29.0, "u_v": 0.0, "module_efficiency": 0.20, "alpha_absorption": 0.90}
            row = st.columns(len(params))
            s["temperature_parameters"] = {name: row[i].number_input(name, min_value=0.0, value=float(default), key=f"{kind}:temp:{model_choice}:{name}") for i, (name, default) in enumerate(params.items())}

    if building_mode:
        st.subheader("建筑数据与评价边界")
        building_upload = st.file_uploader("上传建筑CSV", type="csv", key=f"{kind}:building_upload")
        buildings_path = st.text_input("或填写本机建筑CSV绝对路径", key=f"{kind}:building_path")
        use_demo_buildings = st.checkbox("使用三栋合成建筑演示", value=False, key=f"{kind}:demo_buildings")
        cfg["name"] = st.text_input("情景名称", value=cfg["name"], key=f"{kind}:name")
        with st.expander("字段映射、屋顶参数和范围", expanded=False):
            st.caption("下方JSON会直接进入计算配置。列名、UF、容量密度、分类与修正都可修改。")
            cols = cfg["columns"]
            row = st.columns(2)
            for i, name in enumerate(cols):
                cols[name] = row[i % 2].text_input(name, value=cols[name], key=f"{kind}:col:{name}")
            profile_text = st.text_area("屋顶参数组 JSON", value=json.dumps(cfg["roof_profiles"], ensure_ascii=False, indent=2), height=230, key=f"{kind}:profiles")
            scope_text = st.text_area("评价范围 JSON", value=json.dumps(cfg["scope_labels"], ensure_ascii=False, indent=2), height=120, key=f"{kind}:scopes")
            corrections_text = st.text_area("外部修正 JSON", value=json.dumps(cfg["corrections"], ensure_ascii=False, indent=2), height=140, key=f"{kind}:corrections")
        carbon_enabled = st.checkbox("计算运行期避免排放", value="carbon" in cfg, key=f"{kind}:carbon_enabled")
        if carbon_enabled:
            carbon_default = cfg.get("carbon", {"kg_co2_per_kwh": 0.4, "factor_year": 2025, "source": "请填写来源"})
            row = st.columns(3)
            factor = row[0].number_input("排放因子 kgCO₂/kWh", min_value=0.0, value=float(carbon_default["kg_co2_per_kwh"]), key=f"{kind}:carbon_factor")
            factor_year = row[1].number_input("排放因子年份", min_value=1900, max_value=2200, value=int(carbon_default["factor_year"]), step=1, key=f"{kind}:carbon_year")
            factor_source = row[2].text_input("因子来源", value=carbon_default["source"], key=f"{kind}:carbon_source")

    submitted = st.form_submit_button("运行并绘图", type="primary", width="stretch")

if submitted:
    try:
        if building_mode:
            cfg["roof_profiles"] = json.loads(profile_text)
            cfg["scope_labels"] = json.loads(scope_text)
            cfg["corrections"] = json.loads(corrections_text)
            if carbon_enabled:
                cfg["carbon"] = {"kg_co2_per_kwh": factor, "factor_year": int(factor_year), "source": factor_source}
            else:
                cfg.pop("carbon", None)
        inputs = {"run_root": ROOT / "local" / "web_runs", "cache_root": Path(cache_path) if source_key == "pvgis" else ROOT / "local" / "web_cache"}
        if source_key == "weather":
            inputs.update(uploaded_weather=weather_upload, weather_path=weather_path, use_demo_weather=use_demo_weather)
        if building_mode:
            inputs.update(uploaded_buildings=building_upload, buildings_path=buildings_path, use_demo_buildings=use_demo_buildings)
        with st.spinner("正在校验输入并计算…"):
            output, result = execute(cfg, building_mode, **inputs)
        st.session_state["last_run"] = {"path": str(output), "kind": kind, "building_mode": building_mode,
                                        "demo_buildings": use_demo_buildings if building_mode else False,
                                        "demo_weather": use_demo_weather if source_key == "weather" else False}
        st.success("计算完成。结果和输入快照已保存。")
    except (InputError, OSError, ValueError, KeyError) as exc:
        st.error(f"未完成计算：{exc}")


def show_result(record: dict):
    output = Path(record["path"])
    if not output.is_dir():
        st.info("上次结果目录已移动。重新计算即可查看。")
        return
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    st.subheader("计算结果")
    if record["demo_buildings"]:
        st.info("建筑输入为合成演示数据。以下分组电量不能代表真实城市或项目。")
    if record["demo_weather"]:
        st.info("气象输入为合成演示数据。以下比产额不能代表真实地点。")
    if record["building_mode"]:
        scopes = summary["scopes"]
        table = pd.DataFrame([{"评价范围": k, "建筑数": v["building_count"], "组件面积 m²": v["module_area_m2"],
                               "直流容量 kWp": v["capacity_kwp"], "年交流电量 kWh": v["generation_kwh"]}
                              for k, v in scopes.items()])
        st.dataframe(table, hide_index=True, width="stretch")
        st.bar_chart(table.set_index("评价范围")["年交流电量 kWh"], color="#BB791C")
        groups = pd.read_csv(output / "groups.csv")
        if not groups.empty:
            st.markdown("**分组发电量**")
            st.bar_chart(groups.groupby("category")["generation_kwh"].sum().sort_values(ascending=False), color="#397F8B")
            st.dataframe(groups, hide_index=True, width="stretch")
        yield_info = next(iter(summary["resolved_yields"].values()))
        profile_name = next(iter(summary["yield_profile_files"].values()), None)
    else:
        yield_info = summary["resolved_yield"]
        profile_name = "yield_profile.csv"
    cols = st.columns(3)
    cols[0].metric("年交流比产额", f"{yield_info['kwh_per_kwp']:,.1f} kWh/kWp")
    cols[1].metric("气象时间步", f"{yield_info.get('interval_minutes', '—')} 分钟")
    cols[2].metric("数据来源", yield_info.get("pvgis", {}).get("radiation_database", "本地或已知比产额"))
    if profile_name and (output / profile_name).is_file():
        profile = pd.read_csv(output / profile_name)
        profile["time"] = pd.to_datetime(profile["time"], utc=True)
        config = json.loads((output / "config.snapshot.json").read_text(encoding="utf-8"))
        spec = config["yields"]["reference"] if record["building_mode"] else config
        time_zone = spec["location"]["timezone"]
        local = profile["time"].dt.tz_convert(time_zone)
        profile["month"] = local.dt.month
        profile["hour"] = local.dt.hour
        profile["day"] = local.dt.strftime("%m-%d")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**每月比产额** · kWh/kWp")
            st.bar_chart(profile.groupby("month")["energy_kwh_per_kwp"].sum(), color="#BB791C")
        with c2:
            st.markdown("**平均日内功率** · W/kWp")
            st.line_chart(profile.groupby("hour")["ac_w_per_kwp"].mean(), color="#397F8B")
        st.markdown("**典型年每日发电量** · kWh/kWp")
        st.area_chart(profile.groupby("day")["energy_kwh_per_kwp"].sum(), color="#79A8B1")
        st.caption(f"图表按地点时区 {time_zone} 展示；TMY跨年的小时按月日归入同一个典型年。")
        with st.expander("逐时或子小时原始结果"):
            st.dataframe(profile[["time", "ac_w_per_kwp", "energy_kwh_per_kwp"]], hide_index=True, width="stretch", height=320)
    st.caption(f"结果目录：{output}")
    for name, label in (("config.snapshot.json", "下载配置"), ("summary.json", "下载结果 JSON"),
                        ("yield_profile.csv", "下载逐时结果"), ("groups.csv", "下载分组结果")):
        path = output / name
        if path.is_file():
            st.download_button(label, data=path.read_bytes(), file_name=name, mime="application/json" if name.endswith("json") else "text/csv", key=f"download:{name}")


if "last_run" in st.session_state:
    show_result(st.session_state["last_run"])
else:
    st.info("设置参数后点击“运行并绘图”。首次PVGIS请求需要联网，之后可复用缓存。")
