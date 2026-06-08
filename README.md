# 杭州路网覆盖率计算

计算杭州路网的道路覆盖率和覆盖密度，基于 OSM 路网和 GPS 轨迹数据。

## 环境要求

- Python 3.11+
- 轨迹数据 CSV 文件（从 ClickHouse 导出）
- 网络连接（首次运行需下载 OSM 路网）

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 将轨迹 CSV 放入 data/ 目录

# 3. 编辑 config.yaml，指定 CSV 文件路径

# 4. 运行
python main.py

# 或指定 CSV 文件
python main.py --csv data/trajectory_2026-06-07.csv
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

- `output/coverage_map.html` — folium 交互式地图
  - 图层 1: 覆盖率着色 (绿>80% · 黄40-80% · 红<40%)
  - 图层 2: 密度线宽映射

## 运行流程

```
[1/6] 下载杭州 OSM 路网
[2/6] 构建 HMM 匹配图
[3/6] CSV 加载 + GCJ-02 → WGS-84 坐标转换
[4/6] 并行地图匹配 (降噪 + trip切分 + HMM匹配)
[5/6] 计算覆盖率 & 密度统计
[6/6] 生成 folium 可视化地图
```

## 测试

```bash
pytest tests/ -v
```

## 配置说明

见 `config.yaml`，主要参数：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `trajectory.csv_path` | 轨迹 CSV 文件路径 | data/trajectory_2026-06-07.csv |
| `preprocess.min_speed_ms` | 静止判定 (m/s) | 0.5 |
| `preprocess.trip_gap_minutes` | Trip 切分间隔 (分钟) | 5 |
| `preprocess.dp_epsilon_m` | DP 抽稀精度 (米) | 10 |
| `matching.max_workers` | 并行进程数 | 8 |
| `stats.segment_length_m` | 覆盖率分段长度 (米) | 50 |
