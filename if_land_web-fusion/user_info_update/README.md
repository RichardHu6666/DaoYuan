# Campus Jarvis 融合版网页

这是 Campus Jarvis 的融合版网页端。Campus Jarvis 的核心目标是整合学校分散的信息入口，让学生可以通过自然语言个性化搜索和匹配适合自己的校园信息，例如“近期我感兴趣的竞赛有哪些”“最近有没有适合我的科研讲座”。

当前网页端以审核版的 `?user_id=<qq_user_id>` 逻辑为底座，额外增加网页账号登录、用户画像配置和网页聊天窗口。网页不是最终目标本身，而是 Campus Jarvis 的用户画像配置、信息检索展示和复杂操作承载入口。

## 项目主线

学校信息并不缺，真正痛点是入口太多、来源太散、有效信息难找。

Campus Jarvis 的目标链路是：

```text
学校官网 / 学院网站 / 公众号 / 竞赛平台 / 讲座通知 / 办事入口
    ↓
统一校园信息库
    ↓
自然语言查询
    ↓
结合用户画像做个性化匹配
    ↓
返回适合该用户的信息、摘要、截止时间和下一步动作
```

典型问题：

- 近期我感兴趣的竞赛有哪些？
- 最近有没有 AI 或医学影像相关讲座？
- 有哪些通知和我这个专业有关？
- 今天我有什么 DDL？
- 这周我最该关注什么？

## 核心逻辑

同一份用户资料，多种入口：

- QQ bot `/信息设置` 跳转：`/?user_id=<qq_user_id>`，免登录进入。
- 直接打开公开网址：显示账号登录页。
- 从 QQ 链接进入后，可以绑定网页账号。
- 以后直接打开网站，输入账号即可进入同一份资料。

用户主身份仍然是：

```text
users_table.uuid
```

账号只是找回 UUID 的别名：

```text
user_account_map.account -> users_table.uuid
```

网页聊天和 QQ 聊天上下文分开：

```text
QQ bot: context_table
Web chat: web_context_table
```

两边共用：

- `users_table`
- `plan_table`
- `notification_table`
- `school_event_table`
- `tools_table`

## 当前网页功能

- 账号登录：直接打开网站时使用网页账号进入。
- QQ 免登录：从 `?user_id=<qq_user_id>` 进入时自动识别用户。
- 账号绑定：QQ 链接进入后可以绑定网页账号。
- 用户配置：维护基本信息、兴趣方向、个人目标和助手回复偏好。
- 个性化搜索基础：通过用户画像记录专业、兴趣、年级、目标和推送偏好，为后续校园信息匹配提供依据。
- 待办管理：新增、编辑、删除 DDL，并支持一键标记完成。
- 课表管理：录入课程并用周课表展示。
- 推送配置：支持常用模板，例如竞赛提醒、讲座推荐、学院通知和 DDL 催办。
- 网页聊天：优先接入 QQ bot 已经在用的智能对话服务，复用 DeepSeek 路由、RAG 检索和回答生成；失败时回退到本地规则回复。
- 今日简报：根据当前用户的 DDL、课表和推送偏好生成规则版每日简报。
- 页面仪表盘：展示待办、课程、推送数量、画像完整度、今日行动和接口状态。

说明：当前每日简报是低成本规则版，不依赖真实 LLM，适合稳定演示。网页聊天已经接入 bot 智能服务，但如果 `school_event_table` 还没有导入真实校园信息，竞赛、讲座、活动类问题会提示“当前信息库暂无匹配”，避免 LLM 编造过期信息。

后续接入校园信息库后，网页聊天和 QQ bot 会扩展为真正的信息搜索入口，支持“近期我感兴趣的竞赛有哪些”这类自然语言个性化查询。

## 本地启动

```powershell
cd "D:\IF_Land\fusion_work\user_info_update"
$env:HOST="127.0.0.1"
$env:PORT="8001"
$env:CAMPUS_JARVIS_DB="D:\IF_Land\fusion_work\seu_campus_assistant.db"
D:\Mini\python.exe app.py
```

访问：

```text
http://127.0.0.1:8001
http://127.0.0.1:8001/?user_id=<qq_user_id>
```

## 服务器部署建议

部署目录：

```text
/root/if_land_web-fusion
```

当前融合版主公网地址：

```text
https://b1qjlru2bq403s60-6666.sc01-webservice.gpuhome.cc:8443/
```

直接打开会进入账号登录；从 QQ bot 跳转时使用：

```text
https://b1qjlru2bq403s60-6666.sc01-webservice.gpuhome.cc:8443/?user_id={user_id}
```

网页服务端口：

```text
0.0.0.0:6666
```

启动命令：

```bash
cd /root/if_land_web-fusion/user_info_update
HOST=0.0.0.0 PORT=6666 CAMPUS_JARVIS_DB=/root/if_land_web-v2/seu_campus_assistant.db nohup python3.12 app.py > server-6666.out.log 2> server-6666.err.log &
```

旧 Cloudflare 融合版地址曾用于临时测试，可作为备用，不作为主入口：

```text
https://corporations-falling-ware-interact.trycloudflare.com
127.0.0.1:8001
```

不要动审核版：

```text
/root/if_land_web-v2
https://nancy-asked-rim-fit.trycloudflare.com
```

## 接口

- `GET /api/health`
- `GET /api/user/bootstrap?user_id=<uuid>`
- `GET /api/user/bootstrap?account=<account>`
- `POST /api/account/login`
- `POST /api/user/save`
- `POST /api/chat`
- `POST /api/daily_brief`
- `POST /api/chat/clear`

## 之后替换审核版时

审核通过后，把 bot 的：

```dotenv
INFO_SETTINGS_URL_TEMPLATE="https://nancy-asked-rim-fit.trycloudflare.com/?user_id={user_id}"
```

改成融合版新网址：

```dotenv
INFO_SETTINGS_URL_TEMPLATE="https://<fusion-url>/?user_id={user_id}"
```

同时确保：

```dotenv
SEU_CAMPUS_DB_PATH="/root/if_land_web-fusion/seu_campus_assistant.db"
```

和网页服务的：

```bash
CAMPUS_JARVIS_DB=/root/if_land_web-fusion/seu_campus_assistant.db
```

指向同一个数据库。

## v1.1 Rokid Lingzhu Plugin Compatibility

- Campus Jarvis tool endpoint: `GET/POST /rokid/plugin/ask`
- Some Lingzhu tool imports may append a generated suffix to the tool path, for example `/rokid/plugin/ask/_OlKrM`.
- The backend now accepts both exact and suffixed paths:
  - `/rokid/plugin/ask`
  - `/rokid/plugin/ask/<generated_suffix>`
- Recommended tool input parameter:
  - `query`: string, required, user natural-language question.
  - `user_id`: string, optional, Campus Jarvis user UUID.
- Recommended tool output parameter:
  - `answer`: string, main answer text.
  - `text`: string, compatibility answer text.
  - `ok`: boolean, request success flag.
  - `engine`: string, backend engine name.

## v1.2 Time-Sensitive Query Guard

- Questions such as `今天有什么 DDL？` are now treated as time-sensitive local queries.
- These queries are answered from SQLite first instead of the LLM service.
- This prevents the model from hallucinating the current date or inventing today's schedule.
- Successful guarded responses use `engine = rule_time_sensitive`.

## v1.3 Rizon Custom Agent Endpoint

- Added `GET/POST /rizon/custom-agent` for Rokid Lingzhu custom-agent experiments.
- The endpoint accepts common input fields: `query`, `q`, `message`, `text`, `input`, `prompt`, `content`, or `messages`.
- It forwards the extracted user question to the same Campus Jarvis backend used by the web page and plugin tool.
- It returns multiple compatibility fields: `answer`, `text`, `content`, and `message`.
- Demo AK: `campus-jarvis-demo-ak`. If no AK is sent, the endpoint currently allows the request for easier platform probing.

## v1.4 Unknown Path Fallback

- Unknown GET/POST paths now fall back to the custom-agent handler instead of returning HTML `404 File not found`.
- This protects against Rokid/Lingzhu generated paths such as `/0fyNbh` or `/campus_jarvis_openapi_prefix.json/kYTLz8`.

## v1.5 Default User and Identity Guard

- Default user changed to `9b1a7c6e-6a11-4a65-a8ab-0f4b5f1c0001` for the glasses demo.
- Account mapping: `test_linyiran -> 9b1a7c6e-6a11-4a65-a8ab-0f4b5f1c0001`.
- Identity questions such as `我是谁？` now bypass the LLM and read SQLite directly.
- Successful identity responses use `engine = rule_identity`.

## v1.6/v1.7 Identity Privacy and DDL Scope

- Identity replies no longer expose internal account names or UUID values.
- DDL queries now distinguish `today`, `this week`, and upcoming scopes instead of treating every DDL query as today's DDL.
- Examples:
  - `今天有什么 DDL？` returns only today's unfinished deadlines.
  - `这周有什么 DDL？` returns unfinished deadlines from today through this Sunday.
  - `最近有什么 DDL？` returns upcoming unfinished deadlines.
