# API 说明

所有公开类型都可从 `eventgraph` 导入。

## Event 与 Result

```python
Event(
    id: str,
    roles: tuple[str, ...],
    flow: Flow,
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
    *, events=(), results=(), connections=(), flow_updates=None
) -> MutationReport

graph.replace_result(
    old_result, new_result, *, connections=(), flow_updates=None
) -> MutationReport
```

`flow_updates` 是 `{事件 ID: 新 Flow 对象}`，不自动推导更新。`append` 不删除已有定义；替换必须使用 `replace_result`。已有事件输入连接或输出集合变化，必须提供更新；允许显式传回同一个 Flow 对象以确认它仍适用。

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
| `MissingFlowUpdate` | 输入/输出接口改变但未明确更新流程；继承 ValidationError |
| `NotEnabled` | 时间、地点或触发条件不满足 |
| `UndefinedInput` | 实际相关项组合不在流程覆盖域中 |
