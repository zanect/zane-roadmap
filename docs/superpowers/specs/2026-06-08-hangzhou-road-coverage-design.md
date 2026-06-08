# 杭州路网覆盖率计算 — 设计文档

**日期：** 2026-06-08
**语言：** Python
**数据规模：** 10 万台设备，单日快照（~5000万 GPS 点）

---

## 1. 目标

对杭州路网计算两个核心指标：

| 指标 | 定义 | 计算方式 |
|------|------|---------|
| **覆盖率 (Coverage Ratio)** | 每条道路是否整条都有设备经过 | 50m 分段：有匹配 trip 经过的子段数 / 总子段数 |
| **覆盖密度 (Pass Count)** | 每条道路一天被经过的次数 | 匹配到该路段的 trip 总数 |

---

## 2. 输入数据

### 2.1 路网数据

- **来源：** OpenStreetMap，通过 `osmnx` 按杭州行政区划边界下载
- **过滤：** 只保留可通行机动车道路 (`motorway`, `trunk`, `primary`, `secondary`, `tertiary`, `residential`，排除 `footway`, `path`, `cycleway`)
- **唯一标识：** OSM `way_id`
- **坐标系：** WGS-84
- **规模估算：** 杭州路网约 5~8 万条路段

### 2.2 轨迹数据

- **存储：** CSV 文件 (无 header)
- **字段：** `device_id`, `lon`, `lat`, `speed`, `timestamp_ms`
- **坐标系：** WGS-84 或 GCJ-02（可配置，GCJ-02 时自动转换为 WGS-84）
- **规模：** 10 万台设备 × ~500 点/台 ≈ **5000 万行/天**
- **加载方式：** DuckDB 流式 COPY CSV → Parquet 中间文件（~25 秒/13GB）

---

## 3. 技术方案

### 3.1 整体架构

```
CSV 文件 (原始GPS, WGS-84 或 GCJ-02)
        ↓ DuckDB COPY → Parquet + 坐标转换 → WGS-84
   Parquet (轨迹中间文件)
        ↓ 降噪 + trip切分 + DP抽稀
   trips (压缩后的trip线段, 内存)
        ↓ leuvenmapmatching HMM匹配
   Parquet (matched_trips - trip→way_id映射)
        ↓ 分段统计聚合
   Parquet (roads_coverage - 最终结果)
        ↓ folium 可视化
   coverage_map.html  +  trajectory_map.html
```

OSM 路网 (osmnx) → NetworkX Graph → 构建匹配图 (SqliteMap) → 输入到 HMM 匹配器

### 3.2 Phase 1: 数据获取

**路网 (road_network.py)：**
1. 用 `osmnx.geocode_to_gdf("杭州市, China")` 获取行政边界
2. 用 `osmnx.graph_from_polygon()` 下载路网图
3. 过滤道路类型，导出为 NetworkX MultiDiGraph
4. 构建 `way_id → (node_list, geometry)` 映射表
5. 支持多 Overpass 端点镜像自动切换
6. 首次下载后 pickle 缓存到 `data/`，后续秒级加载

**轨迹 (trajectory.py)：**
1. DuckDB `read_csv` + `COPY` 一键将 CSV 转为 Parquet (ZSTD 压缩)
2. 自动过滤无效行 (null device_id、坐标越界)
3. 按需 GCJ-02 → WGS-84 坐标转换 (分块处理，支持大文件)

### 3.3 Phase 2: 轨迹预处理

**对每台设备独立执行（clean.py）：**

1. **降噪：**
   - 剔除 `speed < 0.5 m/s` 且相邻点间距 `< 5m` 的静止点
   - 剔除距离前后点均超过 500m 的孤立漂移点
   - 可选：卡尔曼滤波平滑坐标

2. **Trip 切分：**
   - 相邻点时间间隔 > 5 分钟 → 新的 trip
   - `trip_id = "{device_id}_{trip_seq}"`
   - 每个 trip 代表一次独立的出行

3. **Douglas-Peucker 抽稀：**
   - 参数 ε = 10m
   - 将 trip 点序列压缩为折线，保留转弯关键点
   - 输出简洁的 LineString，作为 HMM 的观测序列

**效果：** 5000 万点 → ~500 万 trip 线段，匹配量降低 ~90%

### 3.4 Phase 3: 地图匹配

**匹配图构建 (graph.py)：**
- 将 OSM NetworkX Graph 转换为 `leuvenmapmatching` 的 SqliteMap
- 使用 bulk API (`add_nodes`/`add_edges`) 批量写入，避免逐条 SQLite COMMIT
- 对曲线路段自动插入中间节点，提高匹配精度
- 82k 节点 + 138k 边从 ~10 分钟降至 ~10 秒
- 首次构建后缓存为 `.db` 文件，后续直接加载

**HMM 匹配 (hmm_matcher.py)：**
- 库：`leuvenmapmatching`
- 观测概率：GPS 点与候选路段的几何距离，σ = 25m
- 转移概率：相邻两点间的路径合理性（最短路径长度 vs 直线距离）
- Viterbi 解码：求解全局最优路段序列
- 输出：`(trip_id, osm_way_id, node_u, node_v)` 列表

**并行调度 (parallel.py)：**
- 按设备批次流式读取，不将全量数据加载到内存
- 设备数 ≤ 50 时使用单进程模式（便于调试日志）
- 设备数 > 50 时使用 `ProcessPoolExecutor` 多进程并行
- `tqdm` 实时进度展示设备完成数和匹配 trip 数

### 3.5 Phase 4: 统计计算

**覆盖率计算 (coverage.py)：**

1. 将每条 OSM 路段按 50m 等距切割为子段
2. 对每个子段，检查是否有匹配 trip 的投影点落在该子段内
3. `coverage_ratio = 有匹配的子段数 / 总子段数`

**密度计算：**

- `pass_count = COUNT(DISTINCT trip_id)` → 按 `osm_way_id` 分组 (pandas groupby)
- 一个 trip 经过同一路段多次 → 只算 1 次（自然去重）

**最终输出 Schema (`roads_coverage.parquet`)：**

| 列名 | 类型 | 说明 |
|------|------|------|
| `osm_way_id` | str | OSM 路段唯一 ID |
| `road_name` | str | 道路名称 (OSM tags) |
| `road_length` | float | 路段总长度 (m) |
| `coverage_ratio` | float | 覆盖率 0.0 ~ 1.0 |
| `pass_count` | int | 通行 trip 数 |
| `highway_type` | str | 道路等级 (motorway/primary/...) |
| `geometry` | WKT | 路段几何 (LineString) |

### 3.6 Phase 5: 可视化

**覆盖率地图 (map.py)：** `folium` 双图层：
| 图层 | 内容 | 视觉编码 |
|------|------|---------|
| 覆盖率 Choropleth | 每路段按覆盖率着色 | 🟢 >80% · 🟡 40-80% · 🔴 <40% |
| 密度 Heatmap | 每路段按通行次数 | 线宽/颜色深浅映射 |
| 综合叠加 | 两图层可切换 | `folium.LayerControl` |

**轨迹地图 (trajectory_map.py)：** `folium` 设备轨迹可视化：
- 每条设备轨迹渲染为折线
- 起点蓝色标记、终点红色标记
- 自动适配地图视野范围
- 大数据量自动降采样（每设备最多 5000 点）

**底图：** OpenStreetMap

---

## 4. 项目结构

```
cover/
├── src/
│   ├── data/
│   │   ├── road_network.py          # osmnx 下载路网
│   │   ├── trajectory.py            # CSV → Parquet + 坐标转换
│   │   └── coordinate.py            # GCJ-02 ↔ WGS-84 转换 (内嵌)
│   ├── preprocess/
│   │   └── clean.py                 # 降噪 + trip切分 + DP抽稀
│   ├── matching/
│   │   ├── graph.py                 # OSM → map matching graph
│   │   ├── hmm_matcher.py           # HMM 匹配引擎
│   │   └── parallel.py              # 多进程调度 + 进度
│   ├── stats/
│   │   └── coverage.py              # 覆盖率 + 密度聚合
│   └── viz/
│       ├── map.py                   # folium 覆盖率地图
│       └── trajectory_map.py        # folium 轨迹可视化
├── scripts/
│   └── export_geojson.py            # 路网导出 GeoJSON
├── data/                            # 中间数据 (gitignore)
├── output/                          # 最终输出
│   ├── roads_coverage.parquet
│   ├── coverage_map.html
│   └── trajectory_map.html
├── main.py                          # 主入口脚本
├── config.yaml                      # 配置
└── requirements.txt
```

---

## 5. 配置设计 (config.yaml)

```yaml
# 目标日期
date: "2026-06-08"

# CSV 轨迹数据文件路径
trajectory:
  csv_path: "data/csv/pos/pos.csv"

# 路网
road_network:
  city: "杭州市"
  # overpass_endpoint: "https://overpass.kumi.systems/api/interpreter"  # 国内网络如官方不通可取消注释
  highway_types:
    - motorway
    - trunk
    - primary
    - secondary
    - tertiary
    - residential

# 预处理参数
preprocess:
  min_speed_ms: 0.5       # 静止判定 (m/s)
  max_jump_m: 500          # 漂移判定 (m)
  trip_gap_minutes: 5      # trip 切分间隔
  dp_epsilon_m: 10         # 抽稀精度 (m)

# 地图匹配参数
matching:
  observation_sigma: 25    # 观测噪声 (m)
  candidate_radius: 30     # 候选路段搜索半径 (m)
  max_workers: 8           # 并行进程数
  device_chunk_size: 200   # 每批次设备数

# 统计
stats:
  segment_length_m: 50     # 覆盖率分段长度 (m)

# 输出
output:
  dir: "output"
  parquet: "roads_coverage.parquet"
  map: "coverage_map.html"
```

---

## 6. 核心依赖 & 兼容性评估

### 6.1 版本锁定清单

| Package | 锁定版本 | 发布时间 | Python | 状态 |
|---------|---------|---------|--------|------|
| `osmnx` | **2.1.0** | 2026-02 | ≥3.9 | ✅ 活跃 |
| `leuvenmapmatching` | **1.1.4** | 2022-12 | ≥3.8 | ⚠️ 纯Python，兼容 numpy 2.x |
| `duckdb` | **1.5.3** | 2026-05 | ≥3.8 | ✅ 最活跃 |
| `shapely` | **2.1.2** | 2025-09 | ≥3.9 | ✅ 最新稳定 |
| `geopandas` | **1.1.3** | 2026-03 | ≥3.9 | ✅ 活跃 |
| `folium` | **0.20.0** | 2025-06 | ≥3.8 | ✅ 稳定 |
| `numpy` | **2.4.6** | 2026-05 | ≥3.10 | ✅ 最新 |
| `scipy` | **1.17.1** | 2026-02 | ≥3.10 | ✅ 最新 |
| `tqdm` | **4.68.1** | 2026-06 | ≥3.8 | ✅ 活跃 |
| `pyyaml` | **6.0.3** | 2025-09 | ≥3.8 | ✅ 稳定 |

### 6.2 兼容性分析

**Python 版本基准：** 3.11+ (推荐 3.12)

- `numpy 2.4.6` + `shapely 2.1.2`：✅ shapely 2.x 全面支持 numpy 2.x
- `numpy 2.4.6` + `leuvenmapmatching 1.1.4`：✅ 纯 Python 库，仅用 scipy 基础算法，不涉及 numpy C API，兼容无问题
- `geopandas 1.1.3` + `shapely 2.1.2`：✅ geopandas 1.x 原生依赖 shapely ≥2.0
- `osmnx 2.1.0` + `geopandas 1.1.3`：✅ osmnx 2.x 适配最新 geopandas

### 6.3 coord-convert 替代方案

`coord-convert` 最新版本 0.2.1 (2019-09) 已 7 年未更新。**不建议作为外部依赖**，改为内嵌转换函数：

```python
# GCJ-02 → WGS-84 转换 (数学公式，稳定不变)
# 来源: https://github.com/wandergis/coordTransform_py
import math

def gcj02_to_wgs84(lng, lat):
    """
    火星坐标系 (GCJ-02) 转 WGS-84
    精度: < 10m (中国境内)
    """
    PI = math.pi
    a = 6378245.0  # 长半轴
    ee = 0.00669342162296594323  # 偏心率平方

    def _transform_lat(x, y):
        ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
        ret += (20.0 * math.sin(y * PI) + 40.0 * math.sin(y / 3.0 * PI)) * 2.0 / 3.0
        ret += (160.0 * math.sin(y / 12.0 * PI) + 320.0 * math.sin(y * PI / 30.0)) * 2.0 / 3.0
        return ret

    def _transform_lng(x, y):
        ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
        ret += (20.0 * math.sin(x * PI) + 40.0 * math.sin(x / 3.0 * PI)) * 2.0 / 3.0
        ret += (150.0 * math.sin(x / 12.0 * PI) + 300.0 * math.sin(x / 30.0 * PI)) * 2.0 / 3.0
        return ret

    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * PI
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * PI)
    dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * PI)
    return lng - dlng, lat - dlat
```

放入 `src/data/coordinate.py`，零外部依赖。GCJ→WGS 采用迭代逼近，精度 < 1m。

### 6.4 requirements.txt

```
osmnx==2.1.0
leuvenmapmatching==1.1.4
duckdb==1.5.3
shapely==2.1.2
geopandas==1.1.3
folium==0.20.0
numpy==2.4.6
scipy==1.17.1
tqdm==4.68.1
pyyaml==6.0.3
pytest==8.4.2
```

---

## 7. 执行流程 (main.py)

```python
def main():
    config = load_config("config.yaml")

    # Step 1: 获取路网 (首次下载 OSM，后续从 pickle 缓存加载)
    G, way_map = load_road_network(config, force_download=args.force)

    # Step 2: 构建 HMM 匹配图 (bulk 写入 SqliteMap，首次 ~10s，后续直接加载 .db)
    mmap = build_matching_map(G, mmap_db_path)

    # Step 3: CSV → Parquet + 坐标转换 (DuckDB COPY，GCJ-02 → WGS-84)
    raw_path = load_csv_to_parquet(Path(csv_path))
    wgs84_path = convert_coordinates(raw_path)  # 若已是 WGS-84 则跳过

    # Step 4: 轨迹预处理 + 并行地图匹配 (降噪 → trip切分 → DP抽稀 → HMM)
    matched_df = run_map_matching(wgs84_path, mmap_db_path, config)

    # Step 5: 统计聚合 (50m 分段覆盖率 + 密度)
    coverage_df = compute_coverage(matched_df, way_map, segment_length_m=50)
    save_results(coverage_df, parquet_path)

    # Step 6: 覆盖率地图 (folium 双图层)
    render_map(parquet_path, map_path)

    # Step 7: 轨迹地图 (设备轨迹折线可视化)
    render_trajectory_map(wgs84_path, traj_map_path)
```

---

## 8. 约束与边界

- **不纳入范围：** 实时查询、增量更新、多日趋势分析（当前只做单日）
- **精度预期：** HMM 匹配对大部分城市道路准确率 >85%；立交桥、隧道、密集平行道路可能有误匹配
- **运行环境：** 单机多核，不依赖 GPU 或分布式集群
- **坐标系：** 内部统一使用 WGS-84，CSV 加载阶段按需做 GCJ-02 → WGS-84 转换

---

## 9. 已知性能瓶颈

| # | 位置 | 原因 | 影响 | 状态 |
|---|------|------|------|------|
| 1 | HMM 地图匹配 (Viterbi) | O(T×K²)，T=观测点数，K=每点候选路段数。对大规模路网 + 长 trip 慢 | 单设备可能数分钟 | 待优化 |
| 2 | folium 渲染 | 8 万条 PolyLine 生成 HTML，可能几百 MB | ~30-60s | 待优化 |
| 3 | CSV→Parquet 大文件 | 13 GB CSV 内存峰值 ~2GB (DuckDB COPY) | 需 16GB+ RAM | ✅ 已优化 (流式 COPY) |
