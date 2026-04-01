import imaplib
import email
import datetime
import os
import subprocess
import time
# 引入同级目录下的 config.py，用于配置变量
import config


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


def _get_git_auth():
    """返回 Git 认证 URL 和环境变量（内部复用）"""
    auth_url = f"https://{config.GITHUB_TOKEN}@github.com/{config.GITHUB_USER}/{config.GITHUB_REPO}.git"
    git_env = os.environ.copy()
    git_env["GIT_TERMINAL_PROMPT"] = "0"
    return auth_url, git_env


# --- Git操作：拉取（失败会抛出异常） ---
def git_pull():
    print(">>> 正在拉取远程更新 (Pull)...")
    auth_url, git_env = _get_git_auth()
    os.chdir(config.REPO_PATH)
    subprocess.run(
        [config.GIT_EXEC, 'pull', auth_url, 'main', '--no-edit', '--no-rebase'],
        check=True,
        env=git_env,
        timeout=120
    )
    print("✅ 拉取完成")


# --- Git操作：推送（带重试，失败不中断） ---
def git_push(max_retries=3):
    """尝试推送本地 commit，失败不抛异常，返回是否成功"""
    auth_url, git_env = _get_git_auth()
    os.chdir(config.REPO_PATH)
    for attempt in range(1, max_retries + 1):
        try:
            subprocess.run(
                [config.GIT_EXEC, 'push', auth_url, 'main'],
                check=True,
                env=git_env,
                timeout=120
            )
            print("✅ 推送成功")
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"⚠️ 推送失败 (第 {attempt}/{max_retries} 次): {e}")
            if attempt < max_retries:
                time.sleep(5 * attempt)  # 递增等待
    print("❌ 推送在多次重试后仍然失败，将在下次运行时重试")
    return False


# --- Git操作：提交并推送 ---
def git_commit_push(date_str):
    print(">>> 正在提交更改...")
    _, git_env = _get_git_auth()
    os.chdir(config.REPO_PATH)

    try:
        subprocess.run([config.GIT_EXEC, 'add', '.'], check=True, env=git_env)
        subprocess.run(
            [config.GIT_EXEC, 'commit', '-m', f"Diary upload automatically: {date_str}"],
            check=True,
            env=git_env
        )
    except subprocess.CalledProcessError:
        print("--- 无变化，无需提交 ---")
        return

    git_push()


def process_emails(target_date):
    """
    连接邮箱，获取指定日期的日记，并写入本地文件。
    返回: True (如果有新日记写入), False (如果没有日记)
    """
    # 手动定义月份映射，确保生成如 "02-Feb-2026" 的标准格式
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    month_en = months[target_date.month - 1]
    imap_date_str = f"{target_date.day:02d}-{month_en}-{target_date.year}"

    # 连接邮箱
    mail = imaplib.IMAP4_SSL(config.IMAP_SERVER)
    mail.login(config.EMAIL_USER, config.EMAIL_PASS)
    mail.select('INBOX')

    # 搜索邮件
    status, messages = mail.search(None, f'(ON "{imap_date_str}")')
    email_ids = messages[0].split()
    print(f"收到 {len(email_ids)} 封昨日邮件，开始筛选...")

    entries = []

    skipped_sender = 0
    skipped_date = 0

    for e_id in email_ids:
        _, msg_data = mail.fetch(e_id, '(RFC822)')
        msg = email.message_from_bytes(msg_data[0][1])

        sender = get_email_sender(msg)
        if config.ALLOWED_SENDER.lower() not in sender.lower():
            skipped_sender += 1
            continue

        # 处理时间
        date_tuple = email.utils.parsedate_tz(msg['Date'])
        if date_tuple:
            local_date = datetime.datetime.fromtimestamp(email.utils.mktime_tz(date_tuple))
        else:
            local_date = datetime.datetime.now()

        # 即使 IMAP 搜索返回了结果，也要在本地再次确认日期是否严格匹配
        if local_date.date() != target_date:
            skipped_date += 1
            continue

        content = get_email_content(msg)
        if content:
            entries.append((local_date, content))

    if skipped_sender or skipped_date:
        print(f"已跳过: 发件人不符 {skipped_sender} 封, 日期不符 {skipped_date} 封")

    if not entries:
        print("📭 昨天没有收到符合要求的日记。")
        mail.logout()
        return False  # 告诉主程序：没干活，不用提交

    # 按时间排序
    entries.sort(key=lambda x: x[0])

    # 准备写入文件
    month_str = target_date.strftime("%Y-%m")
    filename = f"{month_str}.md"
    full_path = os.path.join(config.REPO_PATH, config.DIARY_DIR, filename)

    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    is_new_file = not os.path.exists(full_path)

    with open(full_path, 'a', encoding='utf-8') as f:
        if is_new_file:
            print(f"创建新月度文件: {filename}")
            front_matter = f"""---
title: "{month_str} 日记"
date: {target_date.strftime("%Y-%m-%d")}T00:00:00+08:00
slug: diary-{month_str}
draft: false
categories:
    - "日记"
---

> 本月日记归档。

"""
            f.write(front_matter)

        f.write(f"## {target_date.strftime('%m-%d')}\n\n")

        for time_obj, content in entries:
            time_str = time_obj.strftime("%H:%M")
            f.write(f"### {time_str}\n\n{content}\n\n")

    print("文件写入完成。")
    mail.logout()
    return True  # 告诉主程序：干活了，请提交！


def main():
    # 1. 确定时间
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)

    print(f"=== 任务开始: 处理 {yesterday} 的日记 ===")

    # 2. 先推送残留的本地 commit（容错，不中断）
    print(">>> 尝试推送残留 commit...")
    git_push()

    # 3. 拉取远程最新内容（Fail-fast）
    try:
        git_pull()
    except Exception as e:
        print(f"❌ Git 拉取失败，停止脚本: {e}")
        return

    # 4. 处理邮件并写入文件
    try:
        has_updates = process_emails(yesterday)

        if has_updates:
            # 5. 提交并推送新内容
            git_commit_push(yesterday.strftime("%Y-%m-%d"))
        else:
            print("--- 无新日记，无需 Git 推送 ---")

    except Exception as e:
        print(f"❌ 处理邮件或文件时发生错误: {e}")


if __name__ == "__main__":
    main()