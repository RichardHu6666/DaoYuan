# 你的导员网页端后端接入文档

文档版本：v1.0  
更新时间：2026-06-06  
面向对象：负责把新后端接入现有前端网页的同学

## 1. 当前地址与代码位置

项目名称：你的导员  
定位：校园智能入口。用户通过网页或 QQ bot 维护同一份个人资料，并用自然语言检索校园通知、竞赛、讲座、DDL、课表和办事入口。

当前正式网页地址：

```text
https://b1qjlru2bq403s60-6666.sc01-webservice.gpuhome.cc:8443/
```

QQ bot 跳转网页时使用：

```text
https://b1qjlru2bq403s60-6666.sc01-webservice.gpuhome.cc:8443/?user_id={user_id}
```

服务器目录：

```text
/root/if_land_web-fusion/user_info_update
```

前端静态文件：

```text
/root/if_land_web-fusion/user_info_update/static/index.html
/root/if_land_web-fusion/user_info_update/static/app.js
/root/if_land_web-fusion/user_info_update/static/styles.css
```

当前正式数据库：

```text
/root/rivermind-data/database/seu_campus_assistant.db
```

准备接入的新决策后端：

```text
/root/decision
```

当前 6666 端口：

```text
0.0.0.0:6666
```

## 2. 前端入口逻辑

前端只有一个页面，但有两种进入方式。

第一种：QQ bot 链接进入。

```text
/?user_id=<uuid>
```

前端会直接调用：

```http
GET /api/user/bootstrap?user_id=<uuid>
```

这种方式不需要账号登录。`user_id` 是主身份，必须对应数据库里的 `users_table.uuid`。

第二种：用户直接打开公网网址。

```text
/
```

前端会显示账号登录层，用户输入账号后调用：

```http
POST /api/account/login
```

账号不是主身份，只是 `uuid` 的别名。后端需要维护：

```text
user_account_map.account -> users_table.uuid
```

前端本地会用 `localStorage` 缓存草稿和最近账号，但后端仍然是最终真相源。

## 3. 前端必须保留的接口

所有接口默认返回 JSON，推荐统一格式：

```json
{
  "ok": true
}
```

失败时：

```json
{
  "ok": false,
  "error": "错误说明"
}
```

前端的 `fetchJson()` 逻辑会在以下情况直接报错：

- HTTP 状态码不是 2xx。
- JSON 中 `ok === false`。
- 返回内容不是合法 JSON。

### 3.1 `GET /api/health`

用途：网页左侧“系统状态”卡片。

请求：

```http
GET /api/health
```

建议响应：

```json
{
  "ok": true,
  "database": {
    "path": "/root/rivermind-data/database/seu_campus_assistant.db",
    "counts": {
      "users_table": 5,
      "plan_table": 22,
      "notification_table": 13,
      "school_event_table": 823
    }
  },
  "backend": {
    "name": "decision",
    "status": "ready"
  }
}
```

前端只强依赖：

- `ok`
- `database.counts.users_table`
- `database.counts.plan_table`
- `database.counts.notification_table`

### 3.2 `GET /api/user/bootstrap`

用途：初始化用户完整资料包。

请求方式 A：通过 UUID。

```http
GET /api/user/bootstrap?user_id=<uuid>
```

请求方式 B：通过账号。

```http
GET /api/user/bootstrap?account=<account>
```

响应必须是完整 `UserBundle`：

```json
{
  "ok": true,
  "account": "yuqingchen",
  "user": {
    "user_id": "2ad03c38-4813-4b0c-bf40-66bf55c1ab30",
    "nickname": "于清辰"
  },
  "profile": {
    "user_id": "2ad03c38-4813-4b0c-bf40-66bf55c1ab30",
    "real_name": "于清辰",
    "gender": "男",
    "birthday": "",
    "school": "东南大学",
    "campus": "九龙湖",
    "college": "仪器科学与工程学院",
    "major": "智能感知工程",
    "grade": "大一",
    "interests": "[\"人工智能\",\"校园信息\",\"竞赛\"]",
    "goals": "[\"提升GPA\",\"参加竞赛\"]",
    "preferences": "{}",
    "personal_description": "",
    "assistant_persona": ""
  },
  "deadlines": [],
  "courses": [],
  "push_settings": {
    "user_id": "2ad03c38-4813-4b0c-bf40-66bf55c1ab30",
    "content_preferences": "[]",
    "daily_ddl_enabled": 1,
    "push_frequency": "daily",
    "push_times": "[\"08:30\"]",
    "quiet_hours_start": "",
    "quiet_hours_end": "",
    "deadline_lookahead_days": 7
  },
  "web_context": []
}
```

字段要求：

- `user.user_id`、`profile.user_id`、`push_settings.user_id` 必须一致。
- `interests`、`goals`、`preferences`、`content_preferences`、`push_times` 当前前端按 JSON 字符串处理，不要改成对象或数组，除非同时改前端。
- `deadlines`、`courses`、`web_context` 必须是数组。
- 用户不存在时建议创建空用户，而不是直接 404。QQ bot 跳转过来的新 UUID 需要能首次打开。

### 3.3 `POST /api/account/login`

用途：直接打开网页时账号登录；或 QQ 链接进入后绑定网页账号。

请求：

```json
{
  "account": "yuqingchen",
  "bind_user_id": "",
  "legacy_user_id": ""
}
```

字段说明：

- `account`：必填，前端会转小写并去空格。
- `bind_user_id`：可选。从 QQ 链接进入后绑定账号时传当前 UUID。
- `legacy_user_id`：历史兼容字段，当前前端传空字符串。

响应：同 `GET /api/user/bootstrap`，返回完整 `UserBundle`。

账号规则建议：

- 账号唯一。
- 一个账号只能绑定一个 UUID。
- 一个 UUID 只能绑定一个账号。
- 如果账号已存在，直接返回该账号对应的用户资料。
- 如果账号不存在且带 `bind_user_id`，把账号绑定到该 UUID。
- 如果账号不存在且没有 `bind_user_id`，新建 UUID 和空用户资料。

### 3.4 `POST /api/user/save`

用途：保存基本资料、待办、课表、推送配置。

请求体就是完整 `UserBundle`，示例：

```json
{
  "account": "yuqingchen",
  "user_id": "2ad03c38-4813-4b0c-bf40-66bf55c1ab30",
  "user": {
    "user_id": "2ad03c38-4813-4b0c-bf40-66bf55c1ab30",
    "nickname": "于清辰"
  },
  "profile": {
    "user_id": "2ad03c38-4813-4b0c-bf40-66bf55c1ab30",
    "real_name": "于清辰",
    "gender": "男",
    "birthday": "",
    "school": "东南大学",
    "campus": "九龙湖",
    "college": "仪器科学与工程学院",
    "major": "智能感知工程",
    "grade": "大一",
    "interests": "[\"人工智能\",\"竞赛\"]",
    "goals": "[\"提升GPA\"]",
    "preferences": "{\"interests\":[\"人工智能\",\"竞赛\"],\"goals\":[\"提升GPA\"],\"campus\":\"九龙湖\"}",
    "personal_description": "",
    "assistant_persona": ""
  },
  "deadlines": [
    {
      "deadline_id": "",
      "title": "高数作业",
      "description": "完成第十五周习题",
      "start_time": "",
      "deadline_time": "2026-06-09 23:00",
      "priority": "3",
      "status": "pending",
      "category": "课程",
      "source_type": "manual",
      "source_ref": ""
    }
  ],
  "courses": [
    {
      "course_id": "",
      "course_name": "高等数学A",
      "day_of_week": "1",
      "start_section": "1",
      "end_section": "2",
      "start_time": "1",
      "end_time": "2",
      "location": "教一",
      "teacher": "",
      "weeks": "",
      "note": "",
      "color": "blue"
    }
  ],
  "push_settings": {
    "user_id": "2ad03c38-4813-4b0c-bf40-66bf55c1ab30",
    "content_preferences": "[{\"push_id\":\"push-1\",\"type\":\"custom\",\"title\":\"竞赛提醒\",\"content\":\"AI竞赛\",\"frequency\":\"daily\",\"date\":\"\",\"weekdays\":[],\"repeat_count\":1,\"times\":[\"08:30\"]}]",
    "daily_ddl_enabled": 1,
    "push_frequency": "daily",
    "push_times": "[\"08:30\"]",
    "quiet_hours_start": "",
    "quiet_hours_end": "",
    "deadline_lookahead_days": 7
  },
  "web_context": []
}
```

响应：建议返回保存后的完整 `UserBundle`。

后端处理建议：

- 以 `user_id` 为主键保存用户资料。
- `deadlines` 和 `courses` 可以按该用户全量覆盖保存。
- `push_settings.content_preferences` 里包含多个推送项，前端当前按一个 JSON 字符串存取。
- 保存成功后必须返回最新 `user.user_id`，前端会用它刷新本地状态。

### 3.5 `POST /api/chat`

用途：网页聊天窗口。这个接口是接入 `/root/decision` 的核心接口。

请求：

```json
{
  "user_id": "9b1a7c6e-6a11-4a65-a8ab-0f4b5f1c0001",
  "message": "近期我感兴趣的竞赛有哪些？"
}
```

响应：

```json
{
  "ok": true,
  "user_id": "9b1a7c6e-6a11-4a65-a8ab-0f4b5f1c0001",
  "reply": "这里是给用户看的最终回答。",
  "context": [
    {
      "role": "user",
      "content": "近期我感兴趣的竞赛有哪些？"
    },
    {
      "role": "assistant",
      "content": "这里是给用户看的最终回答。"
    }
  ],
  "engine": "decision"
}
```

前端强依赖字段：

- `reply`：展示在聊天气泡里。
- `context`：如果是数组，会写回本地草稿并用于下次渲染。

建议后端行为：

- `message` 为空时返回 400。
- `user_id` 缺失时返回 400，错误文案可以是“缺少用户标识 user_id”。
- 正常回答统一放在 `reply`。
- `engine` 建议写清楚当前来源，例如 `decision`、`decision_fallback`、`rule_identity`。

`/root/decision` 推荐接入方式：

```python
from decision import ClientManager

manager = ClientManager()

async def answer(user_id: str, message: str) -> str:
    client = await manager.get_client(user_id)
    return await client.respond(message)
```

如果需要调试信息，可用：

```python
result = await client.respond_result(message)
reply = result.response_text
engine = f"decision:{result.route}"
trace = result.trace
```

注意：

- `ClientManager` 应该在服务进程内长期持有，不要每条请求重新创建。
- 同一用户的并发请求由 `ClientSession` 内部锁串行化。
- 服务关闭时应调用 `await manager.close()`，把上下文写回数据库。

### 3.6 `POST /api/daily_brief`

用途：点击“生成今日简报”按钮。

请求：

```json
{
  "user_id": "9b1a7c6e-6a11-4a65-a8ab-0f4b5f1c0001"
}
```

响应：

```json
{
  "ok": true,
  "user_id": "9b1a7c6e-6a11-4a65-a8ab-0f4b5f1c0001",
  "brief": "今日简报文本。",
  "context": []
}
```

前端强依赖：

- `brief`
- `context`

这个接口可以先用规则生成，不一定必须接 LLM。

### 3.7 `POST /api/chat/clear`

用途：清空网页聊天上下文。

请求：

```json
{
  "user_id": "9b1a7c6e-6a11-4a65-a8ab-0f4b5f1c0001"
}
```

响应：

```json
{
  "ok": true,
  "user_id": "9b1a7c6e-6a11-4a65-a8ab-0f4b5f1c0001",
  "context": []
}
```

注意：

- 只清空网页端上下文。
- 不要求清空 QQ bot 上下文。
- 当前设计允许网页聊天和 QQ bot 聊天上下文相互独立，但用户资料共用。

## 4. 眼镜/插件兼容接口

这些不是网页前端主动调用的接口，但当前演示需要保留。

### 4.1 Rizon 自定义智能体

正式 URL：

```text
https://b1qjlru2bq403s60-6666.sc01-webservice.gpuhome.cc:8443/rizon/custom-agent
```

支持：

```http
GET /rizon/custom-agent?query=我是谁&user_id=<uuid>
POST /rizon/custom-agent
```

POST 请求可兼容以下字段之一作为用户问题：

```text
query / q / message / text / input / prompt / content
```

响应建议：

```json
{
  "ok": true,
  "answer": "最终回答",
  "text": "最终回答",
  "content": "最终回答",
  "message": "最终回答",
  "engine": "decision",
  "user_id": "9b1a7c6e-6a11-4a65-a8ab-0f4b5f1c0001"
}
```

眼镜平台推荐配置：

```text
自定义智能体ID：campus-jarvis
名称：你的导员
类别：学习
URL：https://b1qjlru2bq403s60-6666.sc01-webservice.gpuhome.cc:8443/rizon/custom-agent
AK：campus-jarvis-demo-ak
```

### 4.2 普通插件接口

支持路径：

```text
/ask
/ask/<suffix>
/rokid/plugin/ask
/rokid/plugin/ask/<suffix>
```

请求：

```http
GET /ask?query=这周有什么DDL&user_id=<uuid>
```

或：

```json
{
  "query": "这周有什么DDL",
  "user_id": "9b1a7c6e-6a11-4a65-a8ab-0f4b5f1c0001"
}
```

响应至少包含：

```json
{
  "ok": true,
  "answer": "最终回答",
  "text": "最终回答",
  "engine": "decision",
  "user_id": "9b1a7c6e-6a11-4a65-a8ab-0f4b5f1c0001"
}
```

## 5. 数据表对应关系

前端概念和数据库表的关系如下。

```text
用户主身份
users_table.uuid

网页账号
user_account_map.account -> users_table.uuid

基本画像
users_table

待办 / DDL
plan_table

推送配置
notification_table

网页聊天上下文
web_context_table

QQ bot 聊天上下文
context_table

校园通知 / 竞赛 / 讲座 / 活动
school_event_table

校园工具入口
tools_table
```

前端不直接操作数据库，只依赖 HTTP JSON 契约。

## 6. 后端替换建议

如果后端同学要把核心全部换成 `/root/decision`，建议不要直接删除网页服务外壳。原因是 `/root/decision` 当前是决策层包，不是完整 HTTP 网页后端。

推荐改法：

```text
保留：
- 静态文件服务
- /api/user/bootstrap
- /api/account/login
- /api/user/save
- /api/health
- /api/daily_brief
- /api/chat/clear
- /ask
- /rizon/custom-agent

替换：
- /api/chat 的智能回答核心
- /ask 和 /rizon/custom-agent 的回答核心
```

统一调用链：

```text
前端 /api/chat
    ↓
提取 user_id + message
    ↓
decision.ClientManager.get_client(user_id)
    ↓
client.respond_result(message)
    ↓
返回 reply/context/engine
```

`/root/decision` 当前已知运行依赖：

```text
DECISION_DB_PATH=/root/rivermind-data/database/seu_campus_assistant.db
DECISION_DB_HELPER_PATH=/root/rivermind-data/seu_campus_db_v2.py
DECISION_LLM_API_KEY 或 DEEPSEEK_API_KEY
DECISION_EMBEDDING_BACKEND
```

注意：

- 当前库里的 `embedded_summary` 是 1024 维，长度为 4096 bytes。
- 如果使用 `local_bge_m3`，服务器环境需要 `transformers` 和 `torch`，并能加载 `BAAI/bge-m3`。
- 如果使用 `openai` embedding，需要有效 `DECISION_EMBEDDING_API_KEY` 或 `OPENAI_API_KEY`，并保证新 query embedding 维度与库内 1024 维一致，否则检索会失败。
- 上线前必须先在影子端口验证 `python3 -m decision respond <user_id> "近期我感兴趣的竞赛有哪些"` 能跑通。

## 7. 最小验收用例

后端接完后，用以下用例验收。

### 网页初始化

```http
GET /api/user/bootstrap?user_id=9b1a7c6e-6a11-4a65-a8ab-0f4b5f1c0001
```

预期：

- HTTP 200。
- `ok=true`。
- 返回 `user.user_id`。
- 页面能显示用户资料、待办、课表、推送。

### 账号登录

```json
POST /api/account/login
{
  "account": "test_linyiran",
  "bind_user_id": "",
  "legacy_user_id": ""
}
```

预期：

- HTTP 200。
- 返回完整 `UserBundle`。

### 网页聊天

```json
POST /api/chat
{
  "user_id": "9b1a7c6e-6a11-4a65-a8ab-0f4b5f1c0001",
  "message": "近期我感兴趣的竞赛有哪些？"
}
```

预期：

- HTTP 200。
- `reply` 非空。
- `engine` 能看出走了 decision。
- 页面发送按钮能显示加载态，然后替换为回答。

### DDL 查询

```json
POST /api/chat
{
  "user_id": "9b1a7c6e-6a11-4a65-a8ab-0f4b5f1c0001",
  "message": "这周有什么DDL？"
}
```

预期：

- 返回该用户未来 7 天或本周相关待办。
- 不编造不存在的 DDL。

### 清空网页上下文

```json
POST /api/chat/clear
{
  "user_id": "9b1a7c6e-6a11-4a65-a8ab-0f4b5f1c0001"
}
```

预期：

- `context=[]`。
- 页面聊天区清空。

### 眼镜接口

```http
GET /rizon/custom-agent?query=我是谁&user_id=9b1a7c6e-6a11-4a65-a8ab-0f4b5f1c0001
```

预期：

- HTTP 200。
- `answer` 非空。
- 不暴露内部 UUID 和账号名，除非演示明确需要。

## 8. 上线注意事项

- 不要改审核中的旧地址：`https://nancy-asked-rim-fit.trycloudflare.com`。
- 当前正式演示以 6666 公网地址为准。
- 如果替换后端，先在新端口影子验证，再切 6666。
- 切换前备份当前 `app.py` 和数据库。
- 前端静态文件只要求同源访问 API；如果后端拆到不同域名，需要额外处理 CORS，但当前不建议拆域名。
- 所有接口都必须返回 JSON；不要让 API 路径返回 HTML 404。
