# EventGraph World

一个以预定义事件为中心的 Python 基础库。人物携带实际经历，自主选择当前允许发生的事件；事件读取经历中的结果组合，再给多个参与者追加一次共同事件的结果。

事件之间的连接表示数据依赖，不表示人物必须沿着图中的固定路径行动。

## 跨设备继续工作

项目进度与协作决定保存在 [工作上下文](docs/context.md)，可读对话和恢复步骤见 [对话记录](docs/conversations/README.md)。这些文件与根目录 [AGENTS.md](AGENTS.md) 一起提交并推送后，可在另一台设备克隆项目，让新对话读取并继续工作。

三维可视化 App 的已确认需求见 [App 基本要求](docs/app-requirements.md)。已实现 JSON 解析、三维布局和本地交互查看器。使用方法见 [JSON 与布局接口](docs/json-layout.md) 和 [三维查看器](docs/viewer.md)；可视化节点编辑待后续实现。

## 环境与运行

- Python 3.10 或更高版本。
- 运行与测试仅使用 Python 标准库，无第三方运行依赖。
- 以下命令均在仓库根目录执行，无须先安装：

```bash
python3 -m examples.school_world
python3 -m eventgraph examples/events.json -o layout.json
python3 -m unittest discover -s tests -v
```

如需在其他项目导入，可选择在虚拟环境中运行 `python3 -m pip install -e .`；构建依赖由 `pyproject.toml` 声明。

第二条命令输出规范化事件定义、三维节点坐标和完整业务连接，供后续渲染器使用。布局按必需触发依赖及严格分离的时间窗口确定层级，允许双向相关项；事件 JSON 可以暂不提供执行流程。

## 查看三维图谱

```bash
python3 -m eventgraph.viewer examples/branching.json --port 8765
```

在浏览器打开 `http://127.0.0.1:8765`。支持“简约形态 / 拟态”切换：简约使用电蓝实枝与清晰的关联藤蔓，拟态呈现电蓝发光树冠、渐细枝条和树干纹理。支持旋转、缩放、节点聚焦、JSON 导入及布局导出；全部资源在本地，不依赖 CDN。终端按 Ctrl+C 停止服务。导入仅替换浏览器当前视图，不写回原文件。

![简约形态](docs/concepts/viewer-preview.png)

![拟态](docs/concepts/viewer-natural-preview.png)

## 事件的七项属性

节点内容使用 `content: object`，必须提供一句 `description` 供渲染展示。内容的其他结构由派生类决定，渲染不解析；通用内容可使用 `NodeContent`，保留流程执行的节点使用 `FlowEvent`。原 `Event.flow` 已改为 `Event.content`，详细迁移与扩展示例见 [API 说明](docs/api.md)。

| 属性 | 存放位置 | 含义 |
| --- | --- | --- |
| 时间 | `Event.time` | 可触发的世界时间区间，包含两个端点 |
| 地点 | `Event.locations` | 允许地点的集合；空集合表示不限地点 |
| 参与角色 | `Event.roles` | 角色槽位，执行时绑定具体人物 |
| 触发条件 | `graph.schema(id).trigger_conditions` | 必须全部存在的历史结果 |
| 相关项 | `graph.schema(id).related_items` | 内部流程会读取的可选历史结果 |
| 节点内容 | `Event.content` | `object`，必须提供一句 `description`；具体含义由派生类定义 |
| 输出 | `graph.schema(id).outputs` | 该事件可能产生的结果集合 |

触发条件、相关项和输出直接从图中派生，只有一份事实来源，不另存容易失配的副本。触发条件与相关项不相交，但两者对应的结果可以同时存在于人物经历中。

必需触发依赖与窗口先后约束的合并图必须无环，非法更新在提交前拒绝；相关项连接不受此无环要求限制。

## 图结构

```text
事件 A
  输出结果 a1 ── trigger ──> 事件 B 的触发输入
  输出结果 a2 ── related ──> 事件 C 的相关输入
             └─ related ──> 事件 D 的相关输入
```

- `Event`：预定义事件模块。
- `Result`：事件拥有的输出端口，也是全局唯一的结果类型定义。
- `Connection`：从结果端口到目标事件的带类型连接。
- `Flow`：可继承的内部流程抽象基类。
- `TableFlow`：内置的组合查表流程，可用默认分支避免枚举所有组合。
- `History` / `Execution` / `ResultRecord`：实际发生的经历，和定义图分开保存。

## 最小示例

```python
from eventgraph import (
    Connection, FlowEvent, EventGraph, History, InputKind, Result, TableFlow,
)

graph = EventGraph()
graph.append(
    events=[
        FlowEvent("admission", ("candidate",), TableFlow(default={"admitted"})),
        FlowEvent("final", ("student",), TableFlow(default={"high_score"})),
    ],
    results=[
        Result("admitted", "admission", ("candidate",)),
        Result("high_score", "final", ("student",)),
    ],
    connections=[
        Connection("admitted", "final", InputKind.TRIGGER, "student"),
    ],
)

history = History()
graph.execute(
    "admission", history,
    participants={"candidate": "alice"}, time=1, location="school",
)
graph.execute(
    "final", history,
    participants={"student": "alice"}, time=2, location="school",
)
assert {r.result_id for r in history.for_actor("alice")} == {
    "admitted", "high_score",
}
```

没有参加期末考试的人不会得到成绩记录，也不会得到一个“空成绩”占位记录。不同人物通过 `target_role` 匹配各自的经历，Alice 的录取结果不会让 Bob 获得考试资格。

## 增加事件或结果

`append` 接收新事件、新结果、连接以及受影响事件的流程更新。可以把旧结果连接到新事件，也可以把新结果连接到旧事件。

```python
report = graph.append(
    events=[
        FlowEvent("practice", ("learner",), TableFlow(default={"practiced"})),
    ],
    results=[Result("practiced", "practice", ("learner",))],
    connections=[
        Connection("practiced", "final", InputKind.RELATED, "student"),
    ],
    content_updates={
        "final": TableFlow(
            {frozenset({"practiced"}): {"high_score"}},
            default=set(),  # 示例：未练习时本次执行不产生任何结果
        ),
    },
)
assert report.updated_events == frozenset({"final"})
```

当已有事件的输入连接或输出集合改变时，必须明确提交对应的 `content_updates`。即使原有默认分支足够处理变化，也应显式传入原流程，表示已经确认行为。新增节点通过 `Event.content` 提供内容；流程节点使用 `FlowEvent`，其内容为 `Flow` 对象。

检查失败会抛出异常，整批图更新不提交。库不能从一条新连接自动推断它应提高还是降低某个结果的概率，流程语义由调用者定义。

## 替换结果

```python
graph.replace_result(
    "high_score",
    Result("excellent_score", "final", ("student",)),
    connections=[],  # 新结果的出边在这里显式声明
    content_updates={"final": TableFlow(default={"excellent_score"})},
)
```

旧结果及其出边从当前定义图中移除，新结果加入同一事件。如果旧结果有消费者，这些消费者也必须提供流程更新，即使新结果不重新连接到它们。

已经保存的 `high_score` 历史快照不被删除，也不会自动变成 `excellent_score`。退休的结果 ID 不可复用。需要让旧经历继续满足新条件时，应另行设计迁移或兼容策略，不能只换名字假装结果含义相同。

## 内部流程

```python
flow = TableFlow(
    cases={
        frozenset({"high_score"}): {"hired"},
        frozenset({"experience"}): {"hired"},
        frozenset({"high_score", "experience"}): {"hired"},
    },
    default={"rejected"},
)
```

键是实际存在的相关结果组合，值是本次联合输出，匹配方式是精确集合相等。触发条件已经在流程运行前检查，不混入相关项输入。

一次联合输出可以包含多个角色的结果，例如 `{录用求职者, 面试官完成面试}`。候选输出集合中的结果不会全部自动写入经历。输出的相容性由流程作者保证。

有三种输入覆盖方式：

1. 小规模完全表：不给 `default` 和 `input_domain`，必须覆盖全部相关项子集。
2. 默认分支：用 `default` 处理未列出的组合，不枚举幂集。
3. 显式可达域：用 `input_domain` 声明允许的组合，只覆盖该域；实际收到域外组合时抛出 `UndefinedInput`。

`input_domain` 是作者提供的假设，库不自动证明全局可达性。新增事件可能破坏该假设。复杂条件、状态机、概率抽样可通过继承 `Flow` 实现；自定义流程的静态检查责任见 [API](docs/api.md)。

## 多人、时间与执行顺序

- 每个角色绑定一个人物；一次事件产生一条 `Execution`，携带所有角色的联合结果。
- `Result.recipient_roles` 决定结果写入哪些人物经历。空元组表示世界级结果，例如地震造成的区域损坏。
- `Connection.target_role` 指定读取哪位参与者的经历。省略时，匹配任一参与者的个人结果或世界级结果；角色明确的条件建议始终填写它。
- 流程读取无序的结果 ID 集合，重复记录不会增加同一结果的权重。
- 独立事件可以交换顺序；如果结果、条件或时空限制互相影响，则不保证可交换。
- `is_enabled` 只检查可触发性，不执行流程；`execute` 才实际执行和记录。
- 时间使用调用者定义单位的有限数字，执行记录按世界时间非递减追加。未来记录不能作为过去时刻的输入。

## 当前边界

这是一个内存中的单线程基础库，不包含数据库、自动剧情生成、全局可达性求解、调度器或图形编辑器。事件按瞬时执行处理，`time` 是可触发窗口，不是持续时间模型。

经历是追加式事实，当前触发条件是“全部指定结果已经存在”。撤销、资源消耗、否定条件、按次数判断、角色认知隔离和复杂空间关系尚未建模。一个结果在一个目标事件中只有一条连接，不能同时属于两类输入，也不能用同一个结果 ID 分别占据该事件的多个角色输入。

详见 [设计说明](docs/design.md)、[API 说明](docs/api.md) 和 [完整示例](examples/school_world.py)。
