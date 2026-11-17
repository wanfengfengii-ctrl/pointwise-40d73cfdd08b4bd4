# schema1 到 schema2 的数仓迁移契约

## 共同结果与交付边界

把隐式写读解析升级为可持久、独立执行的显式动作图。关联完成两项交付：A 真实迁移全部历史模式、固定任务及业务状态；B 适配加工消费、旧接口续写和目标原生写入，使同一写读修订对始终得到同一解析口径。只搬表仍会留下 schema1 消费旁路；只改执行会遗漏历史绑定或被当前 head 重绑。全部原测试与两个依赖端口保持原字节，新增验证另放文件。

已有完整旧接口、值格式及依赖语义见 README.md、PORTS.md；warehouse/samples.py 的 seed(path) 返回打开的旧 Warehouse 和真实 ID。构造器含移动后的 head、递归数据、成功/失败/未运行任务和空成果。新建数据库仍按原样建立 storage_version=1；升级是显式操作，不能让旧构造器提前建立新版库。未升级时继续支持旧闭环。

## 必须实现的公开入口

- warehouse.migration.upgrade(db, before_commit=None)：db 是现有 Warehouse.db，即 Database 实例；返回 None。在维护窗口、单工作者、没有正在运行任务的边界调用。before_commit 是零参回调，在目标完整但版本切换尚未提交时调用，仅返回或抛异常；升级失败原样传播异常。已经是版本 2 时直接返回，不再次调用回调。
- 保留 Warehouse、Catalog、Archive、Jobs、Publications 的现有公开方法、参数、返回值和错误类别。已有 Warehouse 对象必须立即切到新版；关闭重开后行为相同。既有任务始终固定原批次与原读修订；新增批次必须另建任务，可显式传原读修订，不改变旧任务输入。
- warehouse.native2.register(db, name, schema) 返回修订整数；warehouse.native2.append(db, request_id, writer_revision, values) 返回 batch_id、receipt。这是目标存储的原生写入入口，只接受版本 2，其他版本抛 Conflict。模式与值语法、整批校验、登记 head、请求绑定及重放语义与旧接口相同，但只写目标业务表；旧对象须立即看见其登记和归档。新 ID 不得覆盖历史 ID。
- warehouse.native2.get_plan(db, writer_revision, reader_revision) 返回完整 JSON graph 的独立副本，对应 v2_plans 中已持久化的该修订对。不存在的修订抛 NotFound。尚无图时可按需生成并持久化；不能以当前 head 替代任一参数。返回图须经未修改的 schema2.load_graph/dump_graph/execute 在不同合法写值上独立执行，不依赖数据库、schema1、回调或原批次成果。

## 存储切换

schema_v2.sql 提供固定目标表契约，不含迁移实现；metadata 继续保留。迁移须复制全部修订、head、批次、任务、运行与成果，保留原 ID、原序载荷、错误文本、状态、请求绑定、归属及回执；为每个已有任务对应的写读修订对保存可执行图。实际不兼容、空批次或曾失败任务也必须能迁移，图可以含按访问才触发的 fail。不得通过先执行该任务决定能否升级。

全部目标状态与 metadata.storage_version='2' 在现成 SQLite 事务内原子提交。提交前异常必须保全旧库及原版本，重开可重试；重复升级无副作用。切换后旧业务表及原文只留审计，不能再读写；既有和重开对象均只使用目标业务表。允许额外 v2_ 表辅助组织图，不能另保留旧执行旁路。schema.py 的模式语法和写值校验可以复用；schema1 及其 compatible、resolve 在升级后的业务路径中均不得调用。目标解析统一由未修改 schema2 执行，不得增加另一套解析执行器或把旧模式作为运行时解释程序。

## 兼容语义

具名 record、显式 union、递归引用、字段及 record 别名方向、默认值和首个兼容读分支均沿用 PORTS.md。按写入身份匹配，不能按字段形状或 union 下标匹配。写 [A{x:long},B{x:long},string]、读 [B{x:long},A{x:long}] 时，A/7、B/7 分别仍为 A/7、B/7；未访问 string 不失败，实际 string 才使整批失败。

同一递归 Node 写修订由 quality 默认 checked、verified 的两个读修订消费，各层须得到各自默认值；随后同名 head 改成 string，也不能改变两项旧任务。读 union 的首个名称兼容分支一旦选定，缺必需字段就失败，不能回退到后续同名完整分支。未进入的坏分支、空批次不提前报错，默认 record 值互相独立；保留原 ResolutionError 的错误文本与首错行为。

允许全量转换及重算，解析表示自行选择。迁移不要求在线复制、多工作者、性能索引或进程自动接管。成果仍由现有发布事务整批发布；实际解析或发布提交前失败，不得留下部分成果或新发布回执，不得改变此前成果。

## 公开联合核验

python3.11 -B -m unittest migration_checks -v 是新增迁移兼容入口，在实现目标能力后执行；未实现的初始树不应被描述为升级失败事故。它将真实构造旧库，核对历史搬运、具名换序、固定递归口径、不同数据的持久图执行、旧与原生续写、失败保全及文件关闭重开。核验包括禁止旧表访问和禁用 schema1 的目标路径。允许补充独立直接参照与更多业务数据，不更改原断言。

保留原完整 discover；交付时让现有运行清单的 verify 同时执行原回归及迁移核验，demo 从真实旧库升级并展示具名成果、固定递归口径及原生续写，不能只打印成功。附简短表示说明，解释图中的身份、递归绑定、惰性失败及原子切换不变量。
