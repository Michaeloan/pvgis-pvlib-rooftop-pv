# PVGIS + pvlib 屋顶光伏计算与可视化

[English](README_EN.md) · [参数说明](references/parameters.md) · [气象与PVGIS说明](references/weather.md) · [Skill入口](SKILL.md)

用网页调整 PVGIS 气象和 pvlib 系统参数，直接得到每 kWp 的年、月、逐时光伏出力；需要城市或项目规模结果时，再导入建筑表计算适装面积、容量和年发电量。网页与命令行共用同一套 Python 计算代码。

![PVGIS与pvlib比产额和月度、日内图表](assets/web-results.png)

上图来自 PVGIS 5.3 返回的广州坐标 TMY 气象、pvlib 0.15.2 和仓库示例系统参数。图中 1,242.3 kWh/kWp 是该**示例参考系统**的年交流比产额；它不是广州城市屋顶发电总量。建筑演示数据和修正系数均为合成值。

<details><summary>查看参数编辑页面</summary>

![PVGIS和pvlib参数编辑页面](assets/web-inputs.png)

</details>

## 研究案例：广州屋顶光伏技术潜力

作者提供的论文当前稿中，**主要评价边界排除城中村住宅子组**，得到以下城市级汇总结果：

| 指标 | 结果 |
|---|---:|
| 屋顶适装面积 | 177.94 km² |
| 直流技术装机容量 | 37.37 GWp |
| 典型气象年技术发电潜力 | 43.35 TWh/a |
| 运行期年减排量 | 19.15 Mt CO₂/a |

城中村住宅另列约 **10.73 TWh/a 条件性发电储备**，未计入上表的主要评价结果。减排量采用2023年广东省电力平均排放因子折算，属于运行期估计。详见[结果口径说明](docs/thesis-aggregate-results.md)。本仓库没有公开逐栋数据和论文原文，仓库演示数据也无法复算上述论文总量。

## 网页使用

需要 Python 3.10 或更新版本。在克隆后的项目目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[weather,web]"
.\.venv\Scripts\python.exe -m streamlit run web\app.py
```

打开终端给出的本地地址，通常为 `http://127.0.0.1:8501`。Windows 安装完成后也可以双击 [启动网页.cmd](启动网页.cmd)。网页只监听本机地址，不提供公网访问控制。

网页有两种计算目标：

1. **比产额**：无需建筑表。输入地点、PVGIS时段和系统参数，查看年比产额、月度柱状图、平均日内功率与典型年每日发电曲线。
2. **逐栋发电量**：上传建筑CSV或提供本机路径，配置字段映射、面积计算、容量密度、年修正和评价范围，得到逐栋结果、分范围汇总及图表。

气象来源可选 PVGIS TMY 或自备逐时/子小时气象CSV；逐栋模式还可直接使用已核实的年交流比产额。使用合成建筑或合成气象需要在页面明确勾选。每次运行产生独立目录，保存输入、配置快照、PVGIS来源记录、结果及SHA-256校验值；页面可下载结果。

**PVGIS TMY接口不提供指定辐射数据库的参数。** 配置可要求返回某个数据库，程序会核对实际结果；不同则报错。本仓库示例要求 `PVGIS-ERA5`，并只接受完整8760小时、辐照时间偏移为0.5小时的TMY。真实研究应核对数据源、时间定义和参数依据。

## 命令行与Skill

只求参考系统比产额：

```powershell
.\.venv\Scripts\python.exe scripts\pv.py yield --config examples\pvgis-yield.json --output outputs\yield-example
```

用合成建筑演示逐栋汇总：

```powershell
.\.venv\Scripts\python.exe scripts\pv.py run --config examples\pvgis-tmy.json --output outputs\buildings-example
```

本地气象样例见 `examples/weather.json`；已知年比产额样例见 `examples/annual.json`。输出目录必须是新目录，程序不会覆盖旧运行。安装包后也可使用 `pvgis-pvlib-pv` 命令。

本仓库根目录同时是可复用 Skill，名称为 **`pvgis-pvlib-rooftop-pv`**。将完整目录交给支持本地 Skill 的智能体使用；仅复制 `SKILL.md` 无法运行脚本。Skill 会引导选择比产额或逐栋入口，并核查面积基准、重复修正及评价范围。

## 输入与输出

| 输入 | 显式可调内容 |
|---|---|
| PVGIS | 经纬度、接口版本、TMY年份范围、地形地平线、自定义地平线、数据库核查、超时和缓存策略 |
| pvlib | 倾角、方位角、DC/AC比、组件温度系数、温度模型及参数、转置模型、AOI、反照率、系统损耗和逆变器效率 |
| 建筑 | ID、面积、功能、行政区、范围、屋顶参数组、比产额组、UF或分项面积系数、容量密度和年修正 |
| 扩展 | 可选的运行期电力排放因子、年份和来源 |

逐栋核算的核心关系是 `组件面积 = 输入面积 × 面积换算系数`、`直流容量 = 组件面积 × 容量密度`、`年交流电量 = 直流容量 × 年交流比产额 × 未计入的年修正`。整体UF与其分项系数互斥；比产额声明已包含的效应不能再次外乘同名修正。详细定义见 [参数说明](references/parameters.md)。

输出包括 `summary.json`、`config.snapshot.json`、`manifest.json`，以及逐时/月度或逐栋/分组CSV。PVGIS运行还保存本次使用的气象快照与服务元数据。`local/`和`outputs/`在 `.gitignore` 中，不会随代码仓库发布。

## 运行验证与边界

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

本地38项测试通过，其中包含网页表单的自动交互测试；另在真实浏览器中检查了页面和图表。项目还实际请求了PVGIS 5.3 TMY并通过pvlib计算了示例比产额。测试记录见 [VALIDATION.md](VALIDATION.md)。这些验证说明本示例入口可运行，不代表已对任意地点或组件型号完成实测校准。

当前版本支持 PVGIS TMY、完整本地气象年及预计算的年度建筑遮挡系数；尚未实现GIS几何遮挡、储能调度、LCOE、项目现金流或接网校验。真实建筑数据、学校模板、论文材料及私人工作文件均未包含在仓库。

许可：[MIT](LICENSE)。第三方依赖与PVGIS数据来源见 [THIRD_PARTY.md](THIRD_PARTY.md)。
