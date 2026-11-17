# 模式和值格式

目录名是任意非空字符串；模式中的具名身份使用 [A-Za-z_][A-Za-z0-9_.]*，不进行隐式命名空间扩展。

模式节点仅含 "null"、"long"、"string"、record 对象、union 数组或具名引用字符串。long 是有符号 64 位整数，bool 不算 long。不支持类型提升。record 为 {"type":"record","name":"Node","aliases":[],"fields":[...]}；字段为 {"name":"x","type":"long","aliases":[],"default":0}。aliases 和 default 可省略。具名定义在一个修订内唯一，可前向或递归引用；同修订内未定义引用拒绝。字段名及字段别名不能相互歧义。union 非空、不能直接嵌套 union、不能重复分支身份。

每一个 record 值都是 {"$type":"Node","fields":{"x":3,...}}，每一个 union 值都是 {"$branch":"Node","value":...}，原始类型分支用原始类型名。null 分支也必须显式包装。write record 必须包含全部声明字段，无多余字段，写入不隐式补默认值。读默认值必须已经是对应类型的合法值，包括完整 record/union 包装；未指定默认值与指定 null 不同。

## schema1：隐式写读解析

`warehouse.schema1.resolve(writer_schema, reader_schema, value)` 校验写值，再直接返回读值。双方具名引用各自在自己的完整模式环境内解释：

1. 写 union 根据值的 $branch 取实际分支。不能使用读 union 的位置索引。
2. 读 union 选声明顺序中第一个兼容分支；record 兼容当且仅当写名称等于读名称或属于读 record 的 aliases，原始类型仅同型兼容。record 的字段差异不用于挑选 union 分支；选定后字段失败不能改选后续分支。
3. record 输出使用读名称。读字段优先查同名写字段，再按读字段 aliases 顺序查写字段名；缺失时深拷贝读默认值，无默认值时报 ResolutionError。写字段的 aliases 不参与读取匹配。多余写字段丢弃。
4. 不兼容仅在实际访问到时失败；未进入 union 分支、空批次不触发解析错误。默认值相互独立。递归值的每一层都保留自己的写/读模式环境。

例如写 [A{x:long},B{x:long}]、读 [B{x:long},A{x:long}]，A/7 始终读为 A/7，B/7 始终读为 B/7；两者字段形状相同不改变身份。另如递归 Node 读模式增加 quality 默认 "raw"，有限链的每一层均得到该字段，null 尾部仍为 null。

## schema2：显式动作端口

`warehouse.schema2` 是独立可用的离线动作执行依赖，不接收模式，不解释字段或类型别名，不寻找兼容分支。输入是相同 JSON 值格式与一个完整 JSON graph：

```json
{"root":"guard","nodes":{
  "guard":{"op":"check","kind":"record","name":"A","next":"field"},
  "field":{"op":"get","field":"x","next":"copy"},
  "copy":{"op":"copy"}
}}
```

`validate_graph(graph)` 校验格式与所有引用，返回图；`dump_graph(graph)` 输出可持久化文本；`load_graph(text)` 校验并恢复；`execute(graph,value)` 执行。没有隐式解析器或图生成接口。get 不读模式默认值，const 由图显式给值。所有动作引用均为 nodes 的字符串键：

| op | 属性与执行 |
|---|---|
| copy | 深拷贝当前输入 |
| const | value：深拷贝指定常量 |
| fail | message：被执行时抛 ResolutionError |
| check | kind 为 null/long/string/record/union；record 另给 name；检查通过后 next，失败抛 ResolutionError |
| get | 从当前 record 的 fields 中读取 field，交给 next；缺字段失败 |
| unwrap | 从 tagged union 取 value 交给 next |
| switch | axis 为 $branch 或 $type；按 cases 中的精确身份跳转，否则 otherwise；分支收到完整原输入 |
| record | name 和 fields（有序 [字段名,动作ID] 列表）；各字段动作分别以同一原输入执行，输出具名 record |
| union | tag 与 next；包装 next 的输出 |
| call | target：以当前输入调用动作，可递归 |
| compose | first 输出作为 then 的输入 |

图验证检查悬空引用，但不执行 fail，也不推导动作之间的类型兼容。递归图应由有限输入驱动终止；端口不替调用方证明终止。tests/test_schema2.py 提供手写递归图、两阶段组合、不同数据重复执行及未访问失败动作的完整样例。动作图可独立序列化，不包含 Python 回调或 schema1 调用。业务数仓当前只经 schema1 消费归档。
