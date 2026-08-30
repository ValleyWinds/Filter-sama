# Copyright (C) 2026 ValleyWinds
# SPDX-License-Identifier: GPL-3.0
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Filter-sama —— 出站消息过滤器。

MaiBot 通过本包的 plugin.py 中的 create_plugin() 工厂函数加载插件。
"""

from .plugin import FilterSamaPlugin, create_plugin

__all__ = ["FilterSamaPlugin", "create_plugin"]
