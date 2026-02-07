import imaplib
import email
import datetime
import os
import subprocess
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
            [config.GIT_EXEC, 'commit', '-m', f"Diary upload automatically: {date_str}"],
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

    for e_id in email_ids:
        _, msg_data = mail.fetch(e_id, '(RFC822)')
        msg = email.message_from_bytes(msg_data[0][1])

        sender = get_email_sender(msg)
        if config.ALLOWED_SENDER.lower() not in sender.lower():
            print(f"跳过非目标发件人: {sender}")
            continue

        print(f"发现有效日记，来自: {sender}")

        # 处理时间
        date_tuple = email.utils.parsedate_tz(msg['Date'])
        if date_tuple:
            local_date = datetime.datetime.fromtimestamp(email.utils.mktime_tz(date_tuple))
        else:
            local_date = datetime.datetime.now()

        # 即使 IMAP 搜索返回了结果，也要在本地再次确认日期是否严格匹配
        # 注意：这里比较的是 .date() (年月日)，忽略具体的时分秒
        if local_date.date() != target_date:
            print(f"跳过非目标日期的邮件: {local_date.date()}")
            continue

        content = get_email_content(msg)
        if content:
            entries.append((local_date, content))

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

        f.write(f"\n# {target_date.strftime('%m-%d')}\n\n")

        for time_obj, content in entries:
            time_str = time_obj.strftime("%H:%M")
            f.write(f"## {time_str}\n\n{content}\n\n")

    print("文件写入完成。")
    mail.logout()
    return True  # 告诉主程序：干活了，请提交！


def main():
    # 1. 确定时间
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)

    print(f"=== 任务开始: 处理 {yesterday} 的日记 ===")

    # 2. 同步代码 (Fail-fast)
    try:
        git_pull()
    except Exception as e:
        print(f"Git拉取失败，停止脚本: {e}")
        return

    # 3. 处理邮件并写入文件
    try:
        # 调用刚才封装的函数，如果它返回 True，说明写入了新内容
        has_updates = process_emails(yesterday)

        if has_updates:
            # 4. 只有在有更新时才推送
            git_commit_push(yesterday.strftime("%Y-%m-%d"))
        else:
            print("--- 无新日记，无需 Git 推送 ---")

    except Exception as e:
        print(f"❌ 处理邮件或文件时发生错误: {e}")


if __name__ == "__main__":
    main()