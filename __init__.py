"""Filter-sama —— 出站消息过滤器。

MaiBot 通过本包的 plugin.py 中的 create_plugin() 工厂函数加载插件。
"""

from .plugin import FilterSamaPlugin, create_plugin

__all__ = ["FilterSamaPlugin", "create_plugin"]
