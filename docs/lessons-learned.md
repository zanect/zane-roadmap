# Lessons Learned — 杭州路网覆盖率项目

开发过程中反复出现的问题及解决方案，供后续维护参考。

---

## 1. 大文件内存溢出 (OOM)

**表现**：pandas `read_csv` 直接加载 10GB+ 轨迹 CSV，内存爆炸。

**解决**：
- 用 DuckDB `COPY` 流式转 Parquet，之后全程用 Parquet + 列裁剪
- `match_device_batch` 按设备 ID 批次查询，不加载全量数据
- 轨迹可视化只读 `lon, lat` 两列

---

## 2. GCJ-02 / WGS-84 坐标系混淆

**表现**：`no_start_edge` 失败率高达 45%，GPS 点距最近 OSM 道路 400-1300m。

**根因**：国内 GPS 数据标称 WGS-84 但实际可能是 GCJ-02（偏移 300-500m）。

**解决**：
- `max_dist_init=900` 大半径覆盖偏移
- 自适应起点裁剪 `_find_first_matchable`：跳过 trip 前段不在路网内的点
- 后续如有准确坐标系元数据，应在 Step 3 调用 `gcj02_to_wgs84` 转换

---

## 3. leuvenmapmatching 库遗留 debug 日志

**表现**：终端 / 日志文件无限刷 `edges_closeto((30.172, 120.226))`，6446 设备产生数百万行。

**根因**：`leuvenmapmatching/map/sqlite.py:490` 有一行裸 `print(f"edges_closeto({loc})")`。

**解决**：直接编辑库文件删除该行。注意 pip 更新库后会恢复，需重新 patch。

---

## 4. `do_stop` 校验距离 ≠ 搜索半径

**表现**：`max_dist=150` 时，即使 `max_dist_init=900` 找到了候选边，起始点仍然被拒绝。

**根因**：leuvenmapmatching 的 `do_stop()` 用 `max_dist`（不是 `max_dist_init`）校验所有候选（包括起始点）。`max_dist_init` 只控制搜索范围，不控制验证。

**教训**：`max_dist` 不能太小，需覆盖典型 GPS 误差。最终取值 450m。

---

## 5. 文档与代码不同步

**表现**：README 写"绿>80% · 黄40-80% · 红<40%"，实际代码是蓝色渐变。

**解决**：
- 每次改代码后立即检查 README.md 和 CLAUDE.md
- 删除过时的设计文档（`docs/superpowers/`），只保留 README + CLAUDE.md 作为唯一信息源

---

## 6. 大文件被 Git 跟踪

**表现**：push 失败，仓库含 2.1GB 的 CSV/Parquet 历史。

**根因**：`.gitignore` 用了 `data/*.csv`（仅匹配一级），未递归匹配 `data/csv/pos/*.csv`。

**解决**：
- `.gitignore` 用 `data/*` + `!data/.gitkeep` 排除整个目录
- `git filter-repo --path <file> --invert-paths` 清理历史

---

## 7. Windows GBK 终端中文乱码

**表现**：`print("淳安县")` 输出为 `������`。

**解决**：
- 日志文件写入 UTF-8，终端仅输出英文/ASCII
- 中文数据用 `with open(..., encoding='utf-8')` 写文件，通过 Read 工具查看
- 日志模块 `logger.py` 的 `_TeeWriter` 在 verbose 模式下同时写终端和文件

---

## 8. 多进程 SQLite 并发锁

**表现**：`sqlite3.OperationalError: database is locked`。

**根因**：`ProcessPoolExecutor` 多进程共享同一个 `SqliteMap` 连接。

**解决**：
- 每个子进程独立打开 `SqliteMap(path, deserializing=True)`
- `deserializing=True` 防止 `create_db()` 误删已有表

---

## 9. 轨迹可视化文件膨胀

**表现**：`trajectory_map.html` 1.4GB，浏览器无法打开。

**根因**：1 亿 GPS 点逐条 `folium.PolyLine` 渲染，每个点产出一段 HTML/JS。

**解决**：
1. 只读 `lon, lat` 两列（列裁剪）
2. `drop_duplicates` 坐标去重（-57.6%）
3. 均匀采样到 15 万点
4. GeoJSON FeatureCollection + CircleMarker 渲染（比逐条 PolyLine 紧凑 100 倍）
5. 最终文件 17MB

---

## 10. 设计文档腐烂

**表现**：`docs/superpowers/` 中的计划/设计文档描述 5 阶段 pipeline，与完工的 7 步系统严重脱节。

**解决**：删除过时文档。以 README.md（用户视角）和 CLAUDE.md（开发者视角）为唯一文档。

---

## 快速排查清单

遇到问题时按以下顺序排查：

1. **匹配率低** → 检查 `max_dist_init` 是否足够大（≥500m）→ 检查坐标系是否 GCJ-02
2. **日志爆炸** → 检查 `leuvenmapmatching/sqlite.py:490` 是否被 patch
3. **内存溢出** → CSV 是否已转 Parquet → 是否按 device 批次查询
4. **push 失败** → 检查 `data/` `output/` `logs/` `cache/` 是否在 `.gitignore`
5. **中文乱码** → 输出是否经过 UTF-8 文件而非直接 print
6. **DB locked** → 确认子进程使用 `deserializing=True`
