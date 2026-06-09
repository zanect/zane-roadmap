"""
日志管理：将所有 stdout/stderr 输出重定向到日志文件，确保运行结果可追溯。

Usage:
    from src.utils.logger import setup_logging
    log_path = setup_logging("logs", verbose=False)
"""
import sys
import logging
from pathlib import Path
from datetime import datetime


class _TeeWriter:
    """同时写入多个文件对象的 Writer，实现类文件接口兼容 tqdm。"""

    def __init__(self, *files):
        self._files = files

    def write(self, message):
        for f in self._files:
            try:
                f.write(message)
            except (OSError, ValueError):
                pass  # 忽略写入失败，避免因日志问题中断流程

    def flush(self):
        for f in self._files:
            try:
                f.flush()
            except (OSError, ValueError):
                pass

    def isatty(self):
        return False  # 告知 tqdm 等库这不是终端，自动降级为文件模式

    def close(self):
        for f in self._files:
            if f not in (sys.__stdout__, sys.__stderr__):
                try:
                    f.close()
                except (OSError, ValueError):
                    pass


def setup_logging(log_dir: str = "logs", verbose: bool = True) -> str:
    """
    初始化日志系统，将所有 print / stdout / stderr 重定向到日志文件。

    Args:
        log_dir: 日志文件输出目录
        verbose: True=同时输出到终端+文件, False=仅写入文件

    Returns:
        日志文件的绝对路径
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"pipeline_{timestamp}.log"

    log_file = open(str(log_path), "w", encoding="utf-8")

    if verbose:
        sys.stdout = _TeeWriter(sys.__stdout__, log_file)  # type: ignore
        sys.stderr = _TeeWriter(sys.__stderr__, log_file)  # type: ignore
    else:
        sys.stdout = _TeeWriter(log_file)  # type: ignore
        sys.stderr = _TeeWriter(log_file)  # type: ignore

    # 配置 Python logging 模块也写入同一文件
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(log_file)],
    )

    # 首条日志：记录启动信息
    print(f"日志文件: {log_path.resolve()}")
    print(f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"命令行: python {' '.join(sys.argv)}")
    print()

    return str(log_path.resolve())
