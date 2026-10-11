# API 说明

所有公开类型都可从 `eventgraph` 导入。

## Event 与 Result

```python
Event(
    id: str,
    roles: tuple[str, ...],
    content: object,
    time: TimeWindow = TimeWindow(),
    locations: frozenset[str] = frozenset(),
    description: str = "",
)

Result(
    id: str,
    event_id: str,
    recipient_roles: tuple[str, ...] = (),
    description: str = "",
)
```

定义为冻结数据类。ID 必须是非空字符串；结果 ID 在一个图的生命周期中不能重用。`recipient_roles` 必须属于结果所属事件的角色集合。

`Event.content` 替代原 `flow` 属性，类型为 `object`。内容对象必须公开 `description: str`，用一句非空、单行文字描述内容；不要求继承指定类。`Event.description` 仍是事件名称/说明，`content.description` 是内容摘要，需要渲染内容时只读取后者，不判断内容类型。当前悬停仍只显示节点名称，不显示内容摘要，也未新增描述面板。

可使用 `NodeContent(description, data=None)` 保存通用内容；也可以使用自己的类。基础 `Event` 不解释内容，直接执行会抛出 `UndefinedInput`。事件派生类通过 `validate_content(related_ids, output_ids)` 校验内容，通过 `resolve(inputs)` 产生结果。已有流程改用 `FlowEvent(..., content=TableFlow(...))`，它将这两个方法转交给内容中的 `Flow`。

```python
from dataclasses import dataclass
from eventgraph import Event, NodeContent, FlowEvent, TableFlow

@dataclass(frozen=True)
class DialogueContent:
    description: str
    lines: tuple[str, ...]

node = Event("greeting", ("speaker",),
             DialogueContent("角色向来访者问好。", ("你好！",)))
flow_node = FlowEvent("study", ("student",),
                      TableFlow(default={"knowledge"}, description="通过学习获得知识。"))
```

内容只受浅层冻结保护；插入图后应视为不可变对象。自定义校验不得修改内容、图或外部状态；事务无法回滚调用者对象的任意副作用。

`TimeWindow(start=None, end=None)` 使用闭区间，无界端点为 `None`。数值必须有限，起点不能晚于终点。没有内置日历或时区换算，整个月份、天、秒等单位由应用统一决定。

## Connection

```python
Connection(
    source_result: str,
    target_event: str,
    kind: InputKind,  # InputKind.TRIGGER / InputKind.RELATED
    target_role: str | None = None,
)
```

也接受 `"trigger"`、`"related"` 字符串。指定目标角色时，匹配该角色绑定人物的历史；未指定时，匹配任一参与者的个人结果或世界级结果。

## EventGraph

```python
graph.append(
    *, events=(), results=(), connections=(), content_updates=None
) -> MutationReport

graph.replace_result(
    old_result, new_result, *, connections=(), content_updates=None
) -> MutationReport
```

`content_updates` 是 `{事件 ID: 新内容对象}`，不自动推导更新。`append` 不删除已有定义；替换必须使用 `replace_result`。已有事件输入连接或输出集合变化，必须提供更新；允许显式传回同一个内容对象以确认它仍适用。

更新使用 `dataclasses.replace`，保留事件派生类型。旧 `flow_updates` 参数仍是兼容别名，但不能与 `content_updates` 同时传入。`Event(..., flow=...)` 和 `.flow` 已移除，Python 调用者需迁移到 `content` 与对应派生类。

`MutationReport` 包括：`revision`、`added_events`、`added_results`、`removed_results`、`updated_events`。新事件列在 `added_events`，不重复列在 `updated_events`。

只读接口：

```python
graph.events                 # 事件 ID → Event，只读映射
graph.results                # 结果 ID → Result，只读映射
graph.connections            # 所有连接的 tuple
graph.revision               # 最近一次成功提交的修订号
graph.schema(event_id)        # EventSchema
graph.consumers(result_id)    # 此结果的所有出边
```

一次更新前获取的只读映射仍指向当时的定义快照；要获取最新状态，应再次访问属性。

更新还会检查必需触发依赖及严格分离窗口产生的时间先后约束；出现自依赖、间接环或时间冲突时抛出 `ValidationError`，不提交更新。`related` 不产生固定顺序，双向相关项合法。

运行接口：

```python
graph.inputs_for(
    event_id, history, *, participants, time, location
) -> frozenset[str]

graph.is_enabled(
    event_id, history, *, participants, time, location
) -> bool

graph.execute(
    event_id, history, *, participants, time, location, execution_id=None
) -> Execution
```

`participants` 是角色名称到人物 ID 的映射，必须绑定且只绑定该事件的角色。`is_enabled` 仅把 `NotEnabled` 转换成 `False`，无效 ID 或错误角色仍会报错。它不提前运行流程，也不保证自定义流程能够处理该输入。

`execute` 在校验后调用流程；未指定执行 ID 时使用 UUID。重复执行 ID 被拒绝，不会重放或静默忽略。未通过检查不会追加历史记录。

## Flow 与 TableFlow

```python
class MyFlow(Flow):
    def validate(self, related_ids, output_ids):
        # 校验本流程引用的相关结果与输出是否属于事件接口。
        # 不得修改外部状态；可以抛出 ValidationError。
        ...

    def resolve(self, inputs):
        # inputs 是实际出现的相关结果 ID 的 frozenset。
        # 返回本次联合输出的 frozenset。
        ...
```

`resolve` 是抽象方法；`validate` 默认不做检查，自定义实现应覆盖它。库无法对任意 Python 过程证明输入全覆盖或结果分支互斥，但每次执行仍会检查实际输出是否属于当前事件。

```python
TableFlow(cases=None, *, default=None, input_domain=None)
```

- `cases`：`{frozenset(相关项组合): 结果 ID 集合}`。
- `default=None`：没有兜底；`default=set()` 表示兜底输出为空集合。
- `input_domain=None`：输入域为所有相关项组合。指定时只允许给定组合，即使有默认分支也不会接受域外输入。
- 所有表项必须属于相关项/输出接口。没有默认分支时必须完整覆盖输入域。
- 精确匹配表项优先于默认分支。

## History 与执行记录

```python
history = History()
history.executions        # 不可修改的 Execution 元组
history.for_actor(id)     # 此人物实际得到的 ResultRecord 元组
history.experiences(id)   # 此人物参与过的 Execution 元组
```

`Execution` 包含 `id`、`event_id`、`graph_revision`、`time`、`location`、`participants`、`inputs` 和 `results`。参与但未收到结果的人，仍能在 `experiences` 中找到本次事件。

`ResultRecord.definition` 是结果定义快照；`result_id` 为快捷属性；`recipients` 是人物 ID 的冻结集合。世界级结果保存在执行记录中，不自动复制给每个人。

## 异常

| 异常 | 用途 |
| --- | --- |
| `EventGraphError` | 所有库异常的共同基类 |
| `ValidationError` | 无效定义、引用、流程输出或运行参数 |
| `MissingContentUpdate` | 输入/输出接口改变但未明确更新内容；继承 ValidationError，`MissingFlowUpdate` 为兼容别名 |
| `NotEnabled` | 时间、地点或触发条件不满足 |
| `UndefinedInput` | 实际相关项组合不在流程覆盖域中 |

## JSON 与三维布局

以下接口也可从 `eventgraph` 直接导入：

```python
loads_graph(text: str) -> EventGraph
graph_from_dict(data: dict) -> EventGraph
dumps_graph(graph: EventGraph) -> str
graph_to_dict(graph: EventGraph) -> dict
analyze_graph(graph: EventGraph) -> Relations
layout_graph(graph, *, node_spacing=3.0, layer_spacing=5.0,
             sweeps=6, previous=None) -> Layout
```

`Relations` 提供只读 `ranks` 与完整业务 `links`。`Layout.positions` 是事件 ID 到 `Position(x, y, z, rank)` 的只读映射，`Layout.to_dict()` 返回几何快照。`UnconfiguredFlow` 用于没有执行规则的可编辑定义，执行时抛出 `UndefinedInput`。

格式、约束、布局参数、稳定更新和导出边界见 [JSON 解析与三维布局](json-layout.md)。
