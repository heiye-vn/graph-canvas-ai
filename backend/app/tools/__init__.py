"""工具包。

导入本包即注册内置工具 —— 这样任何 `from app.tools.xxx import ...`
都能保证注册表是非空的。否则「谁先 import 谁负责注册」这种约定迟早会漏，
表现是 `/api/tools` 偶发返回空列表，而且只在特定启动路径下复现。
"""

from app.tools import (
    builtins,  # noqa: F401  导入即注册
    enhance,  # noqa: F401  M11 去背景 / 换背景 / 扩图 / 超分（排队型工具）
    region,  # noqa: F401  M6 局部编辑（排队型工具）
)
from app.tools import (
    split as split_tools,  # noqa: F401  M7 拆层（排队型工具）
)
