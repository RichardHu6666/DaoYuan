# DaoYuan

这个仓库整理自 `Jarvis` 服务器 `/root` 下的三块核心代码，作为对外公开的代码快照上传：

- `decision/`：CampusJarvis 决策层与检索、路由、服务入口
- `data_clean/`：微信公众号与教务数据清洗、抽取、校验、入库链路
- `if_land_web-fusion/`：用户信息更新与前后端融合相关代码

这次上传刻意不包含独立 GitHub Pages 页面内容，只保留代码与必要说明文档，避免和单独维护的页面分支冲突。

## Directory Layout

```text
decision/
data_clean/
if_land_web-fusion/
```

## Notes

- 代码来源：`Jarvis` 服务器已有运行目录与展示快照
- 为了安全和整洁，仓库忽略了缓存、日志、SQLite 运行产物和测试报告
- 部分模块依赖部署时的环境变量、数据库路径和服务器目录结构，直接运行前需要按各子目录 README 配置
