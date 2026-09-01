import imaplib
import datetime
import os
import subprocess
import time
import logging
from email import message_from_bytes
# 引入同级目录下的 config.py，用于配置变量
import config
from diary_fetch import (
    find_sent_mailbox,
    get_email_content,
    get_email_sender,
    get_email_sent_datetime,
    quote_imap_mailbox,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)


GIT_ENV = os.environ.copy()
GIT_ENV["GIT_TERMINAL_PROMPT"] = "0"


# --- Git操作：拉取（失败会抛出异常） ---
def git_pull():
    logging.info("正在拉取远程更新 (Pull)...")
    os.chdir(config.REPO_PATH)
    subprocess.run(
        [config.GIT_EXEC, 'pull', 'origin', 'main', '--no-edit', '--no-rebase'],
        check=True,
        env=GIT_ENV,
        timeout=120
    )
    logging.info("✅ 拉取完成")


# --- Git操作：推送（带重试，失败不中断） ---
def git_push(max_retries=3):
    """尝试推送本地 commit，失败不抛异常，返回是否成功"""
    os.chdir(config.REPO_PATH)
    for attempt in range(1, max_retries + 1):
        try:
            subprocess.run(
                [config.GIT_EXEC, 'push', 'origin', 'main'],
                check=True,
                env=GIT_ENV,
                timeout=120
            )
            logging.info("✅ 推送成功")
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logging.warning(f"推送失败 (第 {attempt}/{max_retries} 次): {e}")
            if attempt < max_retries:
                time.sleep(5 * attempt)  # 递增等待
    logging.error("推送在多次重试后仍然失败，将在下次运行时重试")
    return False


# --- Git操作：提交并推送 ---
def git_commit_push(date_str):
    logging.info("正在提交更改...")
    os.chdir(config.REPO_PATH)

    try:
        subprocess.run([config.GIT_EXEC, 'add', '.'], check=True, env=GIT_ENV)
        subprocess.run(
            [config.GIT_EXEC, 'commit', '-m', f"diary: 自动上传日记 {date_str}"],
            check=True,
            env=GIT_ENV
        )
    except subprocess.CalledProcessError:
        logging.info("无变化，无需提交")
        return

    git_push()


def process_emails(target_date):
    """
    连接邮箱，获取指定日期的日记，并写入本地文件。
    返回: True (如果有新日记写入), False (如果没有日记)
    """
    # 连接邮箱并选择已发送目录。腾讯企业邮不支持 EXAMINE，因此使用 SELECT；
    # 邮件读取使用 BODY.PEEK[]，不会修改已读标记。
    mail = imaplib.IMAP4_SSL(config.IMAP_SERVER)
    mail.login(config.EMAIL_USER, config.EMAIL_PASS)
    sent_mailbox = find_sent_mailbox(mail)
    select_status, _ = mail.select(quote_imap_mailbox(sent_mailbox))
    if select_status != "OK":
        raise RuntimeError("无法打开已发送文件夹")
    logging.info(f"已选择已发送文件夹: {sent_mailbox}")

    # 腾讯企业邮的 SENTSINCE 不可靠，因此获取全部邮件并在本地按发送日期筛选。
    status, messages = mail.search(None, "ALL")
    if status != "OK":
        raise RuntimeError("无法搜索已发送文件夹中的邮件")
    email_ids = messages[0].split()
    logging.info(f"IMAP已发送文件夹共有 {len(email_ids)} 封邮件，开始按发送时间在本地精确筛选...")

    entries = []

    skipped_sender = 0
    skipped_invalid_date = 0
    skipped_date = 0

    for e_id in email_ids:
        _, msg_data = mail.fetch(e_id, '(BODY.PEEK[])')
        msg = message_from_bytes(msg_data[0][1])

        sender = get_email_sender(msg)
        # 精确判定发件人
        if sender.lower() != config.ALLOWED_SENDER.lower():
            skipped_sender += 1
            continue

        sent_datetime = get_email_sent_datetime(msg)
        if sent_datetime is None:
            skipped_invalid_date += 1
            continue

        if sent_datetime.date() != target_date:
            skipped_date += 1
            continue

        content = get_email_content(msg)
        if content:
            entries.append((sent_datetime, content))

    if skipped_sender or skipped_invalid_date or skipped_date:
        logging.info(
            f"已跳过: 发件人不符 {skipped_sender} 封, "
            f"发送时间无效 {skipped_invalid_date} 封, "
            f"发送日期不符 {skipped_date} 封"
        )

    if not entries:
        logging.info("📭 没有收到符合要求的日记。")
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
            logging.info(f"创建新月度文件: {filename}")
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

    logging.info("文件写入完成。")
    mail.logout()
    return True  # 告诉主程序：干活了，请提交！


def main():
    # 1. 确定时间
    # today = datetime.date(2026, 4, 27)
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)

    logging.info(f"=== 任务开始: 处理 {yesterday} 的日记 ===")

    # 2. 先推送残留的本地 commit（容错，不中断）
    logging.info("尝试推送残留 commit...")
    git_push()

    # 3. 拉取远程最新内容（Fail-fast）
    try:
        git_pull()
    except Exception as e:
        logging.error(f"Git 拉取失败，停止脚本: {e}")
        return

    # 4. 处理邮件并写入文件
    try:
        has_updates = process_emails(yesterday)

        if has_updates:
            # 5. 提交并推送新内容
            git_commit_push(yesterday.strftime("%Y-%m-%d"))
        else:
            logging.info("无新日记，无需 Git 推送")

    except Exception as e:
        logging.error(f"处理邮件或文件时发生错误: {e}")


if __name__ == "__main__":
    main()
