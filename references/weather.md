# PVGIS与本地气象模式

## PVGIS TMY简单入口

从 `examples/pvgis-yield.json` 复制配置并执行 `yield`，直接得到每kWp年/月/逐时交流电量；需要建筑尺度再用 `examples/pvgis-tmy.json` 执行 `run`。`mode="pvgis_tmy"` 时通过 pvlib 的 `get_pvgis_tmy` 调用已明确版本的PVGIS接口，返回 GHI、DNI、DHI、气温与风速，再交给本项目的 pvlib PVWatts 模型计算每kWp年交流电量。

请求输入包括经纬度、服务版本入口、年份范围、地形地平线开关、可选用户地平线、输出格式与超时。计算输入包括时区、参考年、倾角、方位、组件温度系数、逆变器容量比与效率、非遮挡损耗、辐照转置、AOI、温度模型和反照率。全部列在配置中；系统模型当前固定PVWatts DC/AC，并在配置说明中明确。

官方TMY接口没有 `raddatabase` 选择项。所用数据库由PVGIS服务返回；配置的 `expected_radiation_database` 可以断言结果，如 `PVGIS-ERA5`。不符时失败，不在程序里悄悄改库。服务还返回实际选择的月份。本模式要求返回完整8760小时、辐照时间偏移0.5小时。若选择的数据库不满足这些时间条件，先转为本地气象文件并核对时间定义。

`cache_policy=fetch_if_missing` 首次请求并保留气象CSV和服务元数据，后续相同请求离线复用。配置参数变更时缓存签名不匹配会失败；`refresh` 明确重新获取，`cache_only` 保证不联网。每次计算的输出目录还复制所用缓存，防止旧运行只依赖可能被刷新覆盖的共享缓存。完整请求参数、返回数据库、选中月份、pvlib版本、缓存校验值都可追溯。

已确认的主要来源：[欧盟委员会PVGIS API说明](https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis/using-pvgis-5/api-non-interactive-service_en)、[pvlib PVGIS I/O说明](https://pvlib-python.readthedocs.io/en/stable/reference/iotools.html)。2026-09-23核对；实际请求版本由配置决定。

## 输入与时间

CSV必需字段：`time,ghi,dni,dhi,temp_air,wind_speed`。辐照为W/m²，温度为°C，风速为m/s。数值表示配置时段的平均值；采用时段中心的太阳位置计算。瞬时观测需先按研究方法整理为时段输入，并记录处理方法。

time为带偏移量的ISO时间，如 `2025-01-01T00:00:00+08:00`。不猜测无时区时间戳。location.timezone指定系统地点；time.timezone必须显式指定输入序列的日历时区。time.year为完整该时区日历年；time.interval_minutes需为60的正整数约数；timestamp_position可为start、center、end。

程序将时间换算为配置时区并校验完整有序时间网格。闰年为8784小时，普通年为8760小时；有夏令时的时区按实际时区日历生成网格。没有缺失插值或自动排序。逐时/子小时功率积分：`energy_kwh_per_kwp = ac_w_per_kwp × interval_minutes / 60 / 1000`。

TMY各月份的原始年份可能不同，不能把它们直接当作一个连续年份。需要先通过可信的导出工具映射到完整参考年，同时记录月份来源及时间含义。本版不会自动从PVGIS、ERA5或NASA下载或转换原始文件。

## 系统配置

全部字段显式填写，参考 examples/weather.json。

| 字段 | 含义与支持值 |
|---|---|
| location.latitude / longitude | 纬度[-90,90]，经度[-180,180] |
| location.altitude_m | 海拔m，[-500,10000] |
| location.timezone | IANA时区，如Asia/Shanghai |
| tilt_deg | 组件倾角[0,90]度 |
| azimuth_deg | 北=0，东=90，南=180，西=270；[0,360] |
| dc_ac_ratio | 阵列DC额定容量 / 逆变器AC额定容量，大于0 |
| gamma_pdc | 功率温度系数，单位1/°C，范围[-0.02,0.02] |
| system_loss_pct | [0,100]%；非遮挡、非温度、非逆变器的聚合DC损耗 |
| inverter_efficiency | 额定逆变器效率(0,1] |
| transposition | isotropic / haydavies / perez |
| aoi | physical / no_loss |
| temperature_model | faiman / pvsyst |
| temperature_parameters | 与模型对应的显式参数，见下 |
| albedo | 地表反照率[0,1] |

Faiman参数：u0>0，u1≥0。PVsyst参数：u_c>0，u_v≥0，module_efficiency和alpha_absorption均在[0,1]。它们影响热模型，不自动替代建筑参数中的容量密度。

DC与AC模型当前固定为PVWatts，光谱为no_loss。每组比产额用1kWp DC参考阵列计算。逆变器DC输入限值设置为 `1000 / dc_ac_ratio / inverter_efficiency` W，保持DC/AC比的定义；不将该值误设为阵列DC容量。

聚合系统损耗借pvlib的soiling参数传入，其余具名损耗槽全部置0；不表示损耗全部来自积尘。输出声明已经包含orientation、temperature、inverter、system_losses、aoi，防止再次以相同ID外乘。

本地合成天气仅验证软件运行，无法作为广州或其他地点的气候数据。多地点或多朝向分别创建yield组并由建筑yield_id引用；不自动执行空间插值。

## 模型依据

- [pvlib PVWatts DC](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.pvsystem.pvwatts_dc.html)
- [pvlib PVWatts inverter](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.inverter.pvwatts.html)
- [pvlib Faiman temperature](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.temperature.faiman.html)

文档查阅日期：2026-09-23。实际调用版本写入summary.json；本次测试使用pvlib 0.15.2。
