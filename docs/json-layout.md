# JSON 解析与三维布局

已实现 App 的前两项能力：将事件 JSON 转换为经过校验的关系图，再产生可供渲染器使用的三维节点坐标。解析和布局全部使用 Python 标准库；渲染见 [三维查看器](viewer.md)，可视化节点编辑尚未实现。

## 直接使用

在项目根目录执行：

```bash
python3 -m eventgraph examples/events.json -o layout.json
```

`layout.json` 包含 `graph`（规范化的事件定义）和 `layout`（坐标、层级、原始业务连接）。省略 `-o` 时输出到标准输出；源文件与输出文件不能相同。输入非法时退出码为 2，不生成新输出。已有输出文件会被正常的新输出覆盖。

示例包含八个事件、分叉与汇合、学习和实践之间的双向相关项，以及相交和不相交的时间窗口。

Python 接口：

```python
from pathlib import Path
from eventgraph import analyze_graph, dumps_graph, layout_graph, loads_graph

graph = loads_graph(Path("examples/events.json").read_text(encoding="utf-8"))
relations = analyze_graph(graph)
layout = layout_graph(graph)

print(relations.ranks)              # 事件 ID → 先后层级
print(relations.links)              # 全部真实结果连接，保留 trigger / related
print(layout.positions["study"])    # Position(x, y, z, rank)
geometry = layout.to_dict()         # 可直接 JSON 序列化的布局快照
normalized_json = dumps_graph(graph)
```

已有 Python 字典可直接调用 `graph_from_dict(data)`；`graph_to_dict(graph)` 返回规范化字典。导入不会修改输入。导出只保存当前定义，不保存执行历史、历史修订或退休 ID，因此不能把它当成运行中世界的完整存档。

## 事件 JSON 格式

当前导出 version 2，节点内容使用 `content`；仍可导入 version 1 的 `flow` 文件。结构示例：

```json
{
  "version": 2,
  "events": [
    {
      "id": "study",
      "description": "学习",
      "roles": ["student"],
      "locations": ["school"],
      "time": {"start": 0, "end": 10},
      "type": "flow",
      "content": {"description": "通过学习获得知识。", "type": "table", "default": ["knowledge"]}
    },
    {"id": "practice", "roles": ["student"], "time": {"start": 5, "end": 15},
     "content": {"description": "通过实践积累经验。", "data": {"topic": "练习"}}}
  ],
  "results": [
    {"id": "knowledge", "event_id": "study", "recipient_roles": ["student"]},
    {"id": "experience", "event_id": "practice", "recipient_roles": ["student"]}
  ],
  "connections": [
    {"source_result": "knowledge", "target_event": "practice", "kind": "related", "target_role": "student"},
    {"source_result": "experience", "target_event": "study", "kind": "related", "target_role": "student"}
  ]
}
```

| 对象 | 必需字段 | 可选字段与默认值 |
| --- | --- | --- |
| 文档 | `version: 2`、`events` | `results: []`、`connections: []` |
| 事件 | `id`、`content` | `description: ""`、`roles: []`、`locations: []`、`time: {}`、`type: "event"` |
| 通用内容 | 非空单行 `description` | `data: null`，可包含任意 JSON 原生数据 |
| 时间窗口 | 无 | `start`、`end` 缺省或 `null` 表示无界 |
| 结果 | `id`、`event_id` | `description: ""`、`recipient_roles: []` 表示世界级结果 |
| 连接 | `source_result`、`target_event`、`kind` | `target_role: null` |

角色、地点、收件角色均为不重复字符串数组；ID 必须为非空字符串。时间必须为有限数字，窗口包含两端，不表示事件持续时间。字段名采用现有 API 的命名，未知字段视为错误，避免拼写错误被静默忽略。

`type: "event"` 对应基础 `Event`，其内容解析为 `NodeContent(description, data)`；内容只参与展示，直接执行抛出 `UndefinedInput`。`type: "flow"` 对应 `FlowEvent`，内容包含同样的 `description`，以及 `type: "table"` 的组合规则或 `type: "unconfigured"` 的未配置流程。渲染无需区分这些类型，内容摘要的统一接口都是 `content.description`。当前悬停提示保持只显示节点名称，未增加内容描述展示。

旧版 version 1 中的 `flow` 会导入为 `FlowEvent.content`；省略流程的事件导入为基础 `Event`，自动补充“尚未配置节点内容。”摘要。重新导出统一为 version 2。version 2 必须显式提供 `content.description`，不接受旧 `flow` 字段。

Python 内容可以是任何提供 `description` 属性的对象，但内置 JSON 编解码只支持准确类型为 `Event + NodeContent` 和 `FlowEvent + TableFlow/UnconfiguredFlow` 的组合。自定义派生类型或非 JSON 数据必须由应用实现专用编解码，内置导出会明确报错，不静默丢失数据或行为；JSON 不动态加载 Python 类。

组合规则格式：

```json
{
  "description": "根据已有知识决定本次实践的结果。",
  "type": "table",
  "cases": [
    {"inputs": ["knowledge"], "outputs": ["experience"]}
  ],
  "default": [],
  "input_domain": [[], ["knowledge"]]
}
```

`cases` 缺省为空数组；`default` 缺省或 `null` 表示没有默认分支，`[]` 表示默认无输出；`input_domain` 缺省或 `null` 表示没有显式域限制。未配置默认分支时，规则必须覆盖输入域。不同顺序的相同输入集合仍算重复表项。

解析拒绝重复 JSON 键、重复 ID、无效类型、非法引用、未声明的角色或流程结果，以及非有限时间。字段错误尽量带 JSON 路径；跨节点错误指出具体引用或约束环。

## 先后约束与可选影响

排序仅使用两类约束：

1. `trigger`：结果所属事件在目标事件之前。
2. 时间：`A.time.end < B.time.start`，且两端均有界，则 A 在 B 之前。

端点相等或窗口重叠不建立时间顺序。`related` 不参与强制排序，允许双向连接，也允许从高层节点连回低层节点；它可以轻微影响横向布局，让相关节点靠近。

底层 `EventGraph.append` 与 `replace_result` 在提交前检查上述约束的合并图。自触发、间接触发环、触发关系与时间顺序冲突均拒绝，原图与缓存保持不变。可选影响环不拒绝。该校验不证明任意人物的所有事件一定可执行，也不替代实际执行时的角色及历史检查。

时间关系使用按结束时间排序的内部汇总节点表示，不构造所有事件之间的时间边。拓扑排序按最长约束路径计算层级，内部汇总节点不占用视觉层级，也不输出为事件节点。排序结构大小为 `O(V + E)`，构建和确定性排序约为 `O((V + E) log V)`。

`rank(A) < rank(B)` 本身不代表 A、B 存在依赖：它们可能处于两条无关分支。不能根据坐标高度虚构业务连接。返回的 `links` 完整保留真实业务连接；隐含时间顺序体现在层级中，不扩展成密集的可见连线。

## 三维布局与稳定更新

```python
layout = layout_graph(
    graph,
    node_spacing=3.0,
    layer_spacing=5.0,
    sweeps=6,
    previous=None,
)
```

- Y 轴表示先后层级，`y = rank × layer_spacing`，与实际时间单位无关。
- 同层节点在 XZ 平面的六角网格上安放，层间距不得小于节点间距，保证节点中心在三维空间中的最小距离。渲染器应据此选择节点半径；此阶段不保证任意相机角度下的投影或标签不重叠。
- 在约束不变的情况下，以邻居加权中心引导布局，触发连接权重高于相关项；通过有限轮局部调整缩短连接，并保持紧凑。
- ID 决定稳定的处理顺序，不使用随机状态；同一份数据调整数组顺序后，输出仍相同。独立节点允许同层，不强行组成一条链。
- `sweeps` 为 0–100 的整数，控制调整轮数；不是全局最优求解器，尚不承诺最少交叉或最终艺术效果。

编辑 JSON 后，重新解析并传入上一次布局：

```python
updated_graph = loads_graph(edited_json)
updated_layout = layout_graph(updated_graph, previous=layout)
```

节点间距相同时，已有节点保持 XZ 位置，新节点寻找空位。若新约束改变层级，Y 必须更新；多个旧节点移入同层占据同一位置时，保留层级未改变的节点，其他节点就近重新安放。删除的节点不进入新输出。调整节点间距时应省略 `previous` 重新布局。

保留旧布局与无重叠优先于进一步压缩连线。此处是利用旧位置的稳定更新，不是完整的增量关系解析；解析和先后层级仍重新计算。

查看器另调用 `spread_canopy(layout, related_proximity=True)` 展开树冠，并默认优化关联邻近关系。其局部调整以缩短去重关联节点对的三维距离为目标，同时保留触发枝方向和树冠展开程度；每次接受移动都不增加关联总距离。Y 和 rank 固定，六角席位保证最小间距。`related_proximity=False` 可用于对照未优化的树冠；该参数位于 `eventgraph.layout`，不影响通用 `layout_graph` 的默认行为。

布局输出是只读快照，提供 `nodes` 与 `links`，通过事件 ID、结果 ID 和原始 JSON 对应。线条样式、结果端口形状、路径绕行、摄像机与交互属于后续渲染阶段。

## 验证

```bash
python3 -m unittest discover -s tests -v
python3 -m examples.school_world
```

测试覆盖 JSON 往返后的执行语义、非法输入、双向影响、窗口边界、随机图与显式两两时间约束的比较、深层循环、失败事务、分叉汇合、中心间距、确定性和旧布局复用。
