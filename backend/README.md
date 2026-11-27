# 图书借阅后端（成员 B）

Python 3.10+、Flask、PyMySQL。先按[数据库初始化说明](../database/README.md)初始化 MySQL 演示库。应用使用 A 的表、触发器及普通应用数据库账号。

完整应用的启动步骤见[项目 README](../README.md)。Flask 在同一个端口提供前端和 API。

在本目录用 PowerShell 执行以下命令，沿用数据库初始化时的 DB_* 设置，缺失时使用下方默认值并输入密码。演示令牌仅用于本地联调。共享环境请生成高熵令牌，通过安全渠道分发。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not $env:DB_HOST) { $env:DB_HOST = '127.0.0.1' }

if (-not $env:DB_PORT) { $env:DB_PORT = '3306' }

if (-not $env:DB_NAME) { $env:DB_NAME = 'library_project' }

if (-not $env:DB_USER) { $env:DB_USER = 'library_app' }

if (-not (Test-Path Env:DB_PASSWORD)) {
    $databaseSecret = Read-Host '输入 library_app 的 MySQL 密码' -AsSecureString
    $env:DB_PASSWORD = [System.Net.NetworkCredential]::new('', $databaseSecret).Password
}
$env:LIBRARY_READER_TOKENS = '{"local-demo-reader-1":"R-DEMO-001","local-demo-reader-2":"R-DEMO-002"}'
.\.venv\Scripts\python.exe -m flask --app app run --host 127.0.0.1 --port 8000
```

项目网页从 Flask 首页访问并同源调用 API。独立的浏览器 API 客户端可用 `LIBRARY_FRONTEND_ORIGIN` 配置其页面来源（协议、域名和端口）。数据库密码与令牌映射由后端配置。

| 方法与路径 | 输入 | 成功响应 |
|---|---|---|
| GET /api/books | 可选 `q`，书名开头，空值显示前 20 条 | `items` 含 book_id、isbn、title、category、publisher |
| GET /api/books/{isbn}/copies | 13 位 ISBN | `items` 含 isbn、title、copy_id、barcode、shelf_code、availability |
| GET /api/loans | Bearer 令牌 | `items` 含当前读者最近 100 条记录的 loan_id、title、barcode、borrowed_at、due_at、returned_at |
| POST /api/loans | Bearer 令牌与 JSON `{"barcode":"副本条码"}` | 201，loan_id、barcode、borrowed_at、due_at |
| POST /api/loans/{loan_id}/return | Bearer 令牌，无需请求体 | 200，loan_id、returned_at、already_returned |

借还和历史请求发送 `Authorization: Bearer <令牌>`。客户端用响应中的日期显示借还时间，时间格式为 ISO 8601（+08:00），未归还时 returned_at 为 null。可借状态为 AVAILABLE、ON_LOAN、MAINTENANCE 或 WITHDRAWN。错误格式为 `{"error":{"code":"already_on_loan","message":"该副本已借出"}}`。400 为参数无效，401 为令牌缺失或无效，403 为读者不可借，404 为副本或本人借阅记录找不到，409 为借阅冲突或规则拒绝，503 为数据库不可用或事务重试耗尽。

借书时按读者、实体副本顺序加锁，检查活动借阅后插入记录。A 的活动副本唯一索引提供数据库层保障。还书时锁定本人借阅记录并写入归还时间，重复归还返回原时间。所有 SQL 输入通过驱动绑定。借期设为 14 天，读者身份由配置的演示令牌确定。
