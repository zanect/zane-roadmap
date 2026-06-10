# 杭州路网覆盖率计算

计算杭州路网的道路覆盖率和覆盖密度，基于 OSM 路网和 GPS 轨迹数据。

## 环境要求

- Python 3.11+
- 轨迹数据 CSV 文件 (5 列无 header: device_id, lon, lat, speed, timestamp_ms)
- 网络连接（首次运行需下载 OSM 路网和区县边界）

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 将轨迹 CSV 放入 data/csv/pos/ 目录

# 3. 编辑 config.yaml，指定 CSV 文件路径和坐标系

# 4. 运行 (数据为 WGS-84 时无需坐标转换)
python main.py

# 指定 CSV 文件
python main.py --csv data/csv/pos/pos.csv

# GCJ-02 坐标系需指定转换
python main.py --csv data/csv/pos/pos.csv --coord gcj02

# 强制重新下载路网和区县边界
python main.py --force
```

## 输出

### 覆盖率结果 `output/roads_coverage.parquet`

| 字段 | 类型 | 说明 |
|------|------|------|
| `osm_way_id` | str | OSM 路段 ID |
| `road_name` | str | 道路名称 |
| `road_length` | float | 路段长度 (米) |
| `coverage_ratio` | float | 分段覆盖率 (0~1) |
| `pass_count` | int | 途经 trip 数 |
| `highway_type` | str | 道路等级 |
| `district` | str | 所属区县 |
| `geometry` | str | WKT 格式 LineString |

### 设备-道路映射 `output/device_road_map.parquet`

每行 = 一台设备经过一条路：

| 字段 | 说明 |
|------|------|
| `device_id` | 设备 ID |
| `osm_way_id` | OSM 道路 ID |
| `road_name` | 道路名称 |
| `highway_type` | 道路等级 |
| `road_length` | 长度 (米) |
| `district` | 所属区县 |
| `pass_count` | 该设备经过此路次数 |

### 设备汇总 `output/device_summary.parquet`

| 字段 | 说明 |
|------|------|
| `device_id` | 设备 ID |
| `road_count` | 经过的道路数 |
| `district_count` | 覆盖的区县数 |
| `districts` | 覆盖区县列表 |

### 可视化

- `output/coverage_map.html` — folium 覆盖率地图
  - 图层 1: 全路网背景 (灰色细线)
  - 图层 2: 匹配覆盖路段 (深蓝渐变，深浅对应 pass_count 频次)
  - 图例: 左下角频次色卡
- `output/trajectory_map.html` — 轨迹点散点图 (经过去重+采样，15万点 GeoJSON 渲染)

### 运行日志

- `logs/pipeline_YYYYMMDD_HHMMSS.log` — 完整运行日志（含匹配失败原因分布）

## 运行流程

```
[1/7] 下载杭州 OSM 路网 → 标注区县归属 (osmnx + Nominatim)
[2/7] 构建 HMM 匹配图 (bulk 写入 + 空间索引)
[3/7] CSV 加载 → Parquet + GCJ-02 → WGS-84 坐标转换
[4/7] 轨迹预处理 + 并行地图匹配 (去重 → 降噪 → trip切分 → DP抽稀 → HMM匹配)
[5/7] 计算覆盖率 & 密度统计 (含区县归属)
[6/7] 生成 folium 覆盖率地图
[7/7] 生成轨迹散点图 (去重+采样+GeoJSON点渲染)
```

## 预处理细节

| 步骤 | 方法 | 说明 |
|------|------|------|
| 坐标去重 | `dist < 0.1m` | 剔除传感器卡死/数据重复上报的同坐标点 |
| 降噪 | 速度+跳跃 | 静止点(speed<0.5m/s 且位移<5m) + 漂移点(双侧>500m跳跃) |
| Trip 切分 | 时间间隔 | 相邻点间隔 > 5分钟视为新 trip |
| DP 抽稀 | Douglas-Peucker | 保留拐弯关键点，剔除共线中间点 (5m 精度) |
| 自适应起点裁剪 | `edges_closeto` 扫描 | 跳过 trip 前段不在路网范围内的点（如外市出发） |

## 测试

```bash
pytest tests/ -v
```

## 配置说明

见 `config.yaml`，主要参数：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `trajectory.csv_path` | 轨迹 CSV 文件路径 | — |
| `trajectory.coord_system` | 轨迹坐标系 | wgs84 |
| `road_network.highway_types` | 保留的道路类型 | motorway ~ service |
| `preprocess.min_speed_ms` | 静止判定 (m/s) | 0.5 |
| `preprocess.max_jump_m` | 漂移判定距离 (m) | 500 |
| `preprocess.trip_gap_minutes` | Trip 切分间隔 (分钟) | 5 |
| `preprocess.dp_epsilon_m` | DP 抽稀精度 (米) | 5 |
| `matching.observation_sigma` | HMM 观测噪声 (m) | 30 |
| `matching.dist_noise` | HMM 转移噪声 (m) | 50 |
| `matching.max_dist_init` | 首点搜索半径 (m) | 900 |
| `matching.max_dist` | 后续截断距离 (m) | 450 |
| `matching.max_lattice_width` | 每观测点候选数上限 | 40 |
| `matching.non_emitting_states_maxnb` | 最大非发射步数 | 40 |
| `matching.max_workers` | 并行进程数 | 8 |
| `matching.device_chunk_size` | 每批设备数 | 200 |
| `stats.segment_length_m` | 覆盖率分段长度 (米) | 50 |
| `logging.log_dir` | 日志输出目录 | logs |
| `logging.verbose` | 终端+文件双写 | true |
