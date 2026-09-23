# 参数与数据契约（schema_version = 1）

配置使用UTF-8 JSON；表格为UTF-8 CSV（允许BOM）。JSON重复键、未知参数、CSV重复表头会报错。示例中的数值仅为演示，项目不内置广州主结果。

## 建筑表

`columns`映射以下逻辑字段到用户CSV的实际列名，七项全部必需。CSV可以保留其他字段；程序只读取映射字段及配置的修正列。

| 字段 | 含义 |
|---|---|
| building_id | 非空且唯一的建筑ID；保留为文本以保护前导零 |
| area_m2 | 非负有限数，单位m²；含义取决于面积模式 |
| roof_profile | roof_profiles中的键 |
| yield_id | yields中的键；可为不同气象节点/朝向建立多组 |
| scope | scope_labels中的键；每栋只归属于一个范围 |
| district | 分区标签；不分区时使用明确占位如all |
| category | 功能标签；不分类时使用all |

空值、重复ID、未定义参数组/比产额组/范围不会静默填零或丢弃。需要排除的建筑应在输入准备阶段显式筛选并保留筛选记录；也可另设排除范围，仅用于独立报告。

## 面积与容量

每个roof_profile必须包含 `area_mode`、`capacity_density_kwp_m2`和 `source`。

`capacity_density_kwp_m2`：每平方米组件面积对应的直流额定容量，必须大于0；不是每平方米足迹容量，也不是百分数。以0.20为例，相当于200 Wp/m²。

三种互斥模式：

| area_mode | area_m2含义 | 其他参数与计算 |
|---|---|---|
| effective_uf | 建筑屋顶水平足迹 | module_area = area × effective_uf |
| components | 建筑屋顶水平足迹 | module_area = area × usable_fraction × packing_fraction × surface_multiplier |
| module_area | 已确定的组件表面面积 | module_area = area，不再施加面积系数 |

`effective_uf`必须非负；因可能含坡面投影换算，不机械限制小于1，使用者必须核实依据。不得同时填写分项系数。

分项模式：usable_fraction和packing_fraction均在[0,1]，surface_multiplier大于0。它们分别表达可用比例、组件排布占比与坡面面积换算；各自定义必须互不重叠。全参数必须显式输入，无隐藏默认系数。

`capacity_kwp = module_area_m2 × capacity_density_kwp_m2`。

## 年比产额模式

每个年比产额组：`mode="annual"`、非负 `kwh_per_kwp`、`included_effects`字符串列表、`source`来源说明。输入应为已经核验的全年交流电量/直流装机容量，单位kWh/kWp/a；这里不再次建模温度或逆变器。

常用效应ID：`orientation`、`shading`、`temperature`、`inverter`、`system_losses`、`aoi`。允许用户定义其他ID，但同一物理效应应使用同一个ID。

`generation_kwh = capacity_kwp × kwh_per_kwp × 外部年度修正系数连乘`。

## PVGIS TMY模式

`mode="pvgis_tmy"`时，`location`、`system`和`time`与本地气象模式相同，另需显式给出 `pvgis` 对象。见 `examples/pvgis-tmy.json`。

只算每kWp年比产额时，用 `examples/pvgis-yield.json` 的简化配置执行 `yield`。它只需要 `schema_version`、`mode`、`source`、`location`、`system`、`time`、`pvgis`，不读取建筑表。需要逐栋总量时再改用完整配置执行 `run`。本地气象也可通过简化配置运行 `yield`，将 `pvgis` 换为 `weather_csv`，`mode`改为`weather`。

| 参数 | 含义 |
|---|---|
| api_url | 明确指定带版本的PVGIS HTTPS API入口，末尾带/ |
| start_year / end_year | 用于挑选TMY月份的年份范围，至少相差10年 |
| use_horizon | 是否让PVGIS计算地形地平线影响 |
| user_horizon_deg | null或从正北顺时针等间隔的地平线仰角数组 |
| expected_radiation_database | 预期服务返回的数据库名称；null表示接受实际选择但仍记录它 |
| timeout_seconds | API请求超时时间，1—300秒 |
| cache_csv / cache_metadata_json | 读取或保存气象序列与来源记录的路径 |
| cache_policy | cache_only、fetch_if_missing或refresh |
| roll_utc_offset_hours | 当前仅支持明确填写0 |
| output_format | 当前仅支持明确填写json |

TMY返回的是合成典型年，`time`需明确为非闰参考年、60分钟、UTC及start时间标签。当前入口只接受PVGIS报告辐照时间偏移为0.5小时的数据；程序在时段中心计算太阳位置。更复杂的时间语义应先整理为本地气象输入。

接口支持的参数及本程序实际使用范围见 [PVGIS与气象说明](weather.md)。配置中既没有列出、也没有在本模式实现的PVGIS功能不会被暗中采用。

## 外部修正

`corrections`为列表，每项包含唯一 `effect`、`source`，以及 `value` 或 `column`二选一。value为统一常量；column为建筑表实际列名，对每栋读取。值必须位于[0,1]，含义为电量保留比例（0.9表示保留90%，不是损失90%）。

任一比产额声明已含某effect时，配置中不得再次外乘该effect，即使值等于1也应删除冗余修正项。列表为空代表没有额外修正。此检查基于声明，不替代实际计算链溯源。混合“已经含遮挡”与“尚未含遮挡”的比产额时，应先统一口径，或分别运行。

## 范围与碳

`scope_labels`映射范围键到人类可读说明；主评价、储备及其他范围独立汇总，不自动生成混合“总潜力”。空范围保留零结果。

可省略carbon整项；启用时必须填写 `kg_co2_per_kwh`、整数 `factor_year`、`source`。计算 `operational_avoided_co2_kg = generation_kwh × kg_co2_per_kwh`。年份写入结果，不被解释为与所有其他输入同年。该结果不包括组件制造等生命周期排放，也不判断实际电力替代。

## 配置路径与复现

输入路径相对于JSON配置目录，支持绝对路径。输出由CLI明确指定。每次运行生成配置快照、输入与代码校验值；对输入在运行期间改变的情况报错。支持不同屋面、气象节点与分区，但不自动进行GIS空间匹配，ID与类别映射必须先完成。
