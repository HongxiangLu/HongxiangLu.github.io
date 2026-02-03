import imaplib
import email
import datetime
import os
import subprocess
# 引入同级目录下的 config.py，用于配置变量
import config

def clean_text(text, encoding):
    """解码邮件文本"""
    if isinstance(text, bytes):
        return text.decode(encoding or 'utf-8', errors='ignore')
    return text


def get_email_sender(msg):
    """获取并清理发件人地址"""
    header_val = msg.get("From")
    if not header_val:
        return ""
    # email.utils.parseaddr 会把 "Name <email@xxx.com>" 解析成 ('Name', 'email@xxx.com')
    # 我们只取第二个元素，即纯邮箱地址
    return email.utils.parseaddr(header_val)[1].strip()


def get_email_content(msg):
    """从邮件对象中提取纯文本内容"""
    content = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset()
                content += payload.decode(charset or 'utf-8', errors='ignore')
    else:
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset()
        content = payload.decode(charset or 'utf-8', errors='ignore')
    return content.strip()


# --- Git操作第1部分：只负责拉取 ---
def git_pull():
    print(">>> 正在拉取远程更新 (Pull)...")
    # 这里复制你原有的 url 和 env 定义代码
    auth_url = f"https://{config.GITHUB_TOKEN}@github.com/{config.GITHUB_USER}/{config.GITHUB_REPO}.git"
    git_env = os.environ.copy()
    git_env["GIT_TERMINAL_PROMPT"] = "0"
    # 如果有代理配置，也加在这里

    os.chdir(config.REPO_PATH)

    # 只执行 pull
    # 建议加上 timeout 和 check=True，如果拉取失败直接抛出异常，脚本就会停止，不会继续写文件
    subprocess.run(
        [config.GIT_EXEC, 'pull', auth_url, 'main', '--no-edit', '--no-rebase'],
        check=True,
        env=git_env,
        timeout=120
    )
    print("✅ 拉取完成")


# --- Git操作第2部分：只负责提交和推送 ---
def git_commit_push(date_str):
    print(">>> 正在提交更改 (Push)...")
    # 这里同样需要 url 和 env 定义代码
    auth_url = f"https://{config.GITHUB_TOKEN}@github.com/{config.GITHUB_USER}/{config.GITHUB_REPO}.git"
    git_env = os.environ.copy()
    git_env["GIT_TERMINAL_PROMPT"] = "0"
    # 如果有代理配置，也加在这里

    os.chdir(config.REPO_PATH)

    try:
        # 1. ADD
        subprocess.run([config.GIT_EXEC, 'add', '.'], check=True, env=git_env)

        # 2. COMMIT
        subprocess.run(
            [config.GIT_EXEC, 'commit', '-m', f"Diary Upload: {date_str}"],
            check=True,
            env=git_env
        )

        # 3. PUSH
        subprocess.run(
            [config.GIT_EXEC, 'push', auth_url, 'main'],
            check=True,
            env=git_env,
            timeout=120
        )
        print("✅ 推送成功")
    except subprocess.CalledProcessError:
        print("--- 无变化或提交失败 ---")


def main():
    # 1. 确定我们要处理的时间范围：昨天 (脚本在今天凌晨运行)
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)

    # IMAP 搜索格式: "ON 31-Jan-2026"
    imap_date_str = yesterday.strftime("%d-%b-%Y")

    print(f"=== 任务开始: 处理 {yesterday} 的日记 ===")

    # 2.【新增】第一步先同步代码！
    # 建议加个 try-except，如果拉取失败就不继续了
    try:
        git_pull()
    except Exception as e:
        print(f"Git拉取失败，停止脚本以防冲突: {e}")
        return

    # 3. 连接邮箱、筛选邮件
    try:
        mail = imaplib.IMAP4_SSL(config.IMAP_SERVER)
        mail.login(config.EMAIL_USER, config.EMAIL_PASS)
        mail.select('INBOX')

        # 修改搜索策略：只按日期搜（靠谱），发件人我们自己过滤
        status, messages = mail.search(None, f'(ON "{imap_date_str}")')

        email_ids = messages[0].split()
        print(f"收到 {len(email_ids)} 封昨日邮件，开始筛选...")

        entries = []

        for e_id in email_ids:
            _, msg_data = mail.fetch(e_id, '(RFC822)')
            msg = email.message_from_bytes(msg_data[0][1])

            # --- 关键修改：Python 端严格过滤发件人 ---
            sender = get_email_sender(msg)
            # 转换为小写比较，防止大小写差异
            if config.ALLOWED_SENDER.lower() not in sender.lower():
                print(f"跳过非目标发件人: {sender}")
                continue

            print(f"发现有效日记，来自: {sender}")

            # 处理时间
            date_tuple = email.utils.parsedate_tz(msg['Date'])
            if date_tuple:
                local_date = datetime.datetime.fromtimestamp(email.utils.mktime_tz(date_tuple))
            else:
                local_date = datetime.datetime.now()  # 兜底

            content = get_email_content(msg)
            if content:
                entries.append((local_date, content))

        if not entries:
            print("📭 昨天没有收到符合要求的日记。")
            mail.logout()
            return

        # 按时间排序 (早发的在前)
        entries.sort(key=lambda x: x[0])

        # 4. 准备文件写入
        # 文件名格式: YYYY-MM.md (例如 2026-02.md)
        month_str = yesterday.strftime("%Y-%m")
        filename = f"{month_str}.md"
        full_path = os.path.join(config.REPO_PATH, config.DIARY_DIR, filename)

        # 确保目录存在
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        is_new_file = not os.path.exists(full_path)

        with open(full_path, 'a', encoding='utf-8') as f:
            # 如果是新文件（每月1号或者第一次写），写入 Hugo Stack Front Matter
            if is_new_file:
                print(f"创建新月度文件: {filename}")
                front_matter = f"""---
title: "{month_str} 日记"
date: {yesterday.strftime("%Y-%m-%d")}T00:00:00+08:00
slug: diary-{month_str}
draft: false
categories:
    - "日记"
---

> 本月日记归档。

"""
                f.write(front_matter)

            # 写入日期一级标题 (如果昨天已经写过，避免重复写日期头？
            # 简单起见，我们每次写入都带日期头，或者你可以先读取文件判断。
            # 这里按照你的需求：日期为一级标题)

            # 写入当天的所有内容
            f.write(f"\n# {yesterday.strftime('%m-%d')}\n\n")

            for time_obj, content in entries:
                time_str = time_obj.strftime("%H:%M")
                f.write(f"## {time_str}\n\n")
                # 处理一下邮件里的换行，将其变成 Markdown 的引用或者普通文本
                f.write(f"{content}\n\n")

        print("文件写入完成。")

        # 5. Git 推送
        git_commit_push(yesterday.strftime("%Y-%m-%d"))

        mail.logout()

    except Exception as e:
        print(f"❌ 发生严重错误: {e}")


if __name__ == "__main__":
    main()