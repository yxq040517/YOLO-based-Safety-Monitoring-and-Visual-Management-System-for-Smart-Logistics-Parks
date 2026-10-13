# 稳定性、性能与交互优化实施计划

> 使用已确认的设计方案，在当前会话逐项执行。每项先验证回归测试失败，再修复并验证通过。

**Goal:** 修复概览图表、轮询生命周期、异步 API 数据库阻塞和详情请求竞争。

**Architecture:** 保持现有页面和 API；前端共享轮询统一调度，详情加载使用取消及归属检查；后端在线程池中执行完整同步事务。

**Tech Stack:** Vue 3、TypeScript、ECharts、Node 内置测试、FastAPI、SQLAlchemy、pytest。

## 全局约束

- 保持现有 YOLO 权重、训练数据、业务记录、账号和检测规则。
- 不新增测试框架依赖；前端测试复用现有 Vue、TypeScript 与 ECharts。
- 所有 SQLAlchemy Session 在线程内创建并关闭。
- 基线：后端 57 个测试通过，前端构建通过。
- 用户已确认完整方案；设计见 `docs/superpowers/specs/2026-10-12-stability-performance-design.md`。

## Task 1：前端轮询和统计图表

**Files:** `frontend/src/composables.ts`、`frontend/src/components/AnalyticsChart.vue`、`frontend/tests/helpers.mjs`、`frontend/tests/polling.test.mjs`、`frontend/tests/chart.test.mjs`、`frontend/package.json`。

**Interfaces:** 保持 `usePolling(action, interval, enabled)` 返回 `loading`、`error`、`refresh`；重叠 `refresh()` 等待合并后的刷新完成。

- [x] 添加真实 Vue 生命周期、受控定时器、ECharts SVG 渲染测试。
- [x] 运行 `npm.cmd test`，确认可见性切换留下多条定时链及柱形未绘制的测试失败。
- [x] 将轮询改为单一刷新任务和单一后续定时器；所有刷新完成后统一排程，隐藏/禁用/卸载取消排程。
- [x] 在 `AnalyticsChart.vue` 导入并注册 `BarChart`。
- [x] 运行 `npm.cmd test`，确认轮询及柱形测试通过。

## Task 2：异步 API 数据库事务

**Files:** `backend/app/main.py`、`backend/tests/test_async_job_submission.py`、`backend/tests/test_browser_session.py`。

**Interfaces:** 新增同步 `persist_uploaded_job(...)`、`cleanup_unpersisted_upload(job_id, destination)`、`create_browser_job(job_id, owner_id, confidence, classes)`；异步路由使用 `run_in_threadpool` 调用。

- [x] 用隔离 SQLite 数据库验证上传事务不在事件循环线程执行。
- [x] 验证队列已满时无持久化任务与上传文件，执行器提交失败时任务记录为失败并保留原素材。
- [x] 用受控 WebSocket 验证浏览器会话创建、关闭和名额释放。
- [x] 运行 `..\.venv\Scripts\python.exe -m pytest tests/test_async_job_submission.py tests/test_browser_session.py -q`，确认线程检查失败。
- [x] 在工作线程中创建并完成完整事务；把失败状态写入和上传清理也放到工作线程。
- [x] 重跑上述测试并确认通过。

## Task 3：风险详情请求竞争

**Files:** `frontend/src/composables.ts`、`frontend/src/pages/EventsPage.vue`、`frontend/tests/latest-request.test.mjs`。

**Interfaces:** 新增 `useLatestRequest<T>(action)`，返回 `data`、`loading`、`error`、`load`、`clear`；action 接收目标 id 与 AbortSignal，较早响应不覆盖当前目标。

- [x] 添加快速切换、旧请求晚到、失败、清除和卸载测试。
- [x] 运行 `npm.cmd test`，确认缺失行为的测试失败。
- [x] 实现请求取消、请求归属验证和状态归属验证。
- [x] EventsPage 使用该接口加载深链接事件；打开列表事件或关闭抽屉时使旧请求失效。
- [x] 重跑前端测试并确认通过。

## Task 4：整体验证与文档

**Files:** `README.md`、设计和实施文档。

- [x] 更新 README 的前端测试命令及本轮实际行为变化。
- [x] 运行后端完整测试 `..\.venv\Scripts\python.exe -m pytest tests -q`。
- [x] 运行前端 `npm.cmd test`、`npm.cmd run typecheck`、`npm.cmd run build`。
- [x] 检查新增代码与本轮修改的格式、类型、生命周期资源释放及既有 API 兼容性。
- [x] 必要时启动隔离测试服务并检查概览和风险详情页面。
- [x] 将每项验证结果和仍需进一步评估的方向写入交付说明。
