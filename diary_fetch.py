import imaplib
import email
import datetime
import os
import logging
import re
# 引入同级目录下的 config.py，用于配置变量
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)


LIST_RESPONSE_RE = re.compile(
    rb'^\((?P<flags>[^)]*)\)\s+(?:NIL|"(?:\\.|[^"])*")\s+(?P<name>.+)$'
)


def parse_mailbox_list_item(item):
    """解析一条 IMAP LIST 响应，返回 (flags, mailbox_name)。"""
    if not isinstance(item, bytes):
        return None

    match = LIST_RESPONSE_RE.match(item.strip())
    if not match:
        return None

    flags = {flag.lower() for flag in match.group("flags").split()}
    name = match.group("name").strip()

    # LIST 中带空格的目录名会被双引号包裹；去掉引号并还原转义字符。
    if len(name) >= 2 and name.startswith(b'"') and name.endswith(b'"'):
        name = name[1:-1].replace(b'\\"', b'"').replace(b'\\\\', b'\\')

    try:
        mailbox_name = name.decode("ascii")
    except UnicodeDecodeError:
        mailbox_name = name.decode("utf-8")

    return flags, mailbox_name


def find_sent_mailbox(mail):
    """查找服务器的已发送文件夹，优先使用 IMAP 的 \\Sent 标记。"""
    status, mailbox_items = mail.list()
    if status != "OK":
        raise RuntimeError("无法读取邮箱文件夹列表")

    available_mailboxes = {}
    for item in mailbox_items or []:
        parsed = parse_mailbox_list_item(item)
        if not parsed:
            continue

        flags, mailbox_name = parsed
        if b"\\sent" in flags:
            return mailbox_name
        available_mailboxes[mailbox_name.casefold()] = mailbox_name

    # 某些服务器不返回 SPECIAL-USE 标记，兼容常见的英文目录名称。
    for candidate in ("Sent Messages", "Sent", "Sent Items"):
        mailbox_name = available_mailboxes.get(candidate.casefold())
        if mailbox_name:
            return mailbox_name

    raise RuntimeError("未找到服务器的已发送文件夹")


def quote_imap_mailbox(mailbox_name):
    """将目录名编码为可安全传给 imaplib SELECT 的带引号参数。"""
    escaped_name = mailbox_name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped_name}"'


def get_email_sender(msg):
    """获取并清理发件人地址"""
    return email.utils.parseaddr(msg.get("From", ""))[1].strip()


def get_email_sent_datetime(msg):
    """读取邮件头 Date，并转换为本机时区下的无时区 datetime。"""
    try:
        sent_datetime = email.utils.parsedate_to_datetime(msg.get("Date"))
        if sent_datetime and sent_datetime.tzinfo is not None:
            sent_datetime = sent_datetime.astimezone().replace(tzinfo=None)
        return sent_datetime
    except (TypeError, ValueError, OverflowError, OSError):
        return None


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
    
    content = content.strip()
    # 统一换行符，将 \r\n 转换为 \n
    content = content.replace('\r\n', '\n')
    # 将3个及以上的连续换行替换为2个换行（即段落之间只保留一个空行）
    content = re.sub(r'\n{3,}', '\n\n', content)
    return content


def process_emails(start_date, end_date, target_sender):
    """
    连接邮箱，获取特定时间范围内、指定发件人的邮件，并处理内容。
    start_date, end_date: datetime.date 对象
    target_sender: 指定发件人邮箱
    """
    # 连接邮箱，并选择服务器标记的已发送文件夹。
    # 腾讯企业邮不接受 imaplib 只读模式所使用的 EXAMINE，因此这里使用
    # 兼容性更好的 SELECT；下方读取邮件时使用 BODY.PEEK[]，不会修改已读标记。
    mail = imaplib.IMAP4_SSL(config.IMAP_SERVER)
    mail.login(config.EMAIL_USER, config.EMAIL_PASS)
    sent_mailbox = find_sent_mailbox(mail)
    select_status, _ = mail.select(quote_imap_mailbox(sent_mailbox))
    if select_status != "OK":
        raise RuntimeError("无法打开已发送文件夹")
    logging.info(f"已选择已发送文件夹: {sent_mailbox}")

    # 腾讯企业邮的 SENTSINCE/SENTBEFORE 可能直接返回整个目录，无法作为
    # 可靠的日期初筛。这里获取已发送目录中的全部邮件，再统一依据邮件头
    # Date 换算后的本地发送时间进行精确筛选。
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
        msg = email.message_from_bytes(msg_data[0][1])

        # 检查发件人 (精确匹配)
        sender = get_email_sender(msg)
        if target_sender.lower() != sender.lower():
            skipped_sender += 1
            continue

        # 解析邮件头 Date，后续筛选、排序和归档全部以发送时间为准。
        sent_datetime = get_email_sent_datetime(msg)
        if sent_datetime is None:
            skipped_invalid_date += 1
            continue

        # 完全在本地按照发送日期核对目标范围。
        if not (start_date <= sent_datetime.date() <= end_date):
            skipped_date += 1
            continue

        content = get_email_content(msg)
        if content:
            entries.append((sent_datetime, content))

    if skipped_sender or skipped_invalid_date or skipped_date:
        logging.info(
            f"已跳过: 发件人不符 {skipped_sender} 封, "
            f"发送时间无效 {skipped_invalid_date} 封, "
            f"发送时间范围不符 {skipped_date} 封"
        )

    if not entries:
        logging.info("📭 没有收到符合要求的邮件。")
        mail.logout()
        return False

    # 按时间排序
    entries.sort(key=lambda x: x[0])

    # 按照日期分组
    grouped_entries = {}
    for time_obj, content in entries:
        day_key = time_obj.date()
        grouped_entries.setdefault(day_key, []).append((time_obj, content))

    # 按天处理写入
    for target_date in sorted(grouped_entries.keys()):
        day_entries = grouped_entries[target_date]
        
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

            f.write(f"\n## {target_date.strftime('%m-%d')}\n")

            for time_obj, content in day_entries:
                time_str = time_obj.strftime("%H:%M")
                f.write(f"\n### {time_str}\n\n{content}\n")

        logging.info(f"[{target_date}] 的日记已写入 {filename}。")

    mail.logout()
    return True


def main():
    # 设置要提取的发送日期范围。
    start_date = datetime.date(2026, 5, 29)
    end_date = datetime.date(2026, 5, 31)
    
    # 也可以直接传入具体的发件人邮箱，例如 "example@test.com"
    target_sender = config.ALLOWED_SENDER  

    logging.info(f"=== 任务开始: 处理 {start_date} 到 {end_date} 期间，发件人为 '{target_sender}' 的邮件 ===")

    try:
        process_emails(start_date, end_date, target_sender)
    except Exception as e:
        logging.error(f"处理邮件时发生错误: {e}")


if __name__ == "__main__":
    main()
