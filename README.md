# 杭州路网覆盖率计算

计算杭州路网的道路覆盖率和覆盖密度，基于 OSM 路网和 GPS 轨迹数据。

## 环境要求

- Python 3.11+
- 轨迹数据 CSV 文件 (5 列无 header: device_id, lon, lat, speed, timestamp_ms)
- 网络连接（首次运行需下载 OSM 路网）

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

# 强制重新下载路网
python main.py --force
```

## 输出

- `output/roads_coverage.parquet` — 每条道路的覆盖率和密度
  - `osm_way_id` — OSM 路段 ID
  - `road_name` — 道路名称
  - `road_length` — 路段长度 (米)
  - `coverage_ratio` — 覆盖率 (0~1)
  - `pass_count` — 通行 trip 数
  - `highway_type` — 道路等级
  - `geometry` — WKT 格式的 LineString

- `output/coverage_map.html` — folium 覆盖率地图
  - 图层 1: 覆盖率着色 (绿>80% · 黄40-80% · 红<40%)
  - 图层 2: 密度线宽映射

- `output/trajectory_map.html` — 设备轨迹地图
  - 每条设备轨迹渲染为折线，起终点标记

## 运行流程

```
[1/7] 下载杭州 OSM 路网 (osmnx)
[2/7] 构建 HMM 匹配图 (bulk 写入 + 空间索引)
[3/7] CSV 加载 → Parquet + GCJ-02 → WGS-84 坐标转换
[4/7] 轨迹预处理 + 并行地图匹配 (降噪 → trip切分 → DP抽稀 → HMM匹配)
[5/7] 计算覆盖率 & 密度统计
[6/7] 生成 folium 覆盖率地图
[7/7] 生成设备轨迹可视化
```

## 测试

```bash
pytest tests/ -v
```

## 配置说明

见 `config.yaml`，主要参数：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `trajectory.csv_path` | 轨迹 CSV 文件路径 | data/csv/pos/pos.csv |
| `trajectory.coord_system` | 轨迹坐标系 (见 --coord 选项) | wgs84 |
| `road_network.highway_types` | 保留的道路类型 | motorway ~ residential |
| `preprocess.min_speed_ms` | 静止判定 (m/s) | 0.5 |
| `preprocess.max_jump_m` | 漂移判定距离 (m) | 500 |
| `preprocess.trip_gap_minutes` | Trip 切分间隔 (分钟) | 5 |
| `preprocess.dp_epsilon_m` | DP 抽稀精度 (米) | 10 |
| `matching.observation_sigma` | HMM 观测噪声 (m) | 25 |
| `matching.candidate_radius` | 候选路段搜索半径 (m) | 30 |
| `matching.max_workers` | 并行进程数 | 8 |
| `matching.device_chunk_size` | 每批设备数 | 200 |
| `stats.segment_length_m` | 覆盖率分段长度 (米) | 50 |
