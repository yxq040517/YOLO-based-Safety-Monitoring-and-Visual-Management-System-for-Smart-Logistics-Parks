# 登录恢复与检测进度实施计划

**Goal:** 完成已确认的两项稳定性修复，不改动检测规则、模型和业务数据。

**Architecture:** Auth Store 区分身份失效与临时故障，LoginPage 提供恢复视图；Workbench 分离模型与任务轮询。

**Tech Stack:** Vue、Pinia、Vue Router、Axios、Node 内置测试。

- [x] 添加 auth.test.mjs：网络/超时/服务错误保留凭据、401 清除、重试成功、并发合并、退出和新登录后的迟到响应隔离。
- [x] 添加 workbench.test.mjs：模型失败或等待时任务仍刷新、任务错误独立展示、任务归属和卸载取消。
- [x] 运行新增测试，确认原实现失败，再修改 auth.ts 和 WorkbenchPage.vue。
- [x] 修改 router.ts 的恢复失败导航及 LoginPage.vue 的连接恢复、重试与原页面跳转；补充路由回归验证。
- [x] 运行前端完整测试、格式检查、类型检查和生产构建。
- [x] 在隔离测试服务中验证保存会话后刷新失败、点击重新连接和恢复原站内页面；记录截图并关闭临时服务。
- [x] 更新修复记录，保存改动前备份和验证结果。
