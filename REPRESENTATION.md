# 迁移后的解析表示与不变量

迁移把每个“写修订 × 读修订”对编译成一张 `v2_plans.graph` 中的 JSON 动作图，
由未修改的 `warehouse.schema2` 执行。`warehouse/graph.py` 只在升级时离线编译，
运行期业务路径不再接触 `schema1`，也不存在第二套解释器。

## 图中的身份

- 写 union 变为 `switch(axis="$branch")`：按具名 `$branch` 精确分派，经 `unwrap`
  取出内容后进入该名字的动作；未知名进入显式 `fail`。字段形状相同但名字不同的
  record 因此不会被同一下标或同形结构误读。
- 读 union 在编译期按声明顺序取**第一个**名字兼容分支（写名 == 读名或属于读
  record 的 aliases），生成 `union(tag=读名)` 包装。选定后再失败不会回退到后续
  同名完整分支，与 schema1 的“首兼容分支”一致。
- record 输出用读名；字段先查同名字段，再按读字段 aliases 顺序匹配写字段，
  命中的写字段路径由 `get(field=写字段名)` 固化。写字段 aliases 不参与。
- 缺失且有默认值的读字段用 `const` 显式内联该默认值；无默认值则在图中放置
  `fail("missing required field: …")`。

## 递归绑定

编译期以“解释后的写节点 × 读节点”为键复用动作 ID，因此自引用/互引用直接成为
图中共享节点（`call`/目标引用），图有限且可序列化。每一层递归都回到同一对
写/读修订的同一组节点，所以两层各自得到各自读修订的默认值；不同读修订对
（如 quality 默认 `checked` 与 `verified`）各自一张独立的图，互不泄漏。

## 惰性失败

`fail` 只在动作被执行时抛 `ResolutionError`，且错误文本沿用 schema1 的原文：
`no compatible reader branch`、`incompatible accessed types`、`missing required field: x`。
未进入的坏分支、空批次都不触发失败；编译只校验引用完整性，不推导类型兼容，
也不执行 `fail`。record 输出字段的动作按声明顺序执行，首个错误即整批失败。

## 原子切换

升级在一个现成 SQLite 事务内完成：建目标表 → 逐表整行复制（保留原 ID、原序
payload、错误文本、状态、请求绑定、归属与回执）→ 为每个已有任务的修订对写入
图 → 调用 `before_commit()` → 更新 `metadata.storage_version='2'`。任一步异常都
回滚，旧表与版本 1 原样保留，重开可重试；版本已为 2 时 `upgrade` 直接返回且
不再调用回调。切换后旧表只作审计，读写路径全部改用 `v2_*` 表；既有对象按
调用时的版本取表，因此升级提交后立即切换，重开对象也只用目标表。
