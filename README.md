# 行知学园 · 大学院生物／化学

网站：https://saigunww.github.io/daigakuin-info/

保留原网站的课程介绍、师资、学生、升学经验、研究室查询和四种语言，移除 AI 择校栏目，新增「每日研究」与自动更新的数据源。

## 数据来源与更新

| 内容 | 来源 | 频率 |
| --- | --- | --- |
| 合格榜 | 指定 Google Drive 文件夹与服务器 `Documents/合格榜` 中的海报 | 每小时检查 |
| 课程表 | 指定 Google 表格的「生物」「化学」工作表 | 每小时检查 |
| 出愿信息 | 原有 100 个专攻对应的大学官方页面和募集要项 | 每天核查；失败来源每小时重试 |
| 每日研究 | Europe PMC / PubMed 收录的生物、生化、化学、AI 生命科学期刊论文 | 每个日本日期最多新增 3 篇，保留历史并去重 |

课表按用户指定的初次排课表同步。原表不记录后续调课；网站已标明这一限制，仅导出课程、日期、时间、课次、内容和授课形式，不发布教师内部备注、录制要求等列。

出愿页面展示最新官方通知、募集要项链接、来源核查日期和可提取的日程原文。网站原有的考试科目、材料清单、旧日程仍标为参考资料；不能把「官网今天读取成功」理解为「全部旧资料今天已核实」。日期提取不猜年份、不把考试日当出愿日，也不把不同专攻、招生方式或批次合并。只有明确配置 `date_match` 的专攻、学位、入学期、批次、招生方式、截止类型全部匹配时，才能更新专攻的结构化截止日期；其余候选在官网信息区单独展示。页面失效、证书错误、PDF 解析失败时保留已有资料并显示来源状态。迁移后的官方地址维护于 `config/official_sources.json`。

论文条目保留原文标题、期刊、发表日期、收录日期和论文链接，不生成未经原文支持的研究结论。排除预印本、综述、撤稿和未来发表日期。来源不可用或没有合适新论文时保留已有条目。

合格榜按原文件内容校验去重，生成适合网页的 WebP 图片，保留原始海报不修改。无法确定年度的海报显示「未分年度」。本任务已完成本地与网盘的合并；网站的定时任务只读取这两个来源，不删除或改写原文件。

## 服务器运行

同步环境为 Python 3.12；另需系统 `pdftotext`、Git 和已登录的 GitHub CLI。

```bash
cd /home/admin-coach-ai/Documents/大学院生化网页/github
../.sync-venv/bin/python -m pip install -r requirements-sync.txt
../.sync-venv/bin/python scripts/test_sync.py
../.sync-venv/bin/python scripts/sync_data.py
../.sync-venv/bin/python scripts/validate_data.py
../.sync-venv/bin/python scripts/sync_and_publish.py
```

Google 凭据从服务器既有 `~/.config/coach-google-sheets/` 中读取并在内存刷新：课表使用 `token.json`，网盘只读使用 `inventory_drive_readonly_token.json`。凭据不进入代码、公开 JSON 或 GitHub。私有运行日志、缓存和锁放在被 Git 忽略的 `.sync-state/`。

`deploy/` 提供用户级 systemd service/timer。每小时日本时间第 17 分钟（加最多 60 秒错峰）执行；服务器需保持开机联网。启用 `Persistent=true` 可在恢复运行时补跑，用户开启 linger 后不依赖交互登录。

```bash
systemctl --user status daigakuin-info-update.timer
systemctl --user start daigakuin-info-update.service
journalctl --user -u daigakuin-info-update.service -n 80 --no-pager
```

发布器使用锁避免重叠执行，仅暂存五个公开 JSON 和海报图片。有未提交的源代码改动或未经发布器识别的本地提交时停止；不会自动发布手工修改。同步后校验、提交并推送到 `main`，沿用 GitHub Pages 的 `main /` 发布设置。没有内容变化则不新建提交。推送失败会保留本地提交重试；远端变动仅对发布器自己的数据提交尝试 rebase，冲突停止，不强制推送。任务日志会显示失败原因。

推送成功后，从对应提交复制公开网站文件到同目录下的 `网页文件/`，以保持本地网页副本与已发布代码一致；保留既有备份和其他文件。

## 校验

`scripts/test_sync.py` 覆盖日期不跨年猜测、招生批次保护、课表字段白名单、论文日期／类型和官网域名边界。
`scripts/validate_data.py` 校验五个快照及海报引用。
`scripts/check_browser.py` 使用系统 Chrome 和 Python Playwright 验证四种语言、导航、筛选、弹窗、手机布局及单一数据源失败时的回退，退出时关闭临时预览服务器。浏览器校验额外依赖 `playwright`。
