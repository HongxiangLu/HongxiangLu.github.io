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
    # 连接邮箱
    mail = imaplib.IMAP4_SSL(config.IMAP_SERVER)
    mail.login(config.EMAIL_USER, config.EMAIL_PASS)
    mail.select('INBOX')

    # 将 date 对象转为 datetime，以便精确过滤时间范围 (从开始日的 00:00:00 到结束日的 23:59:59)
    start_datetime = datetime.datetime.combine(start_date, datetime.time.min)
    end_datetime = datetime.datetime.combine(end_date, datetime.time.max)

    # 格式化日期给 IMAP 使用 (例如: "01-Apr-2026")
    # 注意：IMAP BEFORE 搜索条件是不包含指定当天的，因此需要 end_date 往后推一天
    imap_since = start_date.strftime("%d-%b-%Y")
    imap_before = (end_date + datetime.timedelta(days=1)).strftime("%d-%b-%Y")

    search_criteria = f'(SINCE "{imap_since}" BEFORE "{imap_before}")'
    
    status, messages = mail.search(None, search_criteria)
    email_ids = messages[0].split()
    logging.info(f"IMAP搜索到 {len(email_ids)} 封邮件，开始在本地进行精确筛选...")

    entries = []
    skipped_sender = 0
    skipped_date = 0

    for e_id in email_ids:
        _, msg_data = mail.fetch(e_id, '(RFC822)')
        msg = email.message_from_bytes(msg_data[0][1])

        # 检查发件人 (精确匹配)
        sender = get_email_sender(msg)
        if target_sender.lower() != sender.lower():
            skipped_sender += 1
            continue

        # 解析处理时间
        date_tuple = email.utils.parsedate_tz(msg['Date'])
        if date_tuple:
            local_date = datetime.datetime.fromtimestamp(email.utils.mktime_tz(date_tuple))
        else:
            local_date = datetime.datetime.now()

        # 严格判断本地时间是否在指定时间范围内
        if not (start_datetime <= local_date <= end_datetime):
            skipped_date += 1
            continue

        content = get_email_content(msg)
        if content:
            entries.append((local_date, content))

    if skipped_sender or skipped_date:
        logging.info(f"已跳过: 发件人不符 {skipped_sender} 封, 日期范围不符 {skipped_date} 封")

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
    # 示例用法：可根据需要调整特定时间范围和指定发件人
    # 例如：提取 2026年4月1日 到 2026年4月30日 期间的邮件
    start_date = datetime.date(2026, 4, 15)
    end_date = datetime.date(2026, 4, 30)
    
    # 也可以直接传入具体的发件人邮箱，例如 "example@test.com"
    target_sender = config.ALLOWED_SENDER  

    logging.info(f"=== 任务开始: 处理 {start_date} 到 {end_date} 期间，发件人为 '{target_sender}' 的邮件 ===")

    try:
        process_emails(start_date, end_date, target_sender)
    except Exception as e:
        logging.error(f"处理邮件时发生错误: {e}")


if __name__ == "__main__":
    main()
