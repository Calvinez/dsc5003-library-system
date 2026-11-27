# B/C 接入约定与示例事务

这些是 A 的数据库接口示例，不是 B 的已实现后端。SQL 值必须由驱动参数绑定；示例中的 `%s` 是 PyMySQL 占位符，不可用字符串拼接替换。所有时间由小组统一采用 Asia/Shanghai 的 DATETIME 本地时间；演示固定基准为 2026-11-26 12:00:00，线上由服务端产生当前时间。

## 借书：完整事务

1. BEGIN。
2. `SELECT reader_id,status FROM readers WHERE reader_no=%s FOR UPDATE`，确认读者存在且 ACTIVE。
3. `SELECT copy_id,status FROM book_copies WHERE barcode=%s FOR UPDATE`，确认副本存在且 IN_SERVICE。
4. `SELECT loan_id FROM loans WHERE active_copy_id=%s FOR UPDATE`，有记录则返回“已借出”。此查询以 copy_id 为值。
5. `INSERT INTO loans(reader_id,copy_id,borrowed_at,due_at) VALUES (%s,%s,%s,%s)`，例如借期 14 天由 B 计算。
6. COMMIT；任何异常均 ROLLBACK。返回 loan_id。

步骤 2、3 的锁顺序保持先读者、后副本。触发器会再次检验资格并加锁；唯一索引 uq_loans_active_copy 是最终的并发防线，前端“可借”显示不是锁。遇 1062（活动借阅唯一键冲突）转为已借出；1644 为明确规则拒绝；1213 死锁/1205 锁等待超时应回滚整个事务，有限次数重试，仍失败则让用户重试。不要把所有 1062 都映射成同一错误，应识别发生冲突的约束。

新增借阅请先查出 ID，再用 INSERT ... VALUES；不要在同一 INSERT ... SELECT 中读取 readers/book_copies，因为借阅触发器会锁定这两张父表，MySQL 对这种同语句再访问可能报 1442。演示脚本已经采用分步查 ID 的方式。

## 还书：完整事务

1. BEGIN。
2. `SELECT loan_id,returned_at,borrowed_at FROM loans WHERE loan_id=%s FOR UPDATE`，检查存在并属于当前授权读者/管理员。
3. 若 returned_at 已有值，直接返回“已归还”（幂等响应，不再次 UPDATE）。
4. `UPDATE loans SET returned_at=%s WHERE loan_id=%s AND returned_at IS NULL`，归还时间不得早于借出时间。
5. COMMIT；异常 ROLLBACK。唯一键中的 active_copy_id 自动变为 NULL，副本重新可借，无需更新库存计数。

挂失/维护：仅当没有未还借阅时将 book_copies.status 改为 MAINTENANCE 或 WITHDRAWN。读者可以暂停，但原有借阅仍能归还。due_at 可在未还借阅上合法调整，次数/最长借期等续借政策本期未实现。

## 建议查询接口

| 接口用途 | 数据库查询 | 返回字段 |
|---|---|---|
| 图书搜索 | sql/02_sample_queries.sql 的 Q1；输入前缀 | book_id,isbn,title,category,publisher |
| 某书实体馆藏 | Q2；按 ISBN | copy_id,barcode,shelf_code,availability |
| 借阅历史 | Q3；按 reader_no | loan_id,title,barcode,borrowed_at,due_at,returned_at |
| 逾期列表 | Q4；按当前截止时刻 | reader_no,name,title,due_at,overdue_days |
| 馆藏统计 | Q5 | total_copies,available_copies |

搜索词中的 `%` 与 `_` 是 LIKE 通配符：产品若承诺字面匹配，B 必须转义并指定 ESCAPE 字符。ISBN 为精确匹配。大页数列表宜按排序键做游标分页，示例只取第一页。SQL 不含登录与权限校验，B 必须在 API 层实施访问控制；不要把数据库密码交给 C 的浏览器代码。

## 账号与初始化

schema 用 owner 账号初始化。普通后端仅 SELECT/INSERT/UPDATE；不给 DELETE loans，避免删除历史；管理员仍有更高权限，所以不能宣称 DBA 无法改历史。测试与性能实验用独立数据库、独立 owner 连接。脚本读取 DB_* 环境变量，不自动加载 .env，连接也会设置严格 SQL 模式和 time_zone='+08:00'；B 若使用其他驱动也应在连接后设置这两个会话参数。Docker 同时设置默认时区 +08:00。

## 已知边界

本包未包含登录、API、前端、罚款、预约或限借策略。图书出版版本以 ISBN 唯一识别；一书归属一个类别与出版社，作者以稳定 author_key 区分同名者。数据库保证同副本最多一条当前未归还借阅；任意管理员补录的已还历史是否相互时间重叠没有数据库区间排斥约束，正常借还 API 应只允许按当前业务时间写入。模拟数据生成器自行保证历史区间不重叠。
