---
name: pvgis-pvlib-rooftop-pv
description: Use PVGIS TMY weather and pvlib to calculate and visualize photovoltaic yield, then optionally estimate building-level rooftop capacity and annual generation. Provides a local web UI, CLI, explicit parameters and reproducible outputs.
---

# 屋顶光伏计算

把用户的屋顶表、面积定义、比产额或气象数据整理成可执行配置，调用本目录的确定性程序计算，并交付分评价范围的结果及复算记录。

用户希望在网页上调整参数和看图时，在项目根目录运行 `python -m streamlit run web/app.py`（需安装 `.[weather,web]`）。网页调用相同计算模块，优先让用户从“比产额”入口开始；需要逐栋结果时再提供建筑表。使用说明见 [README](README.md)。

## 选择入口

- PVGIS比产额主入口：从 `examples/pvgis-yield.json` 建立配置，调用 `yield` 命令；无需建筑表。需要pvlib依赖及首次联网；阅读[PVGIS与气象说明](references/weather.md)，确认数据库、年份和时间定义。
- PVGIS逐栋发电量：从 `examples/pvgis-tmy.json` 建立配置，再提供建筑CSV，调用 `run` 命令。
- 已有年交流比产额：从 `examples/annual.json` 建立配置。该模式仅需 Python 标准库。
- 从气象计算比产额：从 `examples/weather.json` 建立配置；阅读 [气象说明](references/weather.md)，安装项目的 `weather` 可选依赖。
- 接入既有研究表：先核对实际输入版本、面积定义与计算链，再建立字段映射。
- 字段、可配置项、公式与边界见 [参数说明](references/parameters.md)。用户可修改地点、分类、列名、面积因素、密度、比产额、模型选项、损耗与范围。

在当前用户项目中保存配置及输出，路径相对于配置文件解析。通过 skill 目录的绝对路径调用：

```text
python <skill-dir>/scripts/pv.py validate --config <scenario.json>
python <skill-dir>/scripts/pv.py run --config <scenario.json> --output <new-run-directory>
python <skill-dir>/scripts/pv.py yield --config <pvgis-yield.json> --output <new-run-directory>
```

`validate` 会校验建筑行和比产额配置；气象模式也会执行模型。PVGIS模式按配置中的缓存策略决定是否请求网络。已有输出目录不会覆盖。配置中未识别的键会报错，不把它们当作已经生效的参数。

## 研究口径

- 明确输入是屋顶足迹还是组件面积。整体UF与它包含的排布、坡面、障碍等分项只能使用一种面积转换路径。
- 比产额为每kWp直流装机对应的年度交流电量，不含面积和容量密度。记录已含效应，避免方位、遮挡、系统损耗、温度和逆变器重复处理。
- PVGIS TMY不能指定辐射数据库；核对返回的数据库、气象时段和地平线设置，保留原始快照。程序目前只接受时段偏移为0.5小时的完整8760小时TMY。
- `included_effects` 是用户声明，程序能检查同名效应，不能自动判断不同命名是否表达同一物理效应。先核对来源。
- 主评价集合与条件性储备分开报告。技术容量、发电量与建筑数量占比使用各自分母。
- 年遮挡系数是输入的年度电量保留系数，不是本程序计算的几何遮挡；不能据此声称得到了逐时遮挡或接网能力。
- 不用片段气象数据推算全年。输入缺失、单位不明或关键定义不明时，说明缺少什么；可先运行合成演示，不代填真实研究参数。
- 不把演示值、原论文历史总量或通用示例当作新研究的默认依据。运行期避免排放不是全生命周期减排。

## 交付

给出运行目录、配置文件、各评价范围容量与发电量，以及输入来源和实际检查范围。`summary.json`、`buildings.csv`、`groups.csv`、`manifest.json` 支持进一步分析；气象模式另有参考系统的逐时或子小时输出。

本版不执行GIS几何遮挡、储能或现金流优化。需要这些功能时使用已有可核验输入或明确增加相应模块；不将尚未实现的设置写入配置并声称有效。
