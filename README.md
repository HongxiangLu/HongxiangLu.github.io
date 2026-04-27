# Hongxiang LU's Personal Blog & Diary System

这是一个基于 **Hugo (Stack Theme)** 构建的个人博客系统，集成了自动化日记处理流程，方便在不同平台（如邮件、移动端）随时记录生活并自动同步到 GitHub Pages。

## 🚀 项目核心组件

### 1. `diary_bot.py` (自动化日记助手)
这是一个关键的 Python 自动化脚本，其主要职责包括：
- **邮件抓取**：连接到指定的 IMAP 邮箱服务器（由 `config.py` 配置），自动筛选来自授信发件人的特定日期邮件。
- **内容解析**：将邮件正文解析为 Markdown 格式，并按时间顺序归档。
- **自动同步**：将解析后的日记写入本地的 `content/diary/` 目录，并自动执行 `git add`, `git commit` 以及 `git push` 操作，确保远程博客实时更新。

### 2. 内容分类与结构
项目采用了 [Hugo Stack Theme](https://github.com/CaiJimmy/hugo-theme-stack) 进行展示，内容主要分为以下几类：

- **`content/diary/` (日记)**：
  - 以月份为单位进行归档（如 `2026-04.md`）。
  - 记录个人的每日琐碎与随笔，主要通过 `diary_bot.py` 自动化维护。
- **`content/tech/` (技术与工作)**：
  - 存放技术笔记（如《人工智能基础》学习笔记）。
  - 记录实习工作进展（如文通天下实习记录）。
- **`content/selfie/` (生活记录)**：
  - 用于展示日常生活照片与简短记录。
- **`themes/stack/demo/content` (参考模板)**：
  - 这是 Stack 主题自带的示例目录，展示了标准的 Hugo 内容管理方式：
    - `post/`：常规博客文章。
    - `page/`：关于我、归档等静态页面。
    - `categories/`：分类体系结构。

---

## 🛠 Git 提交规范 (Git Commit Convention)

为了保持提交历史的清晰和可读性，本项目遵循以下提交规范。在执行 `git commit -m` 时，请根据修改内容选择合适的学术前缀：

| 前缀 | 适用场景 | 示例 |
| :--- | :--- | :--- |
| **`diary:`** | 自动或手动更新日记内容 | `diary: upload manually 2026-04-27` |
| **`work:`** | 更新实习工作、研究进展、学习笔记 | `work: add research notes on TTS models` |
| **`life:`** | 上传照片、更新生活动态（Selfie 模块） | `life: add new daily selfies for April` |
| **`feat:`** | 为自动化脚本（如 `diary_bot.py`）添加新功能 | `feat: add retry logic for git push` |
| **`fix:`** | 修复 Bug 或配置文件错误 | `fix: resolve date format issue in diary bot` |
| **`docs:`** | 修改 README 或其他项目文档 | `docs: update commit convention in README` |
| **`refactor:`** | 重构代码，不改变原有逻辑 | `refactor: clean up email parsing logic` |
| **`style:`** | 修改样式文件 (CSS/SCSS) 或格式调整 | `style: update gallery layout to 3 columns` |


## ⚙️ 快速配置
1. 修改 `config.py` 中的邮箱与 GitHub Token。
2. 确保本地安装了 Python 3 及其依赖。
3. 如果是在 Linux 服务器上运行，建议配置 `cron` 定时执行 `diary_bot.py`。
