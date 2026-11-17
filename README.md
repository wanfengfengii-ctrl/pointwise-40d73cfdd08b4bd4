# 模式化数仓归档

Python 3.11 标准库项目。数据来源登记不可变写模式，将有序有限值整批归档；加工任务固定一个批次和一个读模式修订，经 schema1 解析后整批发布。相同来源数据可建立多个不同读口径任务，历史成果保留输入、写修订、读修订和运行归属。

```sh
python3.11 -B -m unittest discover -s tests -v
python3.11 -B -m warehouse.demo
```

demo 从真实文件旧库升级后运行，输出真实具名联合、固定递归默认字段、空成果、旧接口续写与原生续写。完整回归另在测试临时目录验证 SQLite 关闭重开、请求重放及提交异常回滚。无安装步骤，无第三方依赖。

## Python API

```python
from warehouse import Warehouse, record, union

with Warehouse() as wh:
    writer = wh.register("source", [
        {"type": "record", "name": "Reading",
         "fields": [{"name": "value", "type": "long"}]},
        "null",
    ])
    reader = wh.register("consumer", [
        "null",
        {"type": "record", "name": "Reading",
         "fields": [{"name": "value", "type": "long"},
                    {"name": "unit", "type": "string", "default": "count"}]},
    ])
    accepted = wh.append("request-1", writer, [
        union("Reading", record("Reading", value=12)),
        union("null", None),
    ])
    job = wh.create_job(accepted["batch_id"], "consumer")
    published = wh.run(job)
    print(wh.results(job, published["run_id"]))
```

传文件路径给 Warehouse 可持久保存。独立构造器 `python3.11 -B -m warehouse.samples sample.sqlite` 要求新的空数据库路径，构造真实 schema1 库，含模式历史、移动过的名称 head、具名归档、递归数据、成功/失败/未运行任务、历史成果和回执。所有文件由调用方选择，程序不访问项目外的个人配置或服务。

## 契约与代码

- `warehouse/catalog.py`：register(name, schema) 返回整数修订并移动非空目录名称的 head；每次成功登记产生新修订。get 接受名称或整数修订，返回独立副本。坏模式不产生修订、不移动 head。
- `warehouse/archive.py`：append(request_id, writer_revision, values) 校验整批后返回 batch_id、receipt。写模式必须传整数修订，批次及行序不可变。同请求、同修订、同 JSON 逻辑载荷返回原回执；否则 Conflict。对象键顺序不影响重放，数组顺序和重复次数影响。
- `warehouse/jobs.py`：create_job(batch_id, reader_name_or_revision) 返回整数任务 ID；仅创建时解析名称，固定读修订和批次。追加其他批次不会改变旧任务输入。run 每次建立新运行；成功发布全部值，实际访问解析错误则记录 failed 并传播原异常。
- `warehouse/publication.py`：results(job_id, run_id=None) 返回有序 values 及归属、receipt；省略 run_id 取最近成功成果。已存在但无成功成果返回 None，成功空批返回 values=[]；未知任务、未知运行或运行属于其他任务抛 NotFound。旧成果永不覆盖。
- `warehouse/db.py`：SQLite 外键和共享事务；publish 在同一事务写入成果、回执及 succeeded 状态。异常回滚，jobs 再记录 failed，保全此前成功成果。run 的可选 before_commit 零参回调用于确定性提交故障注入，须只抛异常或返回，不修改数据库。支持单工作者，不提供进程崩溃后的运行自动接管。建库按 metadata.storage_version 选择旧表或仅目标表；旧构造器仍建立版本 1。

模式和值的严格语法、双代依赖端口见 PORTS.md。所有公开业务错误继承 WarehouseError：SchemaError（模式/写值）、ResolutionError（实际读取不兼容）、Conflict（请求绑定冲突）、NotFound（归属不存在）。有限 JSON 值为输入边界，循环 Python 容器不属于数据格式。

## schema1 → schema2 迁移

`warehouse.migration.upgrade(db, before_commit=None)` 在单个事务内把全部历史模式、批次、任务、运行与成果复制到 `v2_*` 目标表，并为每个已有任务把其写读修订对编译成 `schema2` 动作图存入 `v2_plans`，最后切换 `metadata.storage_version='2'`。`before_commit` 在目标完整但尚未提交时调用；失败回滚保全旧库，重开可重试，重复升级无副作用。切换后旧表仅留审计；`Warehouse` 的旧方法与 `warehouse.native2` 的原生入口共用同一目标存储。`warehouse/native2.py` 提供 `register`、`append`、`get_plan`，`warehouse/graph.py` 是升级期的离线编译器。表示与不变量见 REPRESENTATION.md。

## 确定性回归

tests/test_ingest.py 覆盖具名身份、非法修订、请求重放、批次后段坏值及类型边界；tests/test_processing.py 覆盖递归默认值、惰性分支、别名与第一个兼容分支、缺字段、成果原子性、空与缺失；tests/test_evolution.py 覆盖固定读修订和递归读口径独立性；tests/test_persistence.py 通过真实文件关闭重开验证历史和回滚；tests/test_schema2.py 独立验证显式动作端口。

运行清单的 verify 执行完整 discover（原回归、迁移核验与图/旧解析对照），demo 从真实旧库升级并执行公开业务入口。
